import math

import pytest

from app.signals.runner import SignalEngine
from app.signals.ut_engine import (
    BarSignal,
    StreamConfig,
    decide,
    rma,
    signal_series,
    true_range,
    ut_stops,
)

TF = 900


def stream(**changes):
    return StreamConfig(tv_symbol="OANDA:EURUSD", instance="engine", **changes)


def candle(time, open_, close):
    return dict(time=time, open=open_, high=max(open_, close) + 0.00005, low=min(open_, close) - 0.00005,
                close=close)


def align(env):
    """Put the clock 5 s after a 15-minute candle closed; return that candle's open time."""
    base = math.floor(env.now[0] / TF) * TF
    env.now[0] = base + 5
    return base - TF


def downtrend_then_jump(last_open):
    """Steady decline, then a final closed candle that jumps up through the UT line."""
    count = 300
    bars, price = [], 1.1100
    for k in range(count - 1):
        close = 1.1100 - k * 0.00005
        bars.append(candle(last_open - (count - 1 - k) * TF, price, close))
        price = close
    bars.append(candle(last_open, price, 1.10001))
    return bars


def test_rma_is_seeded_with_sma_like_pine():
    values = rma([1.0, 2.0, 3.0, 4.0, 5.0], 3)
    assert math.isnan(values[0]) and math.isnan(values[1])
    assert values[2] == pytest.approx(2.0)
    assert values[3] == pytest.approx((4 + 2 * 2) / 3)
    assert values[4] == pytest.approx((5 + 2 * values[3]) / 3)


def test_true_range_uses_previous_close_after_first_bar():
    assert true_range([2.0, 5.0], [1.0, 4.0], [1.5, 4.5]) == [1.0, 3.5]


def test_ut_stop_ratchets_and_never_loosens_in_a_trend():
    closes = [1.0 + i * 0.01 for i in range(50)]
    stops = ut_stops(closes, [0.005] * 50, 2.0)
    assert all(b >= a for a, b in zip(stops[5:], stops[6:]))
    assert all(stop < close for stop, close in zip(stops[5:], closes[5:]))


def test_signal_only_on_the_crossing_candle_with_pine_tick_rounding():
    bars = downtrend_then_jump(1_000_000 * TF)
    signals = signal_series(bars, stream(), 0.00001)
    last = signals[-1]
    assert last.side == "LONG" and last.close == 1.10001
    assert last.loss_ticks >= 1 and last.loss_ticks == int(last.loss_ticks)
    assert last.profit_ticks == math.ceil(last.loss_ticks * 1.5 - 1e-9)
    assert signals[-2] is None
    assert signal_series(bars, stream(target_mode="Off"), 0.00001)[-1].profit_ticks is None


@pytest.mark.parametrize(
    "side,position,changes,expected",
    [
        ("LONG", None, {}, "entry"),
        ("LONG", "LONG", {}, None),
        ("SHORT", "LONG", {}, "close"),
        ("SHORT", "LONG", {"opposite_mode": "Close + reverse"}, "reverse"),
        ("SHORT", "LONG", {"opposite_mode": "Ignore"}, None),
        ("SHORT", None, {"direction": "Long only"}, None),
        # Direction filter blocks the reversal entry but the opposite signal still closes.
        ("SHORT", "LONG", {"direction": "Long only", "opposite_mode": "Close + reverse"}, "close"),
    ],
)
def test_decide_matches_pine_order_logic(side, position, changes, expected):
    signal = BarSignal(side, 1.1, 100, 150)
    assert decide(signal, position, stream(**changes)) == expected
    assert decide(None, position, stream(**changes)) is None


def engine(env, mode="trade"):
    return SignalEngine(env.settings, env.db, env.broker, env.mapper, mode=mode, streams=[stream()])


def test_engine_trade_mode_opens_then_closes_through_normal_execution(env):
    last_open = align(env)
    bars = downtrend_then_jump(last_open)
    env.broker.bars["EURUSD"] = bars + [candle(last_open + TF, 1.10001, 1.10001)]  # forming bar ignored
    env.worker.maintain()
    runner = engine(env)
    runner.poll(env.clock())
    queued = env.db.status()["recent_events"]
    assert [(e["event_type"], e["status"]) for e in queued] == [("entry", "QUEUED")]
    runner.poll(env.clock())  # Same candle again: no duplicate.
    assert len(env.db.status()["recent_events"]) == 1
    env.worker.tick()
    record = env.db.open_positions()[0]
    assert record["side"] == "LONG" and record["instance"] == "engine"
    assert env.broker.live[0].sl > 0 and env.broker.live[0].tp > 0

    # Next candle crashes through the UT line: "Close only" closes the long.
    env.now[0] += TF
    crash = candle(last_open + TF, 1.10001, 1.07)
    env.broker.bars["EURUSD"] = bars + [crash, candle(last_open + 2 * TF, 1.07, 1.07)]
    env.worker.maintain()
    runner.poll(env.clock())
    event = env.db.status()["recent_events"][0]
    assert event["event_type"] == "opposite_signal" and event["status"] == "QUEUED"
    env.worker.tick()
    assert env.db.open_positions() == [] and env.broker.live == []


def test_watch_mode_only_audits(env):
    last_open = align(env)
    env.broker.bars["EURUSD"] = downtrend_then_jump(last_open)
    engine(env, mode="watch").poll(env.clock())
    assert env.db.status()["recent_events"] == []
    assert not env.broker.sent
    with env.db.connect() as db:
        actions = [row[0] for row in db.execute("SELECT action FROM audit")]
    assert "engine_signal_watch_only" in actions


def test_late_candle_is_skipped_never_traded(env):
    last_open = align(env)
    env.broker.bars["EURUSD"] = downtrend_then_jump(last_open)
    env.now[0] += 300  # Worker was down when the candle closed.
    engine(env).poll(env.clock())
    assert env.db.status()["recent_events"] == []


def test_engine_failures_never_raise_out_of_poll(env):
    align(env)
    env.broker.bars = {}  # rates unavailable
    engine(env).poll(env.clock())


def test_webhook_cannot_inject_engine_signals(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    body = env.alert()
    body["context"]["source"] = "mt5_engine"
    with TestClient(create_app(env.settings), client=("127.0.0.1", 1234)) as client:
        response = client.post(
            "/api/v1/webhooks/tradingview/" + env.settings.webhook_token.get_secret_value(), json=body
        )
    assert response.status_code == 403
