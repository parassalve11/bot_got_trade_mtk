"""Built-in signal source: MT5 candles -> UT Bot -> the same durable queue as webhooks.

Runs inside the worker (the only process allowed to use MT5). Every signal becomes a
normal AlertEnvelope, so all executor risk checks, deduplication and recovery apply.
Event IDs are derived from the candle time, so re-evaluating a candle after a restart
can never create a second order.
"""

import logging
import math
from datetime import datetime, timezone

from app.control import effective_stream_mode
from app.schemas import ENTRY_EVENTS, AlertEnvelope
from app.signals.ut_engine import decide, htf_direction_at, htf_series, load_streams, signal_series
from app.trading.errors import Reject, Retryable

log = logging.getLogger(__name__)
# Never act on a candle that closed long ago (e.g. worker restarted late): stay flat.
MAX_CANDLE_LAG_SECONDS = 120


class SignalEngine:
    def __init__(self, settings, db, broker, symbols, *, mode=None, streams=None):
        self.settings, self.db, self.broker, self.symbols = settings, db, broker, symbols
        self.mode = mode or settings.engine_mode  # "watch" logs only, "trade" enqueues orders
        all_streams = streams if streams is not None else load_streams(settings.engine_config_path)
        self.streams = list(all_streams)  # disabled streams can be switched on from the dashboard
        self.last_error = {}

    def _guard(self, stream, fn):
        key = (stream.instance, stream.tv_symbol)
        try:
            result = fn()
            self.last_error.pop(key, None)
            return result
        except (Retryable, Reject) as exc:
            if self.last_error.get(key) != str(exc):  # Log changes, not every poll.
                log.warning("engine_poll_failed", extra={"reason": str(exc), "event_id": stream.tv_symbol})
                self.last_error[key] = str(exc)
        except Exception:
            # A signal bug must never stop the worker that manages open positions.
            if self.last_error.get(key) != "unexpected":
                log.exception("engine_unexpected_failure", extra={"event_id": stream.tv_symbol})
                self.last_error[key] = "unexpected"
        return None

    def poll(self, now: float):
        """Evaluate every stream first, then queue closes before entries.

        Several streams can share a symbol (split targets). Queuing all closes for a candle before
        any new entry avoids briefly holding opposite positions on the same symbol.
        """
        pending = []
        for stream in self.streams:
            mode = effective_stream_mode(self.db, stream, self.mode)
            if mode == "off":
                continue
            item = self._guard(stream, lambda s=stream, m=mode: self.poll_stream(s, now, watch_only=m != "trade"))
            if item:
                pending.append((stream, item))
        pending.sort(key=lambda p: 0 if p[1]["alert"].context.event not in ENTRY_EVENTS else 1)
        for stream, item in pending:
            def emit(item=item):
                self.emit(item["alert"], item["rule"], now, watch_only=item["watch_only"])
                self.db.set_state(item["key"], item["candle"])
            self._guard(stream, emit)

    def state_key(self, stream):
        return f"engine:{stream.instance}:{stream.tv_symbol}:{stream.timeframe}"

    def poll_stream(self, stream, now: float, *, watch_only: bool | None = None):
        """Evaluate the newest closed candle. Returns a pending alert to emit, or None."""
        watch_only = stream.watch_only if watch_only is None else watch_only
        rule = self.symbols.resolve(stream.tv_symbol, require_enabled=False)
        recent = self.broker.rates(rule.broker_symbol, stream.timeframe, 3)
        closed = [bar for bar in recent if bar["time"] + stream.seconds <= now]
        if not closed:
            return
        last = closed[-1]
        key = self.state_key(stream)
        if self.db.get_state(key) == last["time"]:
            return  # Already evaluated this candle.
        close_time = last["time"] + stream.seconds
        if now - close_time > MAX_CANDLE_LAG_SECONDS:
            self.db.set_state(key, last["time"])
            return
        if self.db.pending_events(rule.broker_symbol):
            return  # Let queued work finish so the position state below is current.
        bars = self.broker.rates(rule.broker_symbol, stream.timeframe, stream.history_bars + 3)
        bars = [b for b in bars if b["time"] <= last["time"]]
        if not bars or bars[-1]["time"] != last["time"]:
            raise Retryable("engine_history_not_aligned")
        symbol = self.broker.symbol(rule.broker_symbol)
        signal = signal_series(bars, stream, symbol.tick_size)[-1]
        position = self.journal_position(stream)
        trend = None
        if signal is not None and stream.htf_filter != "none":
            htf = [b for b in self.broker.rates(rule.broker_symbol, stream.htf_filter, 500) if b["time"] + 14400 <= now]
            if not htf:
                raise Retryable("engine_htf_history_unavailable")
            trend = htf_direction_at(htf_series(htf, stream), close_time)
        action = decide(signal, position["side"] if position else None, stream, trend)
        if action:
            alert = self.build_alert(stream, action, signal, position, close_time, symbol.tick_size, now)
            # Candle is marked as evaluated only after the alert is queued (see poll()).
            return {"alert": alert, "rule": rule, "watch_only": watch_only, "key": key, "candle": last["time"]}
        self.db.set_state(key, last["time"])
        return None

    def journal_position(self, stream):
        matches = [
            p
            for p in self.db.open_positions()
            if p["instance"] == stream.instance and p["tv_symbol"] == stream.tv_symbol
        ]
        return matches[0] if matches else None

    def build_alert(self, stream, action, signal, position, close_time, tick_size, now):
        close_ms = int(round(close_time * 1000))
        if action == "close":
            trade_id, side, event, previous = position["trade_id"], position["side"], "opposite_signal", None
            loss_ticks = max(1.0, float(math.ceil(position["stop_distance"] / tick_size - 1e-9)))
            target = position["target_distance"]
            profit_ticks = None if target is None else max(1.0, float(math.ceil(target / tick_size - 1e-9)))
        else:
            side, event = signal.side, action
            trade_id = (
                f"bytefx:1.1:{stream.instance}:{stream.tv_symbol}:{stream.timeframe}:{close_ms}:{side}"
            )
            previous = position["trade_id"] if action == "reverse" else None
            loss_ticks, profit_ticks = signal.loss_ticks, signal.profit_ticks
        long_trade = side == "LONG"
        entry = event in ENTRY_EVENTS
        context = dict(
            source="mt5_engine",
            strategy="bytefx_ut_multi_asset",
            version="1.1.0",
            instance=stream.instance,
            event_id=trade_id + ":" + event,
            trade_id=trade_id,
            event=event,
            side=side,
            symbol=stream.tv_symbol,
            timeframe=stream.timeframe,
            signal_time_ms=close_ms,
            reference_price=signal.close,
            stop_ticks=loss_ticks,
            target_ticks=profit_ticks,
            tick_size=tick_size,
            stop_loss=None,
            take_profit=None,
            risk_percent=stream.risk_percent,
            previous_trade_id=previous,
            exit_owner="broker_fixed",
        )
        return AlertEnvelope.model_validate(
            dict(
                context=context,
                fill_price=signal.close,
                action="buy" if long_trade == entry else "sell",
                contracts=1.0,
                position=("long" if long_trade else "short") if entry else "flat",
                position_size=1.0 if entry else 0.0,
                previous_position=(("short" if long_trade else "long") if event == "reverse" else "flat")
                if entry
                else ("long" if long_trade else "short"),
                sent_at=datetime.fromtimestamp(now, timezone.utc),
            )
        )

    def emit(self, alert, rule, now, *, watch_only=False):
        sig = alert.context
        details = {
            "event_id": sig.event_id,
            "event": sig.event,
            "side": sig.side,
            "symbol": sig.symbol,
            "timeframe": sig.timeframe,
            "candle_close_utc": datetime.fromtimestamp(sig.signal_time_ms / 1000, timezone.utc).isoformat(),
            "reference_price": sig.reference_price,
            "stop_ticks": sig.stop_ticks,
            "target_ticks": sig.target_ticks,
        }
        if self.mode != "trade" or watch_only:
            self.db.audit("engine_signal_watch_only", details, now)
            log.info("engine_signal_watch_only", extra={"event_id": sig.event_id, "status": sig.event})
            return
        self.symbols.resolve(sig.symbol, require_enabled=sig.event in ENTRY_EVENTS)
        row, duplicate = self.db.enqueue(alert, rule.broker_symbol, now, self.settings.max_queue_size)
        if not duplicate:
            self.db.audit("engine_signal_queued", {**details, "event_pk": row["id"]}, now)
            log.info("engine_signal_queued", extra={"event_pk": row["id"], "event_id": sig.event_id})
