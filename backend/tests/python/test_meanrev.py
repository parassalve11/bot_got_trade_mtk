import math

import pytest

from app.signals.meanrev import MeanRevSettings, meanrev_state
from app.signals.runner import SignalEngine
from app.signals.ut_engine import StreamConfig

M15 = 900


def uptrend_with_dip(t0=0, n=260, end=1.1006):
    """Slow uptrend, then two sharp down candles that stay above SMA200 (RSI(2) ~ 0)."""
    closes = [end - 0.0004 - (n - 1 - i) * 0.00005 for i in range(n)]
    closes += [closes[-1] - 0.0005, closes[-1] - 0.0010]
    return [dict(time=t0 + i * M15, open=c + 0.00002, high=c + 0.0001, low=c - 0.0001, close=c)
            for i, c in enumerate(closes)]


def stream(**changes):
    return StreamConfig(instance="mr_eurusd", tv_symbol="OANDA:EURUSD", timeframe="15", strategy="meanrev",
                        risk_percent=0.5, history_bars=600, **changes)


def test_rsi2_dip_in_uptrend_is_a_buy():
    bars = uptrend_with_dip()
    st = meanrev_state(bars)
    assert st.entry == "LONG" and st.rsi < 5 and st.close > st.trend
    assert st.stop_for("LONG", 2.0) == pytest.approx(st.close - 2 * st.atr)
    assert meanrev_state(bars[:-2]).entry is None          # no dip yet: RSI(2) high
    assert meanrev_state(bars, MeanRevSettings(trade_dir="Short only")).entry is None
    assert meanrev_state(bars[:100]) is None                # not enough history for SMA200


def test_stream_is_intraday_group():
    assert stream().group == "intraday"
    assert StreamConfig(tv_symbol="OANDA:EURUSD", timeframe="60").group == "swing"


def run(env, bars, base):
    env.broker.bars["EURUSD"] = bars + [dict(bars[-1], time=base)]  # plus the forming candle
    env.worker.maintain()
    SignalEngine(env.settings, env.db, env.broker, env.mapper, mode="trade", streams=[stream()]).poll(env.clock())
    return env.db.status()["recent_events"]


def test_engine_buys_with_atr_stop_then_exits_on_sma5_cross(env):
    base = math.floor(env.now[0] / M15) * M15
    env.now[0] = base + 5
    raw = uptrend_with_dip()
    bars = [dict(b, time=base - (len(raw) - i) * M15) for i, b in enumerate(raw)]
    events = run(env, bars, base)
    assert [(e["event_type"], e["status"]) for e in events] == [("entry", "QUEUED")]
    env.worker.tick()
    record = env.db.open_positions()[0]
    assert record["instance"] == "mr_eurusd" and record["side"] == "LONG"
    assert record["target_distance"] is None and env.broker.live[0].tp == 0
    st = meanrev_state(bars)
    assert record["stop_distance"] == pytest.approx(2 * st.atr, abs=2e-5)

    # Next candle closes back above SMA5 -> close the trade.
    nxt = base + M15
    env.now[0] = nxt + 5
    up = dict(bars[-1], time=base, open=1.1002, high=1.1012, low=1.1001, close=1.1010)
    events = run(env, bars + [up], nxt)
    assert events[0]["event_type"] == "date_end"
    env.worker.tick()
    assert env.db.open_positions() == [] and env.broker.live == []


def test_engine_time_exit_after_max_hold(env):
    base = math.floor(env.now[0] / M15) * M15
    env.now[0] = base + 5
    raw = uptrend_with_dip()
    bars = [dict(b, time=base - (len(raw) - i) * M15) for i, b in enumerate(raw)]
    run(env, bars, base)
    env.worker.tick()
    low = bars[-1]["close"]
    held = []
    for k in range(8):   # price stays below SMA5: only the time stop can close it
        t = base + k * M15
        held.append(dict(bars[-1], time=t, open=low, high=low + 0.00005, low=low - 0.00005, close=low - 0.00001))
        env.now[0] = t + M15 + 5
        last = run(env, bars + held, t + M15)[0]["event_type"]
        if k < 7:
            assert last == "entry"
    assert last == "date_end"
