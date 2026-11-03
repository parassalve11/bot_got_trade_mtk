from dataclasses import replace

import pytest

from app.trading.broker import Position
from app.trading.worker import Worker


def run(env, **kwargs):
    row = env.enqueue(**kwargs)
    env.worker.tick()
    return env.db.event(row["id"])


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_entry_attaches_real_protection_and_sizes_broker_lots(env, side):
    row = run(env, side=side)
    assert row["status"] == "EXECUTED", row
    pos = env.broker.live[0]
    assert pos.side == side
    assert pos.volume != 100  # TV contracts must never be used as MT5 lots.
    assert pos.sl > 0 and pos.tp > 0
    assert -env.broker.profit(side, pos.symbol, pos.volume, pos.price_open, pos.sl) <= 50
    assert env.broker.sent[0]["sl"] > 0  # Protection included on the initial market request.
    assert env.broker.checked
    record = env.db.open_positions()[0]
    assert record["ticket"] == pos.ticket
    assert record["identifier"] == pos.identifier


def test_duplicate_webhook_and_same_side_never_pyramid(env):
    value = env.alert()
    from app.schemas import AlertEnvelope

    alert = AlertEnvelope.model_validate(value)
    first, dup = env.db.enqueue(alert, "EURUSD", env.clock(), 100)
    second, dup2 = env.db.enqueue(alert, "EURUSD", env.clock(), 100)
    assert not dup and dup2 and first["id"] == second["id"]
    env.worker.tick()
    result = run(env, trade_id="trade-2")
    assert result["status"] == "IGNORED"
    assert len(env.broker.sent) == 1
    assert len(env.broker.live) == 1


def test_reversal_closes_and_confirms_before_new_open(env):
    run(env)
    original_ticket = env.broker.live[0].ticket
    result = run(env, event="reverse", side="SHORT", trade_id="trade-2", previous="trade-1")
    assert result["status"] == "EXECUTED", result
    assert len(env.broker.sent) == 3
    assert env.broker.sent[1]["position"] == original_ticket
    assert "position" not in env.broker.sent[2]
    assert len(env.broker.live) == 1 and env.broker.live[0].side == "SHORT"
    assert env.db.position("main", "trade-1")["status"] == "CLOSED"


def test_reversal_cannot_close_other_instance_or_wrong_trade(env):
    run(env)
    result = run(env, event="reverse", side="SHORT", trade_id="trade-2", previous="unknown")
    assert result["status"] == "REJECTED"
    assert len(env.broker.sent) == 1


def test_reversal_partial_close_does_not_open_new_side(env):
    run(env)
    env.broker.next_behaviors = ["partial"]
    result = run(env, event="reverse", side="SHORT", trade_id="trade-2", previous="trade-1")
    assert result["status"] == "REVIEW"
    assert len(env.broker.sent) == 2
    assert len(env.broker.live) == 1 and env.broker.live[0].side == "LONG"
    assert env.db.get_state("safety_hold")


@pytest.mark.parametrize("event", ["stop_loss", "take_profit"])
def test_pine_protective_exits_are_audit_only(env, event):
    run(env)
    result = run(env, event=event)
    assert result["status"] == "LOGGED"
    assert len(env.broker.live) == 1 and len(env.broker.sent) == 1


@pytest.mark.parametrize("event", ["opposite_signal", "daily_loss", "date_end"])
def test_explicit_closes_work_even_while_entries_paused(env, event):
    run(env)
    env.db.set_state("operator_pause", True)
    env.settings.trading_enabled = False
    result = run(env, event=event)
    assert result["status"] == "EXECUTED", result
    assert not env.broker.live


def test_out_of_order_close_tombstones_trade(env):
    assert run(env, event="opposite_signal")["status"] == "IGNORED"
    assert run(env)["status"] == "IGNORED"
    assert not env.broker.sent


def test_closed_trade_exit_does_not_close_newer_position(env):
    run(env)
    env.broker.broker_exit(env.broker.live[0])
    env.worker.maintain()
    run(env, trade_id="trade-2")
    result = run(env, event="opposite_signal", trade_id="trade-1")
    assert result["status"] == "IGNORED"
    assert len(env.broker.live) == 1
    assert env.db.open_positions()[0]["trade_id"] == "trade-2"


