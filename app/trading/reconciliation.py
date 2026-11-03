import json

from app.trading.broker import DONE, DONE_PARTIAL, SLTP
from app.trading.errors import Retryable, SafetyError, Uncertain


class Reconciler:
    def __init__(self, executor):
        self.executor = executor
        self.db, self.broker, self.settings = executor.db, executor.broker, executor.settings

    def resolve_uncertain(self, operation, now):
        request = json.loads(operation["request_json"])
        kind = operation["kind"]
        if kind == "OPEN":
            identifier, volume, price, deals = self.executor.opening_evidence(operation)
            result = dict(
                retcode=DONE if abs(volume - request["volume"]) < 1e-9 else DONE_PARTIAL,
                order=deals[0]["order"],
                deal=deals[0]["ticket"],
                volume=volume,
                price=price,
                recovered_identifier=identifier,
            )
        elif request["action"] == SLTP:
            matching = [p for p in self.broker.positions() if p.identifier == request["_meta"]["identifier"]]
            if matching:
                pos = matching[0]
                symbol = self.broker.symbol(pos.symbol)
                if pos.magic != self.settings.magic_number or pos.symbol != request["symbol"]:
                    raise SafetyError("uncertain_protection_ownership_changed")
                if (
                    abs(pos.sl - request["sl"]) >= symbol.tick_size * 0.5
                    or abs(pos.tp - request["tp"]) >= symbol.tick_size * 0.5
                ):
                    return False
                record = next(
                    (r for r in self.db.open_positions() if r["identifier"] == pos.identifier), None
                )
                if record is None:
                    raise SafetyError("uncertain_protection_position_not_journaled")
                self.executor.positions.assert_owned(record, pos)
                self.executor.positions.refresh(record, pos)
            result = {"retcode": DONE, "reconciled": True}
        else:
            identifier = request["_meta"]["identifier"]
            deals = [
                d
                for d in self.broker.position_deals(identifier)
                if d["magic"] == self.settings.magic_number
                and d["entry"] in (1, 3)
                and d["symbol"] == request["symbol"]
                and d["comment"] == operation["comment"]
            ]
            remaining = [p for p in self.broker.positions() if p.identifier == identifier]
            if not deals:
                # A broker SL can race a close. Absence + full closing history proves flat.
                history = self.broker.position_deals(identifier)
                closed_volume = sum(
                    d["volume"] for d in history if d["entry"] in (1, 3) and d["type"] in (0, 1)
                )
                if remaining or closed_volume < request["volume"] - 1e-8:
                    return False
                result = {"retcode": DONE, "reconciled": True, "already_closed": True}
            else:
                volume = sum(d["volume"] for d in deals)
                result = dict(
                    retcode=DONE if not remaining else DONE_PARTIAL,
                    order=deals[0]["order"],
                    deal=deals[0]["ticket"],
                    volume=volume,
                    price=sum(d["price"] * d["volume"] for d in deals) / volume,
                )
        self.db.operation_result(operation["op_key"], "CONFIRMED", result, now)
        self.db.audit("operation_reconciled", {"operation": operation["op_key"]}, now)
        row = self.db.event(operation["event_pk"])
        if row["status"] == "REVIEW":
            self.db.finish(row["id"], "QUEUED", "broker_evidence_found", now=now)
        return True

    def run(self, now):
        self.executor.risk.account_guard()
        unresolved = False
        for operation in self.db.operations(["UNKNOWN"]):
            try:
                if not self.resolve_uncertain(operation, now):
                    unresolved = True
            except (Retryable, Uncertain):
                unresolved = True

        # Recover confirmed OPEN responses that were committed before the position record.
        for operation in self.db.operations(["CONFIRMED"]):
            if operation["kind"] != "OPEN":
                continue
            request = json.loads(operation["request_json"])
            meta = request["_meta"]
            if self.db.position(meta["instance"], operation["trade_id"]) is None:
                row = self.db.event(operation["event_pk"])
                try:
                    self.executor.finish_open(row, operation, now)
                    if row["status"] == "REVIEW":
                        self.db.finish(row["id"], "QUEUED", "known_open_recovered", now=now)
                except (Retryable, Uncertain):
                    unresolved = True

        values = self.broker.positions()
        records = self.db.open_positions()
        known = {r["identifier"] for r in records}
        if any(p.magic == self.settings.magic_number and p.identifier not in known for p in values):
            self.executor.hold("unrecognized_bot_position", now)
            unresolved = True
        if any(o.get("magic") == self.settings.magic_number for o in self.broker.orders()):
            self.executor.hold("unexpected_bot_working_order", now)
            unresolved = True
        for record in records:
            pos = self.executor.positions.locate(record, values)
            if pos is None:
                self.db.close_position(record["instance"], record["trade_id"], now)
                self.db.audit(
                    "broker_position_closed",
                    {"trade_id": record["trade_id"], "identifier": record["identifier"]},
                    now,
                )
                continue
            try:
                self.executor.positions.assert_owned(record, pos)
                symbol = self.broker.symbol(pos.symbol)
                protection = self.db.operation(f"{record['event_pk']}:PROTECT")
                if protection and protection["status"] == "CONFIRMED":
                    planned = json.loads(protection["request_json"])
                    if (
                        abs(pos.sl - planned["sl"]) < symbol.tick_size * 0.5
                        and abs(pos.tp - planned["tp"]) < symbol.tick_size * 0.5
                    ):
                        record = self.executor.positions.refresh(record, pos)
                if pos.sl <= 0 or (record["target_distance"] is not None and pos.tp <= 0):
                    self.executor.hold("managed_position_missing_protection", now)
                    self.executor.protect(self.db.event(record["event_pk"]), record, now)
                elif (
                    abs(pos.sl - record["sl"]) >= symbol.tick_size * 0.5
                    or abs(pos.tp - record["tp"]) >= symbol.tick_size * 0.5
                ):
                    # Never silently overwrite a manual edit or adopt its risk.
                    self.executor.hold("protective_levels_changed_outside_executor", now)
                    unresolved = True
                else:
                    self.executor.positions.refresh(record, pos)
            except (SafetyError, Uncertain) as exc:
                self.executor.hold(str(exc), now)
                unresolved = True
        return not unresolved
