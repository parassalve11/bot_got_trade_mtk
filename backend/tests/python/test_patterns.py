import math

import pytest

from app.signals.patterns import PatternSettings, atr14, pattern_signals
from app.signals.runner import SignalEngine
from app.signals.ut_engine import StreamConfig

H1 = 3600
# Warm-up wiggle, inverted head and shoulders (shoulders 100, head 95, neckline 106), breakout.
IHS = [110, 108, 110, 108, 110, 100, 106, 95, 106, 100, 108]


def zigzag(points, t0=0, step=8, scale=1.0, shift=0.0, wick=0.3):
    closes = []
    for a, b in zip(points, points[1:]):
        closes += [a + (b - a) * k / step for k in range(step)]
    closes.append(points[-1])
    return [dict(time=t0 + i * H1, open=shift + c * scale, high=shift + (c + wick) * scale,
                 low=shift + (c - wick) * scale, close=shift + c * scale) for i, c in enumerate(closes)]


def first_signal(bars, cfg=None):
    return next((i, s) for i, s in enumerate(pattern_signals(bars, cfg)) if s)


def test_inverted_head_and_shoulders_buy_on_neckline_break():
    bars = zigzag(IHS)
    i, sig = first_signal(bars)
    assert sig.pattern == "Inverted Head and Shoulders" and sig.side == "LONG" and sig.reversal
    assert bars[i - 1]["close"] <= 106.3 < sig.close  # first close above the neckline (swing highs 106.3)
    atr = atr14([b["high"] for b in bars], [b["low"] for b in bars], [b["close"] for b in bars])[i]
    assert sig.stop == pytest.approx(99.7 - 0.2 * atr)  # right-shoulder low minus 0.2 ATR
    assert sig.target == pytest.approx(sig.close + (106.3 - 94.7))  # 1x pattern height
    assert all(s is None for s in pattern_signals(bars)[i + 1:])  # one signal, no repaint


def test_head_and_shoulders_is_the_mirror_sell():
    bars = zigzag([200 - p for p in IHS])
    _, sig = first_signal(bars)
    assert sig.pattern == "Head and Shoulders" and sig.side == "SHORT" and sig.stop > sig.close > sig.target


def test_pattern_settings_filter_signals():
    bars = zigzag(IHS)
    assert all(s is None for s in pattern_signals(bars, PatternSettings(trade_dir="Short only")))
    assert all(s is None for s in pattern_signals(bars, PatternSettings(show_ihs=False, show_rb=False,
                                                                        show_cup=False)))


def test_late_breakout_is_not_traded():
    # Same pattern, but the breakout candle closes far (> 1 ATR) beyond the neckline.
    bars = zigzag(IHS)
    i, _ = first_signal(bars)
    bars[i] = dict(bars[i], close=bars[i]["close"] + 20, high=bars[i]["high"] + 20)
    assert all(s is None for s in pattern_signals(bars[: i + 1]))


def pattern_stream(**changes):
    return StreamConfig(instance="cp_eurusd", tv_symbol="OANDA:EURUSD", timeframe="60", strategy="patterns",
                        risk_percent=0.5, history_bars=3000, **changes)


def eurusd_bars(env):
    """IHS scaled to EURUSD, ending with the breakout candle as the newest CLOSED 1H candle."""
    base = math.floor(env.now[0] / H1) * H1
    env.now[0] = base + 5
    raw = zigzag(IHS)
    i, _ = first_signal(raw)
    count = i + 1
    bars = zigzag(IHS, t0=base - count * H1, scale=0.001, shift=1.1 - 0.107)[:count]
    return bars, base


def run_engine(env, bars, base):
    env.broker.bars["EURUSD"] = bars + [dict(bars[-1], time=base)]  # plus the forming candle
    env.worker.maintain()
    SignalEngine(env.settings, env.db, env.broker, env.mapper, mode="trade", streams=[pattern_stream()]).poll(env.clock())


def capital(env, cap, min_lot_risk):
    env.settings = env.settings.model_copy(update=dict(risk_capital=cap, min_lot_max_risk_percent=min_lot_risk))
    env.worker.settings = env.settings
    env.worker.executor.settings = env.settings
    env.worker.executor.risk.settings = env.settings


