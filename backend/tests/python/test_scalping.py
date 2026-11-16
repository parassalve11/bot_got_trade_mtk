import math
import random

from app.signals.scalping import ScalpSettings, scalp_trades


def _walk(n=6000, seed=7, tf=5, gap_every=0):
    rnd = random.Random(seed)
    bars, price, t = [], 100.0, 1_700_000_000.0 - 1_700_000_000.0 % 86400
    for i in range(n):
        if i and i % 78 == 0:  # new session every 78 five-minute candles
            t += 86400 - 78 * tf * 60
            if gap_every:
                price *= 1 + rnd.choice([-1, 1]) * 0.02
        o = price
        c = o * (1 + rnd.gauss(0, 0.002))
        h, lo = max(o, c) * (1 + abs(rnd.gauss(0, 0.001))), min(o, c) * (1 - abs(rnd.gauss(0, 0.001)))
        bars.append(dict(time=t, open=o, high=h, low=lo, close=c, volume=1000 + rnd.random() * 500))
        price, t = c, t + tf * 60
    return bars


def test_trades_are_well_formed():
    trades = scalp_trades(_walk(), 5)
    assert len(trades) > 50
    for t in trades:
        d = 1 if t.side == "LONG" else -1
        assert t.risk > 0 and math.isfinite(t.r)
        assert d * (t.entry - t.sl) > 0 and d * (t.tp1 - t.entry) > 0 and d * (t.tp2 - t.tp1) > 0
        assert t.exit_bar > t.bar
    # one trade at a time, like the indicator
    assert all(b.bar >= a.exit_bar for a, b in zip(trades, trades[1:]))


def test_stop_gap_fills_at_open_when_fixed():
    bars = _walk(gap_every=1)
    old = [t for t in scalp_trades(bars, 5, ScalpSettings(fixed=False)) if t.reason == "SL hit"]
    new = [t for t in scalp_trades(bars, 5, ScalpSettings(fixed=True)) if t.reason == "SL hit"]
    assert all(abs(t.r + 1) < 1e-9 for t in old)          # Pine v1: always exactly -1R
    assert all(t.r <= -1 + 1e-9 for t in new)              # v2: never better than the stop
    assert any(t.r < -1 - 1e-6 for t in new)               # and the gaps really cost more


def test_direction_filter():
    trades = scalp_trades(_walk(), 5, ScalpSettings(trade_dir="Short only"))
    assert trades and all(t.side == "SHORT" for t in trades)
