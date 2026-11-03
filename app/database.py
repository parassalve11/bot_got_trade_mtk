"""SQLite journal and queue. Transactions never span an MT5/network call."""

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.schemas import AlertEnvelope
from app.trading.errors import Reject, SafetyError

SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_events (
 id INTEGER PRIMARY KEY, instance TEXT NOT NULL, event_id TEXT NOT NULL,
 trade_id TEXT NOT NULL, event_type TEXT NOT NULL, symbol TEXT NOT NULL,
 broker_symbol TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
 received_at REAL NOT NULL, sent_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'QUEUED',
 attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
 error TEXT, processed_at REAL, UNIQUE(instance,event_id)
);
CREATE INDEX IF NOT EXISTS event_queue ON webhook_events(status,next_attempt,id);
CREATE TABLE IF NOT EXISTS operations (
 op_key TEXT PRIMARY KEY, event_pk INTEGER NOT NULL REFERENCES webhook_events(id),
 trade_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
 request_json TEXT NOT NULL, result_json TEXT, comment TEXT NOT NULL UNIQUE,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS positions (
 instance TEXT NOT NULL, trade_id TEXT NOT NULL, tv_symbol TEXT NOT NULL,
 symbol TEXT NOT NULL, side TEXT NOT NULL, ticket INTEGER, identifier INTEGER,
 volume REAL NOT NULL DEFAULT 0, entry_price REAL NOT NULL DEFAULT 0,
 sl REAL NOT NULL DEFAULT 0, tp REAL NOT NULL DEFAULT 0,
 stop_distance REAL NOT NULL DEFAULT 0, target_distance REAL,
 risk_budget REAL NOT NULL DEFAULT 0, status TEXT NOT NULL,
 opened_at REAL, closed_at REAL, event_pk INTEGER REFERENCES webhook_events(id),
 PRIMARY KEY(instance,trade_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS live_ticket ON positions(ticket) WHERE status='OPEN';
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_risk (
 day TEXT PRIMARY KEY, starting_equity REAL NOT NULL, latest_equity REAL NOT NULL,
 paused INTEGER NOT NULL DEFAULT 0, entry_attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS stream_watermarks (
 instance TEXT NOT NULL, symbol TEXT NOT NULL, signal_time_ms INTEGER NOT NULL,
 PRIMARY KEY(instance,symbol)
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, at REAL NOT NULL, action TEXT NOT NULL, details_json TEXT NOT NULL
);
"""


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def utc_day(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).date().isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path.resolve()

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=1.5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported database version; do not overwrite the journal")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO state VALUES ('journal_id',?)", (canonical(uuid.uuid4().hex),))
            db.execute("PRAGMA user_version=1")

    def get_state(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value_json FROM state WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_state(self, key: str, value):
        with self.connect(write=True) as db:
            db.execute(
                "INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (key, canonical(value)),
            )

    def bind_account(self, login: int, server: str, magic: int):
        identity = {"login": login, "server": server, "magic": magic}
        with self.connect(write=True) as db:
            row = db.execute("SELECT value_json FROM state WHERE key='account_binding'").fetchone()
            if row and json.loads(row[0]) != identity:
                raise SafetyError("database_belongs_to_different_account_or_magic")
            db.execute("INSERT OR IGNORE INTO state VALUES ('account_binding',?)", (canonical(identity),))

    def audit(self, action: str, details: dict, now=None):
        with self.connect(write=True) as db:
            db.execute(
                "INSERT INTO audit(at,action,details_json) VALUES (?,?,?)",
                (time.time() if now is None else now, action, canonical(details)),
            )

    def duplicate(self, alert: AlertEnvelope):
        payload = canonical(alert.model_dump(mode="json"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM webhook_events WHERE instance=? AND event_id=?",
                (alert.context.instance, alert.context.event_id),
            ).fetchone()
            if row and row["payload_hash"] != digest:
                raise Reject("event_id_payload_conflict")
            return dict(row) if row else None

    def enqueue(self, alert: AlertEnvelope, broker_symbol: str, now: float, max_queue: int):
        payload = canonical(alert.model_dump(mode="json"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        sig = alert.context
        with self.connect(write=True) as db:
            old = db.execute(
                "SELECT * FROM webhook_events WHERE instance=? AND event_id=?", (sig.instance, sig.event_id)
            ).fetchone()
            if old:
                if old["payload_hash"] != digest:
                    raise Reject("event_id_payload_conflict")
                return dict(old), True
            count = db.execute(
                "SELECT count(*) FROM webhook_events WHERE status IN ('QUEUED','RETRY','PROCESSING')"
            ).fetchone()[0]
            if count >= max_queue:
                raise Reject("queue_full")
            cursor = db.execute(
                """INSERT INTO webhook_events
                (instance,event_id,trade_id,event_type,symbol,broker_symbol,payload_json,payload_hash,received_at,sent_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    sig.instance,
                    sig.event_id,
                    sig.trade_id,
                    sig.event,
                    sig.symbol,
                    broker_symbol,
                    payload,
                    digest,
                    now,
                    alert.sent_at.timestamp(),
                ),
            )
            return dict(
                db.execute("SELECT * FROM webhook_events WHERE id=?", (cursor.lastrowid,)).fetchone()
            ), False

    def claim(self, now: float):
        # Preserve FIFO per actual broker symbol, including aliases and strategy instances.
        with self.connect(write=True) as db:
            row = db.execute(
                """SELECT e.* FROM webhook_events e
                WHERE e.status IN ('QUEUED','RETRY') AND e.next_attempt<=?
                AND NOT EXISTS (SELECT 1 FROM webhook_events older
                    WHERE older.broker_symbol=e.broker_symbol AND older.id<e.id
                    AND older.status IN ('QUEUED','RETRY','PROCESSING'))
                ORDER BY e.id LIMIT 1""",
                (now,),
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE webhook_events SET status='PROCESSING',attempts=attempts+1 WHERE id=?", (row["id"],)
            )
            return dict(db.execute("SELECT * FROM webhook_events WHERE id=?", (row["id"],)).fetchone())

    def finish(self, event_pk: int, status: str, error: str | None = None, *, retry_at=0, now=None):
        with self.connect(write=True) as db:
            db.execute(
                "UPDATE webhook_events SET status=?,error=?,next_attempt=?,processed_at=? WHERE id=?",
                (status, error, retry_at, time.time() if now is None else now, event_pk),
            )

    def event(self, event_pk: int):
        with self.connect() as db:
            row = db.execute("SELECT * FROM webhook_events WHERE id=?", (event_pk,)).fetchone()
            return dict(row) if row else None

    def recover_queue(self):
        # Called only under the exclusive worker OS lock. SENDING may already be filled.
        with self.connect(write=True) as db:
            db.execute(
                "UPDATE operations SET status='UNKNOWN',error='worker_interrupted_during_send' WHERE status='SENDING'"
            )
            db.execute("""UPDATE webhook_events SET status='REVIEW',error='uncertain_broker_operation'
                WHERE id IN (SELECT event_pk FROM operations WHERE status='UNKNOWN')""")
            db.execute("UPDATE webhook_events SET status='QUEUED',next_attempt=0 WHERE status='PROCESSING'")

    def pending_events(self, broker_symbol: str) -> int:
        with self.connect() as db:
            return db.execute(
                "SELECT count(*) FROM webhook_events WHERE broker_symbol=? "
                "AND status IN ('QUEUED','RETRY','PROCESSING')",
                (broker_symbol,),
            ).fetchone()[0]

    def operations(self, statuses=None):
        with self.connect() as db:
            if statuses:
                rows = db.execute(
                    f"SELECT * FROM operations WHERE status IN ({','.join('?' for _ in statuses)}) ORDER BY created_at",
                    statuses,
                )
            else:
                rows = db.execute("SELECT * FROM operations ORDER BY created_at")
            return [dict(row) for row in rows]

    def operation(self, key: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM operations WHERE op_key=?", (key,)).fetchone()
            return dict(row) if row else None

    def prepare_operation(self, event_pk: int, trade_id: str, kind: str, request: dict, now: float):
        key = f"{event_pk}:{kind}"
        comment = "bfx-" + hashlib.sha256((self.get_state("journal_id") + key).encode()).hexdigest()[:24]
        request = {**request, "comment": comment}
        with self.connect(write=True) as db:
            db.execute(
                """INSERT OR IGNORE INTO operations
                (op_key,event_pk,trade_id,kind,status,request_json,comment,created_at,updated_at)
                VALUES (?,?,?,?,'PREPARED',?,?,?,?)""",
                (key, event_pk, trade_id, kind, canonical(request), comment, now, now),
            )
            row = db.execute("SELECT * FROM operations WHERE op_key=?", (key,)).fetchone()
            return dict(row)

    def refresh_prepared(self, key: str, request: dict, now: float):
        with self.connect(write=True) as db:
            row = db.execute("SELECT comment,status FROM operations WHERE op_key=?", (key,)).fetchone()
            if not row or row["status"] != "PREPARED":
                raise SafetyError("cannot_change_sent_operation")
            request = {**request, "comment": row["comment"]}
            db.execute(
                "UPDATE operations SET request_json=?,updated_at=? WHERE op_key=?",
                (canonical(request), now, key),
            )
        return self.operation(key)

    def mark_sending(self, key: str, now: float):
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM operations WHERE op_key=?", (key,)).fetchone()
            if not row or row["status"] != "PREPARED":
                raise SafetyError("operation_not_prepared")
            db.execute("UPDATE operations SET status='SENDING',updated_at=? WHERE op_key=?", (now, key))
            if row["kind"] == "OPEN":
                changed = db.execute(
                    "UPDATE daily_risk SET entry_attempts=entry_attempts+1 WHERE day=?", (utc_day(now),)
                ).rowcount
                if not changed:
                    raise SafetyError("daily_baseline_missing")

    def operation_result(self, key: str, status: str, result: dict | None, now: float, error=None):
        with self.connect(write=True) as db:
            db.execute(
                "UPDATE operations SET status=?,result_json=?,updated_at=?,error=? WHERE op_key=?",
                (status, canonical(result) if result is not None else None, now, error, key),
            )

    def open_positions(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM positions WHERE status='OPEN'")]

    def position(self, instance: str, trade_id: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM positions WHERE instance=? AND trade_id=?", (instance, trade_id)
            ).fetchone()
            return dict(row) if row else None

    def save_position(self, value: dict):
        allowed = {
            "instance",
            "trade_id",
            "tv_symbol",
            "symbol",
            "side",
            "ticket",
            "identifier",
            "volume",
            "entry_price",
            "sl",
            "tp",
            "stop_distance",
            "target_distance",
            "risk_budget",
            "status",
            "opened_at",
            "closed_at",
            "event_pk",
        }
        if set(value) != allowed:
            raise ValueError("Position record has unexpected/missing fields")
        columns = list(value)
        updates = ",".join(f"{key}=excluded.{key}" for key in columns if key not in {"instance", "trade_id"})
        with self.connect(write=True) as db:
            db.execute(
                f"INSERT INTO positions ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                f"ON CONFLICT(instance,trade_id) DO UPDATE SET {updates}",
                tuple(value.values()),
            )

    def close_position(self, instance: str, trade_id: str, now: float):
        with self.connect(write=True) as db:
            db.execute(
                "UPDATE positions SET status='CLOSED',closed_at=? WHERE instance=? AND trade_id=?",
                (now, instance, trade_id),
            )

    def tombstone(self, sig, broker_symbol: str, now: float, event_pk: int):
        if self.position(sig.instance, sig.trade_id):
            return
        self.save_position(
            dict(
                instance=sig.instance,
                trade_id=sig.trade_id,
                tv_symbol=sig.symbol,
                symbol=broker_symbol,
                side=sig.side,
                ticket=None,
                identifier=None,
                volume=0,
                entry_price=0,
                sl=0,
                tp=0,
                stop_distance=0,
                target_distance=None,
                risk_budget=0,
                status="CLOSED",
                opened_at=None,
                closed_at=now,
                event_pk=event_pk,
            )
        )

    def observe_equity(self, equity: float, max_loss: float, now: float):
        day = utc_day(now)
        with self.connect(write=True) as db:
            db.execute(
                "INSERT OR IGNORE INTO daily_risk(day,starting_equity,latest_equity) VALUES (?,?,?)",
                (day, equity, equity),
            )
            db.execute(
                "UPDATE daily_risk SET latest_equity=?,paused=CASE WHEN ?<=starting_equity*(1-?/100) THEN 1 ELSE paused END WHERE day=?",
                (equity, equity, max_loss, day),
            )
            return dict(db.execute("SELECT * FROM daily_risk WHERE day=?", (day,)).fetchone())

    def watermark(self, instance: str, symbol: str, signal_time_ms: int):
        with self.connect(write=True) as db:
            row = db.execute(
                "SELECT signal_time_ms FROM stream_watermarks WHERE instance=? AND symbol=?",
                (instance, symbol),
            ).fetchone()
            if row and signal_time_ms < row[0]:
                raise Reject("out_of_order_signal")
            db.execute(
                "INSERT INTO stream_watermarks VALUES (?,?,?) ON CONFLICT(instance,symbol) DO UPDATE SET signal_time_ms=max(signal_time_ms,excluded.signal_time_ms)",
                (instance, symbol, signal_time_ms),
            )

    def status(self):
        with self.connect() as db:
            counts = {
                row[0]: row[1]
                for row in db.execute("SELECT status,count(*) FROM webhook_events GROUP BY status")
            }
            recent = [
                dict(row)
                for row in db.execute(
                    "SELECT id,instance,event_id,event_type,symbol,status,error,received_at,processed_at FROM webhook_events ORDER BY id DESC LIMIT 50"
                )
            ]
            daily = db.execute("SELECT * FROM daily_risk ORDER BY day DESC LIMIT 1").fetchone()
            unresolved = db.execute(
                "SELECT count(*) FROM operations WHERE status IN ('UNKNOWN','SENDING')"
            ).fetchone()[0]
        return {
            "events": counts,
            "recent_events": recent,
            "open_positions": self.open_positions(),
            "daily_risk": dict(daily) if daily else None,
            "uncertain_operations": unresolved,
        }

    def backup(self, destination: Path):
        destination = destination.resolve()
        if destination == self.path or destination.exists():
            raise ValueError("Backup destination must be a new file")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