def test_engine_trades_pattern_with_pattern_stop_and_target(env):
    bars, base = eurusd_bars(env)
    run_engine(env, bars, base)
    events = env.db.status()["recent_events"]
    assert [(e["event_type"], e["status"]) for e in events] == [("entry", "QUEUED")]
    env.worker.tick()
    record = env.db.open_positions()[0]
    assert record["instance"] == "cp_eurusd" and record["side"] == "LONG"
    live = env.broker.live[0]
    assert live.sl == pytest.approx(1.10002 - record["stop_distance"], abs=1e-5)
    assert record["target_distance"] == pytest.approx(0.0116, abs=2e-5)
    with env.db.connect() as db:
        details = [r[0] for r in db.execute("SELECT details_json FROM audit WHERE action='engine_signal_queued'")]
    assert "Inverted Head and Shoulders" in details[0]


def test_time_exit_after_150_bars(env):
    bars, base = eurusd_bars(env)
    run_engine(env, bars, base)
    env.worker.tick()
    assert env.db.open_positions()
    flat = [dict(time=0, open=1.1, high=1.1003, low=1.0997, close=1.1) for _ in range(150)]

    def after(n):
        end = base + n * H1
        env.now[0] = end + 5
        later = [dict(b, time=base + k * H1) for k, b in enumerate(flat[:n])]
        env.broker.bars["EURUSD"] = bars + later + [dict(flat[0], time=end)]
        env.worker.maintain()
        SignalEngine(env.settings, env.db, env.broker, env.mapper, mode="trade",
                     streams=[pattern_stream()]).poll(env.clock())
        return env.db.status()["recent_events"][0]["event_type"]

    assert after(149) == "entry"  # still holding
    assert after(150) == "date_end"
    env.worker.tick()
    assert env.db.open_positions() == [] and env.broker.live == []


def test_small_capital_skips_or_uses_minimum_lot(env):
    # $1000 capital, 0.5% = $5, but 0.01 lot risks ~$8 on this stop.
    capital(env, 1000, 0)
    bars, base = eurusd_bars(env)
    run_engine(env, bars, base)
    env.worker.tick()
    assert env.db.status()["recent_events"][0]["error"] == "risk_budget_below_minimum_lot"
    assert env.broker.live == []


def test_minimum_lot_allowed_within_cap_and_sized_from_capital(env):
    capital(env, 1000, 1.0)  # min lot may risk up to 1% of $1000 = $10
    bars, base = eurusd_bars(env)
    run_engine(env, bars, base)
    env.worker.tick()
    assert env.broker.live and env.broker.live[0].volume == 0.01
    record = env.db.open_positions()[0]
    assert 5 < record["risk_budget"] <= 10  # actual min-lot risk, not 0.5% of the $10,000 account


def test_capital_follows_bot_profit_and_loss(env):
    from app.trading.risk_manager import bot_capital

    capital(env, 1000, 0)
    assert bot_capital(env.db, env.settings, 10000) == 1000
    assert bot_capital(env.db, env.settings, 10050) == 1050  # bot made $50
    assert bot_capital(env.db, env.settings, 9900) == 900
    env.settings = env.settings.model_copy(update=dict(risk_capital=2000))
    assert bot_capital(env.db, env.settings, 9900) == 2000  # new capital resets the baseline
    env.settings = env.settings.model_copy(update=dict(risk_capital=None))
    assert bot_capital(env.db, env.settings, 9900) == 9900


def test_symbol_min_lot_cap_overrides_the_global_cap(env):
    capital(env, 1000, 0)  # global: never use the minimum lot above the risk budget
    rule = env.mapper.rules["OANDA:EURUSD"]
    env.mapper.rules["OANDA:EURUSD"] = rule.model_copy(update=dict(min_lot_max_risk_percent=1.0))
    bars, base = eurusd_bars(env)
    run_engine(env, bars, base)
    env.worker.tick()
    assert env.broker.live and env.broker.live[0].volume == 0.01  # allowed for this symbol only
    assert 5 < env.db.open_positions()[0]["risk_budget"] <= 10
