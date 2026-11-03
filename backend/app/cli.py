import argparse
import json
import secrets
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.database import Database
from app.schemas import AlertEnvelope
from app.trading.errors import Reject, Retryable, SafetyError
from app.trading.executor import Executor
from app.trading.lock import WorkerLock
from app.trading.mt5_client import MT5Client
from app.trading.symbol_mapper import SymbolMapper


def init_config(directory=Path(".")):
    template = (directory / ".env.example").read_text("utf-8")
    template = template.replace("REPLACE_WITH_RANDOM_TOKEN_AT_LEAST_32_CHARACTERS", secrets.token_urlsafe(40))
    template = template.replace(
        "REPLACE_WITH_DIFFERENT_RANDOM_TOKEN_AT_LEAST_32_CHARACTERS", secrets.token_urlsafe(40)
    )
    with (directory / ".env").open("x", encoding="utf-8") as output:
        output.write(template)
    print("Created .env with distinct secrets. Trading remains DISABLED. Secrets are not printed.")


def mt5_preflight(settings, db, broker, mapper):
    risk = Executor(settings, db, broker, mapper).risk
    account = risk.account_guard()
    blockers = [] if account.trade_allowed else ["terminal_or_account_trading_disabled"]
    symbols = []
    for name, rule in mapper.rules.items():
        if not rule.enabled:
            continue
        item = {"tv_symbol": name, "broker_symbol": rule.broker_symbol}
        try:
            symbol = broker.symbol(rule.broker_symbol)
            item.update(volume_min=symbol.volume_min, volume_step=symbol.volume_step)
            now = time.time()
            tick = broker.tick(rule.broker_symbol)
            item["tick_age_seconds"] = round(now - tick.time, 3)
            # Hint only (valid while the market is open and ticking): the broker clock offset
            # that would make this quote current. Compare with MT5_SERVER_UTC_OFFSET_SECONDS,
            # especially after daylight-saving changes.
            raw_lead = tick.time + settings.mt5_server_utc_offset_seconds - now
            item["measured_server_offset_hint_seconds"] = int(round(raw_lead / 1800) * 1800)
            risk.tick(rule.broker_symbol, now)
            spread = (tick.ask - tick.bid) / symbol.point
            item["spread_points"] = round(spread, 3)
            if spread > rule.max_spread_points + 1e-8:
                raise Reject("spread_limit")
            item["quote_ready"] = True
        except (Reject, Retryable) as exc:
            item.update(quote_ready=False, reason=str(exc))
            blockers.append(name + ":" + str(exc))
        symbols.append(item)
    if not symbols:
        blockers.append("no_enabled_symbols")
    return {
        "connected": True,
        "account": "***" + str(account.login)[-3:],
        "trade_allowed": account.trade_allowed,
        "server_utc_offset_seconds": settings.mt5_server_utc_offset_seconds,
        "symbols": symbols,
        "preflight_passed": not blockers,
        "blockers": blockers,
    }


def simulate_history(bars, stream, tick_size, htf_bars=None):
    """Approximate Pine replay on closed MT5 candles: fills at next open, bracket SL/TP.

    Same signal maths as live trading. Fills/costs are simplified; for comparison only.
    """
    from app.signals.ut_engine import decide, htf_direction_at, htf_series, signal_series

    signals = signal_series(bars, stream, tick_size)
    series = htf_series(htf_bars, stream) if htf_bars else None
    trades, position = [], None
    for i, bar in enumerate(bars):
        if position and i >= position["fill_index"]:
            long = position["side"] == "LONG"
            hit_sl = bar["low"] <= position["sl"] if long else bar["high"] >= position["sl"]
            hit_tp = position["tp"] is not None and (
                bar["high"] >= position["tp"] if long else bar["low"] <= position["tp"]
            )
            if hit_sl or hit_tp:  # Both in one candle: assume the stop (conservative).
                position.update(exit_time=bar["time"], exit=position["sl"] if hit_sl else position["tp"],
                                reason="stop_loss" if hit_sl else "take_profit")
                trades.append(position)
                position = None
        signal = signals[i]
        trend = htf_direction_at(series, bar["time"] + stream.seconds) if series else None
        action = decide(signal, position["side"] if position else None, stream, trend)
        if not action or i + 1 >= len(bars):
            continue
        fill = bars[i + 1]["open"]
        if action in ("close", "reverse"):
            position.update(exit_time=bars[i + 1]["time"], exit=fill, reason="opposite_signal")
            trades.append(position)
            position = None
        if action in ("entry", "reverse"):
            sign = 1 if signal.side == "LONG" else -1
            position = dict(
                side=signal.side, signal_time=bar["time"] + stream.seconds, fill_index=i + 1,
                entry=fill, sl=fill - sign * signal.loss_ticks * tick_size,
                tp=None if signal.profit_ticks is None else fill + sign * signal.profit_ticks * tick_size,
            )
    for trade in trades:
        sign = 1 if trade["side"] == "LONG" else -1
        trade["result_ticks"] = round((trade["exit"] - trade["entry"]) * sign / tick_size)
    return signals, trades, position