@pytest.mark.parametrize("behavior", ["timeout_after_fill", "exception_after_fill", "none_after_fill"])
def test_uncertain_send_reconciles_without_duplicate_order(env, behavior):
    env.broker.next_behaviors = [behavior]
    result = run(env)
    assert result["status"] == "REVIEW"
    assert len(env.broker.live) == 1
    # Simulate service restart with the same durable journal and broker account.
    env.db.recover_queue()
    restored = Worker(env.settings, env.db, env.broker, env.mapper, clock=env.clock)
    restored.tick()
    assert env.db.event(result["id"])["status"] == "EXECUTED"
    assert len(env.broker.sent) == 1
    assert len(env.db.open_positions()) == 1


def test_timeout_without_evidence_never_retries_send(env):
    env.broker.next_behaviors = ["timeout_no_fill"]
    result = run(env)
    assert result["status"] == "REVIEW"
    for _ in range(3):
        env.now[0] += 2
        env.worker.tick()
    assert len(env.broker.sent) == 1
    assert env.db.operations(["UNKNOWN"])


def test_restart_recovers_known_open_after_position_write_crash(env, monkeypatch):
    original = env.db.save_position
    monkeypatch.setattr(env.db, "save_position", lambda _: (_ for _ in ()).throw(OSError("disk error")))
    result = run(env)
    assert len(env.broker.live) == 1
    assert result["status"] == "REVIEW"
    monkeypatch.setattr(env.db, "save_position", original)
    env.db.recover_queue()
    env.worker.maintain()
    assert len(env.db.open_positions()) == 1
    assert len(env.broker.sent) == 1


def test_partial_open_keeps_actual_volume_without_topping_up(env):
    env.broker.next_behaviors = ["partial"]
    result = run(env)
    assert result["status"] == "EXECUTED", result
    assert env.db.open_positions()[0]["volume"] == env.broker.live[0].volume
    assert len(env.broker.sent) == 1


def test_fill_reanchors_levels_and_verifies_modification(env):
    env.broker.slippage = 0.00003
    result = run(env)
    assert result["status"] == "EXECUTED", result
    assert len(env.broker.sent) == 2 and env.broker.sent[1]["action"] == 6
    pos = env.broker.live[0]
    assert abs(pos.price_open - pos.sl - 0.001) < 1e-9


def test_excessive_fill_slippage_flattens_and_pauses(env):
    env.broker.slippage = 0.001
    result = run(env)
    assert result["status"] == "REVIEW"
    assert not env.broker.live
    assert env.db.get_state("safety_hold")
    assert len(env.broker.sent) == 2


def test_missing_initial_sl_is_repaired(env):
    env.broker.next_behaviors = ["missing_protection"]
    result = run(env)
    assert result["status"] == "EXECUTED", result
    assert env.broker.live[0].sl > 0
    assert env.broker.sent[1]["action"] == 6


def test_failed_protection_modification_flattens_instead_of_naked_retry(env):
    env.broker.next_behaviors = ["missing_protection", "reject", "ok"]
    result = run(env)
    assert result["status"] == "REVIEW"
    assert not env.broker.live
    assert env.db.get_state("safety_hold")


def test_broker_side_stop_is_reconciled(env):
    run(env)
    env.broker.broker_exit(env.broker.live[0])
    env.worker.maintain()
    assert not env.db.open_positions()
    assert len(env.broker.sent) == 1


def test_manual_position_conflict_is_untouched(env):
    manual = Position(7, 7, "EURUSD", "LONG", 0.1, 1.1, 1.09, 1.12, 0, "manual")
    env.broker.live.append(manual)
    result = run(env)
    assert result["status"] == "REJECTED"
    assert env.broker.live == [manual]
    assert not env.broker.sent


def test_orphan_magic_position_blocks_new_entries(env):
    orphan = Position(7, 7, "GBPUSD", "LONG", 0.1, 1.2, 1.19, 1.22, env.settings.magic_number, "orphan")
    env.broker.live.append(orphan)
    result = run(env)
    assert result["status"] in ("RETRY", "REJECTED")
    assert env.db.get_state("safety_hold")["reason"] == "unrecognized_bot_position"
    assert not env.broker.sent


