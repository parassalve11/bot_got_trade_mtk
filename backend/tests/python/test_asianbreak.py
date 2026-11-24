import math

import pytest

from app.signals.asianbreak import BreakoutSettings, breakout_state
from app.signals.runner import SignalEngine
from app.signals.ut_engine import StreamConfig

M15 = 900


def day_bars(day0, closes_after, lo=1.0990, hi=1.1010):
    """Candles from 01:00 (server = UTC in tests): 32 range candles inside [lo, hi], then `closes_after`."""
    bars = []
    t = day0 + 3600
    for k in range(32):                                  # 01:00 .. 08:45
        mid = lo + (hi - lo) * (0.25 if k % 2 else 0.75)
        bars.append(dict(time=t, open=mid, high=hi if k == 3 else mid + 0.0001,
                         low=lo if k == 7 else mid - 0.0001, close=mid))
        t += M15
    for c in closes_after:                               # from 09:00
        bars.append(dict(time=t, open=c, high=c + 0.0001, low=c - 0.0001, close=c))
        t += M15
    return bars


def test_first_close_above_range_is_a_buy_with_stop_in_the_middle():
    day0 = 20_000 * 86400
    bars = day_bars(day0, [1.1000, 1.1015])              # 09:00 inside, 09:15 closes above
    st = breakout_state(bars, M15, 0)
    assert st.entry == "LONG" and st.high == pytest.approx(1.1010) and st.low == pytest.approx(1.0990)
    assert st.stop == pytest.approx(1.1000)
    assert breakout_state(bars[:-1], M15, 0).entry is None
    assert breakout_state(bars, M15, 0, BreakoutSettings(stop_mode="opposite")).stop == pytest.approx(1.0990)
    assert breakout_state(bars, M15, 0, BreakoutSettings(trade_dir="Short only")).entry is None


def test_only_the_first_breakout_of_the_day_counts():
    day0 = 20_000 * 86400
    bars = day_bars(day0, [1.1015, 1.1000, 1.0980])      # up first, later down: no second trade
    assert breakout_state(bars, M15, 0).entry is None
    assert breakout_state(bars[:-2], M15, 0).entry == "LONG"


def test_server_offset_shifts_the_session():
    day0 = 20_000 * 86400
    bars = day_bars(day0, [1.1015])
    shifted = [dict(b, time=b["time"] - 7200) for b in bars]   # bot times = server time - 2 h
    assert breakout_state(shifted, M15, 7200).entry == "LONG"
    assert breakout_state(shifted, M15, 0).entry is None      # wrong clock: range not complete


def test_exit_on_the_candle_ending_at_22_45():
    day0 = 20_000 * 86400
    bars = day_bars(day0, [1.1015] * 54)                 # 09:00 .. 22:15
    assert bars[-1]["time"] % 86400 == 22 * 3600 + 15 * 60
    assert not breakout_state(bars, M15, 0).exit_now
    bars += day_bars(day0, [1.1015] * 55)[-1:]           # 22:30 candle closes 22:45
    assert breakout_state(bars, M15, 0).exit_now


def stream():
    return StreamConfig(instance="ab_eurusd", tv_symbol="OANDA:EURUSD", timeframe="15", strategy="breakout",
                        risk_percent=0.5, history_bars=200)


def run(env, bars, forming):
    env.broker.bars["EURUSD"] = bars + [dict(bars[-1], time=forming)]
    env.worker.maintain()
    SignalEngine(env.settings, env.db, env.broker, env.mapper, mode="trade", streams=[stream()]).poll(env.clock())
    return env.db.status()["recent_events"]


def test_engine_trades_breakout_and_closes_at_day_end(env):
    day0 = math.floor(env.now[0] / 86400) * 86400
    bars = day_bars(day0, [1.1000, 1.1015])
    forming = bars[-1]["time"] + M15
    env.now[0] = forming + 5
    events = run(env, bars, forming)
    assert [(e["event_type"], e["status"]) for e in events] == [("entry", "QUEUED")]
    env.worker.tick()
    record = env.db.open_positions()[0]
    assert record["instance"] == "ab_eurusd" and record["side"] == "LONG" and record["target_distance"] is None
    # stop distance = breakout close - range middle, applied from the fill (as for every strategy)
    assert record["stop_distance"] == pytest.approx(0.0015, abs=2e-5)

    rest = day_bars(day0, [1.1000, 1.1015] + [1.1012] * 53)[len(bars):]   # .. 22:30 candle
    for k in range(len(rest)):
        forming = rest[k]["time"] + M15
        env.now[0] = forming + 5
        top = run(env, bars + rest[:k + 1], forming)[0]["event_type"]
        if k < len(rest) - 1:
            assert top == "entry"
    assert top == "date_end"
    env.worker.tick()
    assert env.db.open_positions() == [] and env.broker.live == []
