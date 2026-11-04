"""Split targets: two strategy instances may each hold one bot position on the same symbol."""

from dataclasses import replace

from app.trading.broker import Position
from tests.python.test_engine import align, candle, downtrend_then_jump, stream

TF = 900


def allow_split(env, limit=2):
    rule = env.mapper.rules["OANDA:EURUSD"]
    env.mapper.rules["OANDA:EURUSD"] = rule.model_copy(update={"max_bot_positions": limit})


def run(env, **kw):
    row = env.enqueue(**kw)
    env.worker.tick()
    return env.db.event(row["id"])


def test_default_symbol_still_allows_one_position(env):
    assert run(env, instance="small", trade_id="t-a")["status"] == "EXECUTED"
    second = run(env, instance="big", trade_id="t-b")
    assert second["status"] == "REJECTED" and second["error"] == "existing_position_conflicts_with_flat_entry"
    assert len(env.broker.live) == 1


def test_two_halves_open_on_one_symbol(env):
    allow_split(env)
    assert run(env, instance="small", trade_id="t-a")["status"] == "EXECUTED"
    assert run(env, instance="big", trade_id="t-b")["status"] == "EXECUTED"
    assert len(env.broker.live) == 2
    assert {p["instance"] for p in env.db.open_positions()} == {"small", "big"}
    third = run(env, instance="other", trade_id="t-c")
    assert third["status"] == "REJECTED"
    assert len(env.broker.live) == 2


def test_same_instance_never_doubles(env):
    allow_split(env)
    run(env, instance="small", trade_id="t-a")
    again = run(env, instance="small", trade_id="t-a2")
    assert again["status"] == "IGNORED" and again["error"] == "same_side_position_no_pyramiding"
    assert len(env.broker.live) == 1


def test_manual_position_blocks_split(env):
    allow_split(env)
    env.broker.live.append(Position(77, 77, "EURUSD", "LONG", 0.1, 1.1, 1.09, 1.12, 0, "manual"))
    first = run(env, instance="small", trade_id="t-a")
    assert first["status"] == "REJECTED"
    assert len(env.broker.live) == 1


def test_netting_account_cannot_share_symbol(env):
    allow_split(env)
    run(env, instance="small", trade_id="t-a")
    env.broker.account_value = replace(env.broker.account_value, margin_mode=0)
    second = run(env, instance="big", trade_id="t-b")
    assert second["status"] == "REJECTED" and second["error"] == "netting_account_cannot_share_symbol"
    assert len(env.broker.live) == 1


def test_engine_queues_closes_before_entries(env):
    """Two halves on one symbol: on an opposite signal, the close is queued before any entry."""
    from app.signals.runner import SignalEngine

    allow_split(env)
    last_open = align(env)
    bars = downtrend_then_jump(last_open)
    env.broker.bars["EURUSD"] = bars + [candle(last_open + TF, 1.10001, 1.10001)]
    env.worker.maintain()
    # Only "big" is on at first, so it alone goes LONG on the jump.
    big = stream().model_copy(update={"instance": "big"})
    small = stream().model_copy(update={"instance": "small"})
    SignalEngine(env.settings, env.db, env.broker, env.mapper, mode="trade", streams=[big]).poll(env.clock())
    env.worker.tick()
    assert [p["instance"] for p in env.db.open_positions()] == ["big"]

    # Crash candle: big must close (opposite signal); small is flat and enters SHORT.
    env.now[0] += TF
    env.broker.bars["EURUSD"] = bars + [candle(last_open + TF, 1.10001, 1.07), candle(last_open + 2 * TF, 1.07, 1.07)]
    env.worker.maintain()
    SignalEngine(env.settings, env.db, env.broker, env.mapper, mode="trade", streams=[small, big]).poll(env.clock())
    queued = [e for e in reversed(env.db.status()["recent_events"]) if e["status"] == "QUEUED"]
    assert [(e["instance"], e["event_type"]) for e in queued] == [("big", "opposite_signal"), ("small", "entry")]