def test_mixed_netting_ownership_is_not_closed(env):
    run(env)
    pos = env.broker.live[0]
    env.broker.add_deal(
        identifier=pos.identifier,
        order=900,
        side="LONG",
        entry=0,
        volume=0.01,
        price=1.1,
        symbol=pos.symbol,
        magic=0,
        comment="manual",
    )
    result = run(env, event="opposite_signal")
    assert result["status"] == "REVIEW"
    assert len(env.broker.sent) == 1


@pytest.mark.parametrize(
    "case,reason",
    [
        ("risk", "requested_risk_above_server_limit"),
        ("spread", "spread_limit"),
        ("stops", "broker_minimum_stop_violation"),
        ("margin", "insufficient_free_margin"),
        ("minlot", "risk_budget_below_minimum_lot"),
        ("drift", "price_drift_limit"),
        ("paused", "entries_paused"),
    ],
)
def test_risk_rejections_do_not_send(env, case, reason):
    args = {}
    if case == "risk":
        args["risk_percent"] = 10
    if case == "spread":
        env.broker.quotes["EURUSD"] = (1.1, 1.101)
    if case == "stops":
        args["stop_ticks"] = 1
    if case == "margin":
        env.broker.account_value = replace(env.broker.account_value, margin_free=1)
    if case == "minlot":
        env.broker.account_value = replace(env.broker.account_value, equity=1)
    if case == "drift":
        args["reference_price"] = 1.0
    if case == "paused":
        env.db.set_state("operator_pause", True)
    result = run(env, **args)
    assert result["status"] == "REJECTED", result
    assert result["error"] == reason
    assert not env.broker.sent


def test_daily_loss_latches_across_restart_and_equity_rebound(env):
    env.worker.maintain()
    env.broker.account_value = replace(env.broker.account_value, equity=9600)
    env.worker.maintain()
    env.broker.account_value = replace(env.broker.account_value, equity=10000)
    restored = Worker(env.settings, env.db, env.broker, env.mapper, clock=env.clock)
    env.enqueue()
    restored.tick()
    assert env.db.event(1)["error"] == "daily_equity_loss_limit"
    assert not env.broker.sent
    env.now[0] += 86400
    restored.maintain()
    assert not env.db.status()["daily_risk"]["paused"]


def test_live_account_requires_both_live_switch_and_expected_identity(env):
    env.broker.account_value = replace(env.broker.account_value, trade_mode=2)
    run(env)
    assert not env.broker.sent
    assert env.db.get_state("safety_hold")["reason"] == "account_demo_live_mode_mismatch"


def test_different_login_cannot_use_journal(env):
    env.worker.maintain()
    env.broker.account_value = replace(env.broker.account_value, login=999999)
    run(env)
    assert not env.broker.sent
    assert env.db.get_state("safety_hold")["reason"] == "unexpected_mt5_account"


def test_offline_retry_recovers_and_does_not_duplicate(env):
    env.broker.offline = True
    result = run(env)
    assert result["status"] == "RETRY"
    env.broker.offline = False
    env.now[0] += 3
    env.worker.tick()
    assert env.db.event(result["id"])["status"] == "EXECUTED"
    assert len(env.broker.sent) == 1


def test_stale_queued_entry_is_rejected_after_reconnect(env):
    env.broker.offline = True
    result = run(env)
    env.now[0] += 400
    env.broker.offline = False
    env.worker.tick()
    assert env.db.event(result["id"])["status"] == "REJECTED"
    assert not env.broker.sent


def test_check_rejection_and_send_rejection_are_not_retried(env):
    env.broker.check_retcode = 10019
    result = run(env)
    assert result["status"] == "REJECTED" and not env.broker.sent
    env.broker.check_retcode = 0
    env.broker.next_behaviors = ["reject"]
    result = run(env, trade_id="trade-2")
    assert result["status"] == "REJECTED"
    env.worker.tick()
    assert len(env.broker.sent) == 1
