"""Search for HIGH WIN-RATE settings that are still profitable, with honest walk-forward.

Adds to research/optimize_ut.py: smaller take-profits, wider stops, "Ignore" opposite
signals, and trend filters (EMA 200 on the chart timeframe, or the Pine HTF filter:
previous COMPLETED 4H candle close vs its UT line, same UT settings).
Train 3 Nov 2025 - 2 Aug 2026; test 3 Aug 2026 onwards (never used for selection).
Usage: optimize_winrate.py DATA_DIR OUT_JSON SYMBOL TF [TF ...]
"""
import itertools
import json
import sys

import numpy as np

DATA, OUT, SYMBOL, TFS = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
sys.argv = [sys.argv[0], DATA, OUT]  # optimize_ut reads its own argv on import
sys.path.insert(0, "research")
import optimize_ut as base  # noqa: E402

GRID = dict(
    sens=[1.0, 2.0, 3.0, 4.0, 6.4],
    atr_len=[1, 2, 5, 10],
    stop_atr=[1.5, 2.0, 3.0, 4.0],
    rr=[0.3, 0.5, 0.75, 1.0, 1.5],
    opp=["Close only", "Ignore"],
    trend=["none", "ema200", "htf240"],
)


def ema(values, length):
    alpha = 2 / (length + 1)
    out = np.empty(len(values))
    out[:] = np.nan
    if len(values) >= length:
        out[length - 1] = values[:length].mean()  # Pine ta.ema seeds with an SMA
        for i in range(length, len(values)):
            out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def htf_direction(b, htf, sens, atr_len, tf_seconds):
    """+1/-1/0 per chart candle from the last 4H candle COMPLETED by that candle's close."""
    closes = htf["close"].tolist()
    stops = np.array(base.ut_stops(closes, base.atr(htf["high"].tolist(), htf["low"].tolist(), closes, atr_len), sens))
    hdir = np.where(htf["close"] > stops, 1, np.where(htf["close"] < stops, -1, 0))
    hdir[np.isnan(stops)] = 0
    htf_close_times = htf["time"] + 14400
    chart_close = b["time"] + tf_seconds
    # Pine: request.security(..., [close[1], line[1]], lookahead_on) = the HTF candle BEFORE the one
    # containing this chart candle. A 4H candle closing at the same moment is not used yet.
    k = np.searchsorted(htf_close_times, chart_close, side="left") - 1
    out = np.zeros(len(b["time"]), int)
    valid = k >= 0
    out[valid] = hdir[k[valid]]
    return out


results = []
htf = base.load(SYMBOL, "240")
for tf in TFS:
    b = base.load(SYMBOL, tf)
    tick = float(b["tick"])
    tf_sec = base.TF_SECONDS[tf]
    risk_atr = np.array(base.atr(b["high"].tolist(), b["low"].tolist(), b["close"].tolist(), 14))
    ema200 = ema(b["close"], 200)
    ema_dir = np.where(b["close"] > ema200, 1, np.where(b["close"] < ema200, -1, 0))
    for sens, atr_len in itertools.product(GRID["sens"], GRID["atr_len"]):
        idx, sides = base.signals(b, sens, atr_len)
        directions = {"none": None, "ema200": ema_dir, "htf240": htf_direction(b, htf, sens, atr_len, tf_sec)}
        for trend, direction in directions.items():
            allowed = np.ones(len(b["close"]), bool)
            if direction is not None:
                allowed[idx] = direction[idx] == sides  # entry only with the trend
            for stop_atr, rr, opp in itertools.product(GRID["stop_atr"], GRID["rr"], GRID["opp"]):
                args = (b, idx, sides, risk_atr, tick, base.COST[SYMBOL], stop_atr, rr, opp, allowed)
                phase = [base.simulate(*args, skip=k) for k in (0, 1)]
                train = [base.stats([x for x in p if x[0] < base.SPLIT]) for p in phase]
                test = [base.stats([x for x in p if x[0] >= base.SPLIT]) for p in phase]
                results.append(dict(sym=SYMBOL, tf=tf, sens=sens, atr_len=atr_len, stop_atr=stop_atr, rr=rr,
                                    opp=opp, trend=trend, train=base.worse(*train), test=test[0],
                                    test_other_phase=test[1]))
    print("done", SYMBOL, tf, flush=True)
json.dump(results, open(OUT, "w"))
print("saved", len(results))
