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
            ready = bool(
                clean
                and account.trade_allowed
                and self.settings.trading_enabled
                and not daily["paused"]
                and not self.db.get_state("operator_pause", False)
                and not self.db.get_state("safety_hold")
            )
            self.heartbeat(True, ready, None if ready else "entries_paused_or_review_required")
        except Retryable as exc:
            self.heartbeat(False, False, str(exc))
        except (SafetyError, Uncertain, Reject) as exc:
            self.executor.hold(str(exc), self.clock())
            self.heartbeat(True, False, str(exc))

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
