import json
import logging
import math
import time

from app.api.webhook import check_freshness
from app.schemas import AUDIT_EVENTS, CLOSE_EVENTS, AlertEnvelope
from app.trading.broker import BUY, DEAL, DONE, DONE_PARTIAL, GTC, SELL, SLTP
from app.trading.errors import Reject, Retryable, SafetyError, Uncertain
from app.trading.position_manager import PositionManager
from app.trading.risk_manager import RiskManager, filling_policy, protective_levels, validate_stops

log = logging.getLogger(__name__)
# Only explicit non-execution responses are considered definitive failures.
DEFINITIVE_REJECTIONS = {
    10004,
    10006,
    10007,
    10013,
    10014,
    10015,
    10016,
    10017,
    10018,
    10019,
    10020,
    10021,
    10022,
    10024,
    10026,
    10027,
    10030,
    10032,
    10033,
    10034,
    10035,
    10036,
    10038,
    10039,
    10040,
    10041,
    10042,
    10043,
    10044,
    10045,
    10046,
}


class Executor:
    def __init__(self, settings, db, broker, symbols, *, clock=time.time):
        self.settings, self.db, self.broker, self.symbols = settings, db, broker, symbols
        self.risk = RiskManager(settings, db, broker)
        self.positions = PositionManager(settings, db, broker)
        self.clock = clock

    def hold(self, reason, now):
        value = {"reason": reason, "at": now}
        if (self.db.get_state("safety_hold") or {}).get("reason") != reason:
            self.db.set_state("safety_hold", value)
            self.db.audit("safety_hold", value, now)

    def send(self, row, kind, trade_id, request, now):
        now = self.clock()
        key = f"{row['id']}:{kind}"
        operation = self.db.operation(key)
        if operation:
            if operation["status"] == "CONFIRMED":
                return operation, json.loads(operation["result_json"])
            if operation["status"] in ("SENDING", "UNKNOWN"):
                raise Uncertain("operation_requires_reconciliation")
            if operation["status"] == "REJECTED":
                raise Reject("operation_already_rejected")
            operation = self.db.refresh_prepared(key, request, now)
        else:
            operation = self.db.prepare_operation(row["id"], trade_id, kind, request, now)
        actual = json.loads(operation["request_json"])
        actual.pop("_meta", None)
        account = self.risk.account_guard()  # Recheck identity immediately before every send.
        if not account.trade_allowed:
            raise Retryable("terminal_or_account_trading_disabled")
        if actual["action"] == DEAL and not actual.get("position"):
            self.risk.entry_guard(account, now)
            if any(p.symbol == actual["symbol"] for p in self.broker.positions()) or any(
                o["symbol"] == actual["symbol"] for o in self.broker.orders()
            ):
                raise Reject("symbol_changed_before_send")
        if actual.get("position"):
            match = next((p for p in self.broker.positions() if p.ticket == actual["position"]), None)
            if match is None:
                raise Retryable("position_changed_before_send")
            record = next((p for p in self.db.open_positions() if p["identifier"] == match.identifier), None)
            if record is None:
                raise SafetyError("position_not_in_journal")
            self.positions.assert_owned(record, match)
        checked = self.broker.check(actual)
        if checked["retcode"] != 0:
            self.db.operation_result(key, "REJECTED", checked, now, "order_check_rejected")
            raise Reject(f"order_check_rejected_{checked['retcode']}")
        self.db.mark_sending(key, now)  # Durable commit BEFORE the side effect.
        try:
            result = self.broker.send(actual)
        except Exception:
            self.db.operation_result(key, "UNKNOWN", None, now, "exception_during_order_send")
            raise Uncertain("exception_during_order_send") from None
        if result is None or result.get("retcode") not in (
            {DONE, DONE_PARTIAL, 10025} | DEFINITIVE_REJECTIONS
        ):
            self.db.operation_result(key, "UNKNOWN", result, now, "broker_result_uncertain")
            raise Uncertain("broker_result_uncertain")
        if result["retcode"] in DEFINITIVE_REJECTIONS or (
            result["retcode"] == 10025 and actual["action"] != SLTP
        ):
            self.db.operation_result(key, "REJECTED", result, now, "broker_rejected")
            raise Reject(f"broker_rejected_{result['retcode']}")
        self.db.operation_result(key, "CONFIRMED", result, now)
        log.info("broker_operation_confirmed", extra={"event_pk": row["id"], "operation": key})
        return self.db.operation(key), result

    def opening_evidence(self, operation):
        request = json.loads(operation["request_json"])
        result = json.loads(operation["result_json"]) if operation["result_json"] else {}
        all_deals = self.broker.deals(operation["created_at"] - 60)
        deals = [
            d
            for d in all_deals
            if d["magic"] == self.settings.magic_number
            and d["symbol"] == request["symbol"]
            and d["entry"] == 0
            and d["type"] == request["type"]
            and (
                d.get("comment") == operation["comment"]
                or (result.get("order") and d["order"] == result["order"])
                or (result.get("deal") and d["ticket"] == result["deal"])
            )
        ]
        identifiers = {d["position_id"] for d in deals}
        if len(identifiers) > 1:
            raise SafetyError("multiple_positions_for_one_open_operation")
        if not deals:
            raise Retryable("opening_deal_not_yet_identifiable")
        volume = sum(d["volume"] for d in deals)
        symbol = self.broker.symbol(request["symbol"])
        if volume <= 0 or volume > request["volume"] + symbol.volume_step * 1e-6:
            raise SafetyError("unexpected_executed_volume")
        if any(
            o.get("comment") == operation["comment"] or o.get("ticket") == result.get("order")
            for o in self.broker.orders()
        ):
            raise Uncertain("open_operation_has_working_remainder")
        return next(iter(identifiers)), volume, sum(d["price"] * d["volume"] for d in deals) / volume, deals

    def finish_open(self, row, operation, now):
        request = json.loads(operation["request_json"])
        meta = request["_meta"]
        identifier, volume, price, deals = self.opening_evidence(operation)
        live = [p for p in self.broker.positions() if p.identifier == identifier]
        if len(live) > 1:
            raise SafetyError("ambiguous_open_position")
        pos = live[0] if live else None
        if pos is None:
            history = self.broker.position_deals(identifier)
            closed_volume = sum(d["volume"] for d in history if d["entry"] in (1, 3) and d["type"] in (0, 1))
            if closed_volume < volume - 1e-8:
                raise Retryable("filled_position_not_yet_visible")
        record = dict(
            instance=meta["instance"],
            trade_id=operation["trade_id"],
            tv_symbol=meta["tv_symbol"],
            symbol=request["symbol"],
            side=meta["side"],
            ticket=pos.ticket if pos else None,
            identifier=identifier,
            volume=volume,
            entry_price=price,
            sl=pos.sl if pos else request["sl"],
            tp=pos.tp if pos else request["tp"],
            stop_distance=meta["stop_distance"],
            target_distance=meta["target_distance"],
            risk_budget=meta["risk_budget"],
            status="OPEN" if pos else "CLOSED",
            opened_at=min(d.get("time_msc", d["time"] * 1000) / 1000 for d in deals),
            closed_at=None if pos else now,
            event_pk=row["id"],
        )
        if pos:
            self.positions.assert_owned(record, pos)
        self.db.save_position(record)
        if pos:
            symbol = self.broker.symbol(pos.symbol)
            # Strict post-fill slippage check also covers brokers that ignore deviation.
            if (
                abs(price - request["price"])
                > self.settings.max_deviation_points * symbol.point + symbol.tick_size * 0.5
            ):
                self.emergency_close(row, record, "post_fill_slippage_limit", now)
                return
            self.protect(row, record, now)

    def protect(self, row, record, now):
        pos = self.positions.locate(record)
        if pos is None:
            self.db.close_position(record["instance"], record["trade_id"], now)
            return
        self.positions.assert_owned(record, pos)
        symbol = self.broker.symbol(pos.symbol)
        sl, tp = protective_levels(
            pos.side, pos.price_open, record["stop_distance"], record["target_distance"], symbol
        )
        risk = -self.broker.profit(pos.side, pos.symbol, pos.volume, pos.price_open, sl)
        if not math.isfinite(risk) or risk > record["risk_budget"] + 1e-6:
            self.emergency_close(row, record, "post_fill_risk_limit", now)
            return
        same = abs(pos.sl - sl) < symbol.tick_size * 0.5 and abs(pos.tp - tp) < symbol.tick_size * 0.5
        if same:
            self.positions.refresh(record, pos)
            return
        previous_protection = self.db.operation(f"{row['id']}:PROTECT")
        if previous_protection and previous_protection["status"] == "CONFIRMED":
            self.emergency_close(row, record, "protection_changed_after_confirmation", now)
            return
        try:
            tick = self.risk.tick(pos.symbol, now)
            validate_stops(pos.side, sl, tp, tick, symbol, modifying=True)
            request = dict(
                action=SLTP,
                position=pos.ticket,
                symbol=pos.symbol,
                sl=sl,
                tp=tp,
                magic=self.settings.magic_number,
                _meta={"identifier": pos.identifier, "side": pos.side},
            )
            self.send(row, "PROTECT", record["trade_id"], request, now)
        except Reject:
            self.emergency_close(row, record, "cannot_attach_fill_based_protection", now)
            return
        updated = self.positions.locate(record)
        if updated is None:
            self.db.close_position(record["instance"], record["trade_id"], now)
            return
        if abs(updated.sl - sl) >= symbol.tick_size * 0.5 or abs(updated.tp - tp) >= symbol.tick_size * 0.5:
            raise Uncertain("protective_modification_not_confirmed")
        self.positions.refresh(record, updated)

    def close(self, row, record, now, *, kind="CLOSE"):
        pos = self.positions.locate(record)
        if pos is None:
            self.db.close_position(record["instance"], record["trade_id"], now)
            return
        self.positions.assert_owned(record, pos)
        symbol = self.broker.symbol(pos.symbol)
        tick = self.risk.tick(pos.symbol, now)
        request = dict(
            action=DEAL,
            position=pos.ticket,
            symbol=pos.symbol,
            volume=pos.volume,
            type=SELL if pos.side == "LONG" else BUY,
            price=tick.bid if pos.side == "LONG" else tick.ask,
            deviation=self.settings.max_deviation_points,
            magic=self.settings.magic_number,
            type_time=GTC,
            type_filling=filling_policy(symbol),
            _meta={"identifier": pos.identifier, "side": pos.side},
        )
        _, result = self.send(row, kind, record["trade_id"], request, now)
        remaining = self.positions.locate(record)
        if remaining is not None:
            if result["retcode"] == DONE_PARTIAL or remaining.volume < pos.volume:
                raise SafetyError("partial_close_requires_review_no_reversal_sent")
            raise Retryable("close_not_yet_reflected_in_positions")
        self.db.close_position(record["instance"], record["trade_id"], now)

    def emergency_close(self, row, record, reason, now):
        self.hold(reason, now)
        self.close(row, record, now, kind="EMERGENCY_CLOSE")
        raise SafetyError(reason + "_position_closed")

    def handle(self, row, now):
        alert = AlertEnvelope.model_validate_json(row["payload_json"])
        sig = alert.context
        if sig.event in AUDIT_EVENTS:
            return "LOGGED", "broker_owns_protective_exits"
        if self.settings.trading_mode == "DISABLED":
            raise Reject("trading_mode_disabled")
        # A known fill is recovered even after an entry signal has expired. No new order.
        completed_open = self.db.operation(f"{row['id']}:OPEN")
        if completed_open and completed_open["status"] == "CONFIRMED":
            self.broker.connect()
            self.risk.account_guard()
            self.finish_open(row, completed_open, now)
            return "EXECUTED", "recovered_open"
        check_freshness(alert, self.settings, now)
        self.broker.connect()
        account = self.risk.account_guard()
        self.risk.daily(account, now)
        rule = self.symbols.resolve(sig.symbol, require_enabled=sig.event not in CLOSE_EVENTS)
        if rule.broker_symbol != row["broker_symbol"]:
            raise Reject("symbol_mapping_changed_after_intake")
        if sig.event in CLOSE_EVENTS:
            record = self.db.position(sig.instance, sig.trade_id)
            if record is None:
                self.db.tombstone(sig, rule.broker_symbol, now, row["id"])
                return "IGNORED", "unknown_trade_close_tombstoned"
            if record["tv_symbol"] != sig.symbol or record["side"] != sig.side:
                raise Reject("close_trade_identity_mismatch")
            if record["status"] == "CLOSED":
                return "IGNORED", "trade_already_closed"
            self.close(row, record, now)
            return "EXECUTED", "position_closed"
        if sig.exit_owner != "broker_fixed":
            raise Reject("unsupported_pine_exit_owner")
        self.db.watermark(sig.instance, sig.symbol, sig.signal_time_ms)
        existing = self.db.position(sig.instance, sig.trade_id)
        if existing is not None:
            return "IGNORED", "trade_already_seen"
        previous = None
        if sig.event == "reverse":
            previous = self.db.position(sig.instance, sig.previous_trade_id)
            if (
                previous is None
                or previous["symbol"] != rule.broker_symbol
                or previous["tv_symbol"] != sig.symbol
                or previous["side"] == sig.side
            ):
                raise Reject("reversal_previous_trade_mismatch")
        live_records = [p for p in self.db.open_positions() if p["symbol"] == rule.broker_symbol]
        if sig.event == "entry" and live_records:
            current = live_records[0]
            if len(live_records) == 1 and current["instance"] == sig.instance and current["side"] == sig.side:
                self.db.tombstone(sig, rule.broker_symbol, now, row["id"])
                return "IGNORED", "same_side_position_no_pyramiding"
            raise Reject("existing_position_conflicts_with_flat_entry")
        replacing = previous["identifier"] if previous and previous["status"] == "OPEN" else None
        # Preflight first; a rejected reversal should not unnecessarily close a good position.
        plan = self.risk.plan(sig, rule, now, replacing_identifier=replacing)
        if previous and previous["status"] == "OPEN":
            self.close(row, previous, now)
            # Confirmed flat, then recompute from new quote/equity/free margin.
            plan = self.risk.plan(sig, rule, now)
        request = {
            **plan.request,
            "_meta": {
                "instance": sig.instance,
                "tv_symbol": sig.symbol,
                "side": sig.side,
                "stop_distance": plan.stop_distance,
                "target_distance": plan.target_distance,
                "risk_budget": plan.risk_budget,
            },
        }
        operation, _ = self.send(row, "OPEN", sig.trade_id, request, now)
        self.finish_open(row, operation, now)
        return "EXECUTED", "position_opened"
