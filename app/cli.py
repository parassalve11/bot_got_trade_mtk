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
            if len(args.note.strip()) < 10:
                raise ValueError("Provide a meaningful audit note (at least 10 characters)")
            if args.command in ("resume", "acknowledge-hold") and db.operations(["UNKNOWN", "SENDING"]):
                raise ValueError("Uncertain operations must be reconciled before resuming")
            if args.command == "resume" and db.get_state("safety_hold"):
                raise ValueError("Resolve the cause, then acknowledge the safety hold first")
            if args.command == "acknowledge-hold":
                beat = db.get_state("worker", {})
                if time.time() - beat.get("at", 0) > settings.worker_health_seconds or not beat.get(
                    "reconciled"
                ):
                    raise ValueError("A fresh clean worker reconciliation is required")
                db.set_state("safety_hold", None)
            else:
                db.set_state("operator_pause", args.command == "pause")
            db.audit("operator_" + args.command, {"note": args.note})
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
