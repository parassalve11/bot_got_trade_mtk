import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.database import Database
from app.schemas import AlertEnvelope
from app.trading.errors import SafetyError
from app.trading.lock import WorkerLock
from app.trading.worker import Worker


def test_concurrent_duplicate_delivery_has_one_durable_row(env):
    body = AlertEnvelope.model_validate(env.alert())
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: env.db.enqueue(body, "EURUSD", env.clock(), 100), range(16)))
    assert len({item[0]["id"] for item in values}) == 1
    assert sum(not item[1] for item in values) == 1


def test_worker_lock_refuses_second_owner_and_releases(env):
    path = env.settings.database_path.with_suffix(".worker.lock")
    with WorkerLock(path):
        with pytest.raises(RuntimeError):
            with WorkerLock(path):
                pass
    with WorkerLock(path):
        pass


def test_retry_preserves_symbol_fifo_but_allows_other_symbols(env):
    first = env.enqueue(trade_id="trade-1")
    env.enqueue(trade_id="trade-2")
    third = env.enqueue(trade_id="trade-3", symbol="OANDA:GBPUSD", reference_price=1.2)
    assert env.db.claim(env.clock())["id"] == first["id"]
    env.db.finish(first["id"], "RETRY", retry_at=env.clock() + 20)
    assert env.db.claim(env.clock())["id"] == third["id"]
    assert env.db.claim(env.clock()) is None


def test_crash_before_send_marks_unknown_and_does_not_replay(env):
    row = env.enqueue()
    env.db.claim(env.clock())
    env.worker.maintain()
    sig = AlertEnvelope.model_validate_json(row["payload_json"]).context
    plan = env.worker.executor.risk.plan(sig, env.mapper.resolve(sig.symbol), env.clock())
    op = env.db.prepare_operation(
        row["id"],
        sig.trade_id,
        "OPEN",
        {
            **plan.request,
            "_meta": dict(
                instance=sig.instance,
                tv_symbol=sig.symbol,
                side=sig.side,
                stop_distance=plan.stop_distance,
                target_distance=plan.target_distance,
                risk_budget=plan.risk_budget,
            ),
        },
        env.clock(),
    )
    env.db.mark_sending(op["op_key"], env.clock())
    env.db.recover_queue()
    assert env.db.event(row["id"])["status"] == "REVIEW"
    env.worker.tick()
    assert not env.broker.sent
    assert env.db.operation(op["op_key"])["status"] == "UNKNOWN"


def test_crash_after_broker_fill_before_result_commit_recovers_once(env, monkeypatch):
    original = env.db.operation_result

    def disk_failure(key, status, result, now, error=None):
        if status == "CONFIRMED":
            raise OSError("journal write lost")
        return original(key, status, result, now, error)

    monkeypatch.setattr(env.db, "operation_result", disk_failure)
    row = env.enqueue()
    env.worker.tick()
    assert env.db.operation(f"{row['id']}:OPEN")["status"] == "SENDING"
    monkeypatch.setattr(env.db, "operation_result", original)
    env.db.recover_queue()
    env.worker.tick()
    assert env.db.operation(f"{row['id']}:OPEN")["status"] == "CONFIRMED"
    assert len(env.broker.sent) == 1


def test_uncertain_close_recovery_does_not_close_again(env):
    env.enqueue()
    env.worker.tick()
    env.broker.next_behaviors = ["timeout_after_fill"]
    close = env.enqueue(event="opposite_signal")
    env.worker.tick()
    assert env.db.event(close["id"])["status"] == "REVIEW"
    env.db.recover_queue()
    env.worker.tick()
    assert env.db.event(close["id"])["status"] in ("EXECUTED", "IGNORED")
    assert len(env.broker.sent) == 2


def test_uncertain_protection_recovery_uses_broker_state(env):
    env.broker.slippage = 0.00003
    env.broker.next_behaviors = ["ok", "timeout_after_fill"]
    row = env.enqueue()
    env.worker.tick()
    assert env.db.event(row["id"])["status"] == "REVIEW"
    env.worker.tick()
    assert env.db.event(row["id"])["status"] == "EXECUTED"
    assert len(env.broker.sent) == 2
    assert not env.db.get_state("safety_hold")


def test_uncertain_open_that_already_hit_broker_stop_is_not_reopened(env):
    env.broker.next_behaviors = ["timeout_after_fill"]
    row = env.enqueue()
    env.worker.tick()
    env.broker.broker_exit(env.broker.live[0])
    env.worker.tick()
    assert env.db.event(row["id"])["status"] == "EXECUTED"
    assert env.db.position("main", "trade-1")["status"] == "CLOSED"
    assert len(env.broker.sent) == 1


def test_old_entry_signal_is_rejected_but_old_trade_close_with_new_sent_at_is_valid(env):
    env.enqueue()
    env.worker.tick()
    env.now[0] += 86400
    row = env.enqueue(event="opposite_signal", signal_time_ms=int((env.clock() - 86400) * 1000))
    env.worker.tick()
    assert env.db.event(row["id"])["status"] == "EXECUTED"


def test_daily_entry_limit_survives_worker_restart(env):
    env.settings.max_daily_entries = 1
    env.enqueue()
    env.worker.tick()
    env.broker.broker_exit(env.broker.live[0])
    other = env.enqueue(trade_id="trade-2")
    restored = Worker(env.settings, env.db, env.broker, env.mapper, clock=env.clock)
    restored.tick()
    assert env.db.event(other["id"])["error"] == "daily_entry_limit"
    assert len(env.broker.sent) == 1


def test_account_binding_rejects_second_account_and_magic(env):
    env.db.bind_account(1, "A", 10)
    with pytest.raises(SafetyError):
        env.db.bind_account(2, "A", 10)
    with pytest.raises(SafetyError):
        env.db.bind_account(1, "A", 20)


def test_online_backup_retains_dedupe_and_risk_state(env):
    env.enqueue()
    env.worker.tick()
    destination = env.tmp_path / "snapshot.db"
    env.db.backup(destination)
    copy = Database(destination)
    copy.initialize()
    assert copy.event(1)["status"] == "EXECUTED"
    assert copy.open_positions()[0]["trade_id"] == "trade-1"
    assert copy.status()["daily_risk"]["entry_attempts"] == 1
    assert copy.get_state("journal_id") == env.db.get_state("journal_id")


def test_no_stop_and_freeze_level_failure_uses_emergency_close(env):
    env.broker.next_behaviors = ["missing_protection"]
    env.broker.symbols["EURUSD"] = replace(env.broker.symbols["EURUSD"], freeze_level=200)
    row = env.enqueue()
    env.worker.tick()
    assert env.db.event(row["id"])["status"] == "REVIEW"
    assert not env.broker.live


def test_uncertain_response_payload_is_not_treated_as_failure(env):
    env.broker.next_behaviors = ["timeout_no_fill"]
    row = env.enqueue()
    env.worker.tick()
    saved = env.db.operation(f"{row['id']}:OPEN")
    assert saved["status"] == "UNKNOWN"
    assert json.loads(saved["result_json"])["retcode"] == 10012