def engine_scan(settings, broker, mapper, bars_count):
    from datetime import datetime, timezone

    from app.signals.ut_engine import load_streams

    def stamp(epoch):
        utc = datetime.fromtimestamp(epoch, timezone.utc)
        return utc.strftime("%Y-%m-%d %H:%M UTC") + " (" + utc.astimezone().strftime("%H:%M local") + ")"

    for stream in [s for s in load_streams(settings.engine_config_path) if s.enabled]:
        rule = mapper.resolve(stream.tv_symbol, require_enabled=False)
        symbol = broker.symbol(rule.broker_symbol)
        now = time.time()
        bars = [b for b in broker.rates(rule.broker_symbol, stream.timeframe, bars_count)
                if b["time"] + stream.seconds <= now]
        htf_bars = None
        if stream.htf_filter != "none":
            htf_bars = [b for b in broker.rates(rule.broker_symbol, stream.htf_filter, max(500, bars_count // 4 + 100))
                        if b["time"] + 14400 <= now]
        signals, trades, open_trade = simulate_history(bars, stream, symbol.tick_size, htf_bars)
        warmup = min(len(bars), max(200, stream.risk_atr_length * 10))
        print()
        print(f"=== {stream.tv_symbol} -> {rule.broker_symbol}, {stream.timeframe}m, instance '{stream.instance}' ===")
        print(f"Candles: {stamp(bars[0]['time'])} to {stamp(bars[-1]['time'] + stream.seconds)}")
        print()
        print("UT signals (candle close time = when TradingView would show the arrow):")
        for i, signal in enumerate(signals):
            if signal and i >= warmup:
                print(f"  {stamp(bars[i]['time'] + stream.seconds)}  {'BUY ' if signal.side == 'LONG' else 'SELL'}"
                      f"  close {signal.close:.{symbol.digits}f}  stop {signal.loss_ticks:.0f} ticks  target "
                      f"{'off' if signal.profit_ticks is None else f'{signal.profit_ticks:.0f} ticks'}")
        shown = [t for t in trades if t["fill_index"] >= warmup]
        print()
        print("Simulated trades (approximate; ignores spread/commission):")
        for t in shown:
            print(f"  {t['side']:5} in {stamp(bars[t['fill_index']]['time'])} @ {t['entry']:.5f}  "
                  f"out {stamp(t['exit_time'])} @ {t['exit']:.5f}  {t['reason']:15} {t['result_ticks']:+d} ticks")
        if open_trade:
            print(f"  {open_trade['side']:5} still open since {stamp(bars[open_trade['fill_index']]['time'])}")
        wins = sum(t["result_ticks"] > 0 for t in shown)
        if shown:
            print()
            print(f"Trades {len(shown)} | wins {wins} | losses {len(shown) - wins} | "
                  f"win rate {wins / len(shown):.0%} | net {sum(t['result_ticks'] for t in shown):+d} ticks")
        print("(First", warmup, "candles are indicator warm-up and are not listed.)")


def resolve_no_fill(settings, db, key, note):
    # Exclusive lock prevents a live worker from sending while an operator resolves a journal entry.
    with WorkerLock(db.path.with_suffix(".worker.lock")):
        operation = db.operation(key)
        if not operation or operation["status"] != "UNKNOWN" or operation["kind"] != "OPEN":
            raise ValueError("Only an UNKNOWN OPEN operation can be declared no-fill")
        broker = MT5Client(settings)
        executor = Executor(settings, db, broker, SymbolMapper(settings.symbols_path))
        try:
            broker.connect()
            executor.risk.account_guard()
            request = json.loads(operation["request_json"])
            if any(p.symbol == request["symbol"] for p in broker.positions()) or any(
                o["symbol"] == request["symbol"] for o in broker.orders()
            ):
                raise SafetyError(
                    "Symbol still has positions or working orders; do not discard the operation"
                )
            try:
                executor.opening_evidence(operation)
            except Retryable as exc:
                if str(exc) != "opening_deal_not_yet_identifiable":
                    raise
            else:
                raise SafetyError("Matching broker deals exist; let reconciliation recover the operation")
            now = time.time()
            db.operation_result(key, "REJECTED", {"operator_verified_no_fill": True}, now, "operator_no_fill")
            row = db.event(operation["event_pk"])
            sig = AlertEnvelope.model_validate_json(row["payload_json"]).context
            db.tombstone(sig, row["broker_symbol"], now, row["id"])
            db.finish(row["id"], "REJECTED", "operator_verified_no_fill", now=now)
            db.audit("operator_resolved_no_fill", {"operation": key, "note": note}, now)
        finally:
            broker.shutdown()


def parser():
    root = argparse.ArgumentParser(description="BYTEFX local administration (no public trading endpoints)")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init-config", help="Create .env once; never print secrets")
    check = commands.add_parser("check", help="Validate local config; optionally inspect MT5 read-only")
    check.add_argument("--mt5", action="store_true")
    api = commands.add_parser("api", help="Serve the API on loopback only")
    api.add_argument("--port", type=int, default=8000)
    commands.add_parser("worker", help="Run the sole MT5 worker")
    scan = commands.add_parser(
        "engine-scan", help="Read-only: list built-in engine signals on MT5 history for comparison"
    )
    scan.add_argument("--bars", type=int, default=2000)
    commands.add_parser("status", help="Read protected local operational state")
    for name in ("pause", "resume", "acknowledge-hold"):
        sub = commands.add_parser(name)
        sub.add_argument("--note", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("destination", type=Path)
    resolve = commands.add_parser(
        "resolve-no-fill", help="After broker inspection, abandon an uncertain OPEN without resending"
    )
    resolve.add_argument("operation_key")
    resolve.add_argument("--broker-checked", action="store_true", required=True)
    resolve.add_argument("--note", required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init-config":
            init_config()
            return 0
        settings = get_settings()
        if args.command == "api":
            import uvicorn

            uvicorn.run(
                "app.main:create_app",
                factory=True,
                host="127.0.0.1",
                port=args.port,
                access_log=False,
                proxy_headers=False,
                workers=1,
            )
            return 0
        if args.command == "worker":
            from app.trading.worker import run_worker

            run_worker(settings)
            return 0
        if args.command == "engine-scan":
            # Read-only MT5 queries; no worker lock, so it can run beside a live worker.
            broker = MT5Client(settings)
            try:
                broker.connect()
                engine_scan(settings, broker, SymbolMapper(settings.symbols_path), max(300, args.bars))
            finally:
                broker.shutdown()
            return 0
        db = Database(settings.database_path)
        db.initialize()
        if args.command == "check":
            mapper = SymbolMapper(settings.symbols_path)
            print(
                json.dumps(
                    {
                        "configuration": "valid",
                        "trading_mode": settings.trading_mode,
                        "trading_enabled": settings.trading_enabled,
                        "enabled_symbols": [name for name, rule in mapper.rules.items() if rule.enabled],
                    },
                    indent=2,
                )
            )
            if args.mt5:
                with WorkerLock(db.path.with_suffix(".worker.lock")):
                    broker = MT5Client(settings)
                    try:
                        broker.connect()
                        report = mt5_preflight(settings, db, broker, mapper)
                        print(json.dumps(report, indent=2))
                        if not report["preflight_passed"]:
                            return 1
                    finally:
                        broker.shutdown()
        elif args.command == "status":
            print(
                json.dumps(
                    {
                        **db.status(),
                        "worker": db.get_state("worker", {}),
                        "operator_pause": db.get_state("operator_pause", False),
                        "safety_hold": db.get_state("safety_hold"),
                    },
                    indent=2,
                )
            )
        elif args.command == "backup":
            db.backup(args.destination)
            print("Consistent SQLite backup created.")
        elif args.command == "resolve-no-fill":
            if len(args.note.strip()) < 10:
                raise ValueError("Provide a meaningful broker-inspection note (at least 10 characters)")
            resolve_no_fill(settings, db, args.operation_key, args.note)
            print("Operation abandoned, original event rejected, and audit note saved. No order resent.")
        else:
            from app import control

            if args.command == "acknowledge-hold":
                control.acknowledge_hold(db, settings, args.note)
            else:
                control.set_paused(db, args.command == "pause", args.note)
            print("Control state saved. Broker protective orders remain in place.")
        return 0
    except Exception as exc:
        # Configuration errors may contain secret field input values: never print their repr.
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            fields = ", ".join(".".join(map(str, err["loc"])) or "configuration" for err in exc.errors())
            print("Invalid settings: " + fields + ". Check .env and .env.example.", file=sys.stderr)
        elif isinstance(exc, (ValueError, RuntimeError, SafetyError, Retryable, FileExistsError)):
            print(str(exc), file=sys.stderr)
        else:
            print(
                "Command failed: " + type(exc).__name__ + ". Check configuration and logs.", file=sys.stderr
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
