import logging
import threading
import time

from app.config import get_settings
from app.database import Database
from app.logging_config import configure_logging
from app.trading.errors import Reject, Retryable, SafetyError, Uncertain
from app.trading.executor import Executor
from app.trading.lock import WorkerLock
from app.trading.mt5_client import MT5Client
from app.trading.reconciliation import Reconciler
from app.trading.symbol_mapper import SymbolMapper

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings, db, broker, symbols, *, clock=time.time):
        self.settings, self.db, self.broker, self.clock = settings, db, broker, clock
        self.executor = Executor(settings, db, broker, symbols, clock=clock)
        self.reconciler = Reconciler(self.executor)
        self.reconciled = False
        self.last_equity_record = 0.0
        self.last_history = 0.0
        self.engine = None
        if settings.engine_mode != "off":
            from app.signals.runner import SignalEngine

            self.engine = SignalEngine(settings, db, broker, symbols)

    def heartbeat(self, connected, ready, reason=None):
        self.db.set_state(
            "worker",
            {
                "at": self.clock(),
                "connected": connected,
                "ready": ready,
                "reconciled": self.reconciled,
                "reason": reason,
                "mode": self.settings.trading_mode,
                "engine": self.settings.engine_mode,
                "account": "***" + str(self.settings.mt5_login)[-3:],
            },
        )

    def maintain(self):
        self.reconciled = False
        if self.settings.trading_mode == "DISABLED":
            self.heartbeat(False, False, "trading_mode_disabled")
            return
        try:
            self.broker.connect()
            account = self.executor.risk.account_guard()
            daily = self.executor.risk.daily(account, self.clock())
            clean = self.reconciler.run(self.clock())
            self.reconciled = clean
            self.process_close_requests()
            self.publish_snapshot(account)
            ready = bool(
                clean
                and account.trade_allowed
                and self.settings.trading_enabled
                and not daily["paused"]
                and not self.db.get_state("operator_pause", False)
                and self.db.get_state("bot_running", True)
                and not self.db.get_state("safety_hold")
            )
            self.heartbeat(True, ready, None if ready else "entries_paused_or_review_required")
        except Retryable as exc:
            self.heartbeat(False, False, str(exc))
        except (SafetyError, Uncertain, Reject) as exc:
            self.executor.hold(str(exc), self.clock())
            self.heartbeat(True, False, str(exc))

    def process_close_requests(self):
        """Dashboard close requests. Executed here so every MT5 call stays in the worker."""
        for request in self.db.pending_close_requests():
            now = self.clock()
            record = self.db.position(request["instance"], request["trade_id"])
            if record is None or record["status"] != "OPEN":
                self.db.finish_close_request(request["id"], "NOT_OPEN", now)
                continue
            details = {"instance": record["instance"], "trade_id": record["trade_id"], "by": request["requested_by"]}
            try:
                self.executor.close(self.db.event(record["event_pk"]), record, now, kind="MANUAL_CLOSE")
            except Retryable as exc:
                if now - request["requested_at"] > 120:
                    self.db.finish_close_request(request["id"], "FAILED", now, str(exc))
                continue
            except (Reject, Uncertain, SafetyError) as exc:
                self.executor.hold(str(exc), now)
                self.db.finish_close_request(request["id"], "FAILED", now, str(exc))
                self.db.audit("operator_close_failed", {**details, "reason": str(exc)}, now)
                continue
            self.db.finish_close_request(request["id"], "CLOSED", now)
            self.db.audit("operator_close_executed", details, now)

    def publish_snapshot(self, account):
        """Account/position snapshot for the dashboard; the API never calls MT5 itself."""
        now = self.clock()
        try:
            positions = self.broker.positions()
        except Retryable:
            return
        self.db.set_state("account_snapshot", {
            "at": now,
            "currency": account.currency,
            "balance": account.balance,
            "equity": account.equity,
            "margin_free": account.margin_free,
            "floating": account.equity - account.balance if account.balance else 0.0,
            "positions": [
                {"ticket": p.ticket, "identifier": p.identifier, "symbol": p.symbol, "side": p.side,
                 "volume": p.volume, "price_open": p.price_open, "sl": p.sl, "tp": p.tp, "profit": p.profit,
                 "magic": p.magic, "bot": p.magic == self.settings.magic_number}
                for p in positions
            ],
        })
        if now - self.last_equity_record >= 300 and account.balance:
            self.db.record_equity(account.balance, account.equity, now)
            self.last_equity_record = now
        if now - self.last_history >= 60:
            try:
                deals = self.broker.deals(now - 90 * 86400)
            except Retryable:
                return
            closed = {}
            for d in deals:
                if d.get("magic") != self.settings.magic_number:
                    continue
                item = closed.setdefault(str(d["position_id"]), {"profit": 0.0, "closed_at": None, "close_price": None})
                item["profit"] += d.get("profit", 0.0) + d.get("commission", 0.0) + d.get("swap", 0.0) + d.get("fee", 0.0)
                if d.get("entry") in (1, 3):
                    item["closed_at"] = d.get("time_msc", d["time"] * 1000) / 1000
                    item["close_price"] = d.get("price")
            self.db.set_state("deal_history", closed)
            self.last_history = now

    def process_one(self):
        row = self.db.claim(self.clock())
        if not row:
            return False
        try:
            if (
                row["event_type"] in ("entry", "reverse")
                and self.settings.trading_mode != "DISABLED"
                and not self.reconciled
            ):
                raise Retryable("reconciliation_not_ready")
            status, reason = self.executor.handle(row, self.clock())
            self.db.finish(row["id"], status, reason, now=self.clock())
        except Reject as exc:
            self.db.finish(row["id"], "REJECTED", str(exc), now=self.clock())
        except Retryable as exc:
            sent = any(
                op["event_pk"] == row["id"] and op["status"] in ("CONFIRMED", "UNKNOWN", "SENDING")
                for op in self.db.operations()
            )
            if row["attempts"] > self.settings.max_retries:
                self.db.finish(row["id"], "REVIEW" if sent else "FAILED", str(exc), now=self.clock())
                if sent:
                    self.executor.hold("post_send_recovery_exhausted", self.clock())
            else:
                delay = min(60, self.settings.retry_base_seconds * 2 ** (row["attempts"] - 1))
                self.db.finish(row["id"], "RETRY", str(exc), retry_at=self.clock() + delay, now=self.clock())
        except Uncertain as exc:
            # UNKNOWN operation itself blocks entries until broker evidence resolves it.
            self.db.finish(row["id"], "REVIEW", str(exc), now=self.clock())
            if not self.db.operations(["UNKNOWN", "SENDING"]):
                self.executor.hold(str(exc), self.clock())
        except SafetyError as exc:
            self.executor.hold(str(exc), self.clock())
            self.db.finish(row["id"], "REVIEW", str(exc), now=self.clock())
        except Exception:
            # A DB failure after order_send leaves SENDING in the journal. Never resend.
            log.exception("unexpected_worker_failure", extra={"event_pk": row["id"]})
            self.executor.hold("unexpected_worker_failure", self.clock())
            self.db.finish(row["id"], "REVIEW", "unexpected_worker_failure", now=self.clock())
        final = self.db.event(row["id"])
        log.info(
            "event_processed",
            extra={"event_pk": row["id"], "status": final["status"], "reason": final["error"]},
        )
        return True

    def tick(self):
        self.maintain()
        # Only generate signals from a connected, reconciled terminal.
        if self.engine and self.reconciled and self.db.get_state("bot_running", True):
            self.engine.poll(self.clock())
        return self.process_one()


def run_worker(settings=None):
    settings = settings or get_settings()
    configure_logging(settings, "worker")
    db = Database(settings.database_path)
    db.initialize()
    broker = MT5Client(settings)
    worker = Worker(settings, db, broker, SymbolMapper(settings.symbols_path))
    stop = threading.Event()
    with WorkerLock(db.path.with_suffix(".worker.lock")):
        db.recover_queue()
        if settings.stop_on_pc_restart:
            from app.control import stop_after_long_offline

            stop_after_long_offline(db, time.time())
        try:
            while not stop.is_set():
                try:
                    worker.tick()
                except Exception:
                    log.exception("worker_cycle_failed")
                    # No further sends until restart/operator inspection after journal failures.
                    raise
                stop.wait(settings.worker_poll_seconds)
        except KeyboardInterrupt:
            pass
        finally:
            broker.shutdown()
            worker.heartbeat(False, False, "worker_stopped")


if __name__ == "__main__":
    run_worker()
