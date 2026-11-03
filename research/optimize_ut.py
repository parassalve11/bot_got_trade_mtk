"""Walk-forward grid search of the UT engine on 1 year of MT5 metal candles.

Train: first ~9 months. Test: last ~3 months (never used for selection).
Selection: best *neighbourhood-averaged* train score (robustness), train net R > 0.
Signals come from app.signals.ut_engine (the exact live maths); the replay is vectorised.
Usage: optimize.py DATA_DIR OUT_JSON
"""
import itertools
import json
import math
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, ".")
from app.signals.ut_engine import atr, ut_stops  # noqa: E402

DATA, OUT = sys.argv[1], sys.argv[2]
SPLIT = datetime(2026, 8, 3, tzinfo=timezone.utc).timestamp()
START = datetime(2025, 11, 3, tzinfo=timezone.utc).timestamp()
COST = {"XAUUSD": 0.30, "XAGUSD": 0.030}  # Round-trip spread + slippage per unit of price
GRID = dict(
    sens=[1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.4, 8.0],
    atr_len=[1, 2, 3, 5, 10],
    stop_atr=[1.0, 1.5, 2.0, 2.5, 3.0],
    rr=[1.0, 1.5, 2.0, 2.5, 3.0],
    opp=["Close only", "Close + reverse"],
    session=["all", "07-20"],
)
TFS = ["15", "30", "60"]
TF_SECONDS = {"15": 900, "30": 1800, "60": 3600}


def load(sym, tf):
    d = np.load(f"{DATA}/{sym}_{tf}.npz")
    return {k: d[k] for k in d.files}


def signals(b, sens, atr_len):
    closes = b["close"].tolist()
    stops = np.array(ut_stops(closes, atr(b["high"].tolist(), b["low"].tolist(), closes, atr_len), sens))
    c = b["close"]
    up = np.zeros(len(c), bool)
    dn = np.zeros(len(c), bool)
    up[1:] = (c[1:] > stops[1:]) & (c[:-1] <= stops[:-1])
    dn[1:] = (c[1:] < stops[1:]) & (c[:-1] >= stops[:-1])
    ready = np.zeros(len(c), bool)
    ready[1:] = ~np.isnan(stops[:-1])
    idx = np.flatnonzero((up | dn) & ready)
    return idx, np.where(up[idx], 1, -1)


def first_exit(b, side, fill, sl, tp):
    n = len(b["close"])
    lo, hi = b["low"], b["high"]
    step = 512
    i = fill
    while i < n:
        j = min(n, i + step)
        if side > 0:
            s_hit, t_hit = lo[i:j] <= sl, hi[i:j] >= tp
        else:
            s_hit, t_hit = hi[i:j] >= sl, lo[i:j] <= tp
        any_hit = s_hit | t_hit
        if any_hit.any():
            k = int(np.argmax(any_hit))
            return i + k, (sl if s_hit[k] else tp), ("SL" if s_hit[k] else "TP")
        i = j
        step *= 4
    return None, None, None


def simulate(b, sig_idx, sig_side, risk_atr, tick, cost, stop_atr, rr, opp, session_ok):
    n = len(b["close"])
    trades, pos = [], None

    def book(p, exit_idx, price, why):
        r = ((price - p["entry"]) * p["side"] - cost) / p["dist"]
        trades.append((b["time"][p["fill"]], r, why))

    for i, side in zip(sig_idx.tolist(), sig_side.tolist()):
        if b["time"][i] < START or i + 1 >= n:
            continue
        if pos and pos["exit"] is not None and pos["exit"] <= i:
            book(pos, pos["exit"], pos["exit_price"], pos["why"])
            pos = None
        allowed = session_ok[i]
        if pos and pos["side"] == side:
            continue
        if pos:
            book(pos, i + 1, b["open"][i + 1], "OPP")
            pos = None
            if opp != "Close + reverse":
                continue
        if not allowed or not risk_atr[i] > 0:
            continue
        loss_ticks = max(1, math.ceil(risk_atr[i] * stop_atr / tick - 1e-9))
        tp_ticks = max(1, math.ceil(loss_ticks * rr - 1e-9))
        entry = b["open"][i + 1]
        sl = entry - side * loss_ticks * tick
        tp = entry + side * tp_ticks * tick
        e, price, why = first_exit(b, side, i + 1, sl, tp)
        pos = dict(side=side, fill=i + 1, entry=entry, dist=loss_ticks * tick, exit=e, exit_price=price, why=why)
    if pos and pos["exit"] is not None:
        book(pos, pos["exit"], pos["exit_price"], pos["why"])
    return trades


def stats(rs):
    if not rs:
        return dict(n=0, wr=0, net=0, pf=0, exp=0, dd=0, score=-99)
    a = np.array(rs)
    wins, losses = a[a > 0].sum(), -a[a <= 0].sum()
    eq = np.cumsum(a)
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max())
    exp = float(a.mean())
    # t-stat-like score: rewards expectancy that is consistent over many trades.
    score = exp / (a.std() + 1e-9) * math.sqrt(len(a))
    return dict(n=len(a), wr=float((a > 0).mean()), net=float(a.sum()), pf=float(wins / losses) if losses else 99,
                exp=exp, dd=dd, score=float(score))


results = []
for sym in ("XAUUSD", "XAGUSD"):
    for tf in TFS:
        b = load(sym, tf)
        tick = float(b["tick"])
        hours = ((b["time"] + TF_SECONDS[tf]) % 86400) / 3600  # candle close hour UTC
        sessions = {"all": np.ones(len(hours), bool), "07-20": (hours >= 7) & (hours <= 20)}
        risk_atr = np.array(atr(b["high"].tolist(), b["low"].tolist(), b["close"].tolist(), 14))
        for sens, atr_len in itertools.product(GRID["sens"], GRID["atr_len"]):
            idx, sides = signals(b, sens, atr_len)
            for stop_atr, rr, opp, sess in itertools.product(GRID["stop_atr"], GRID["rr"], GRID["opp"], GRID["session"]):
                trades = simulate(b, idx, sides, risk_atr, tick, COST[sym], stop_atr, rr, opp, sessions[sess])
                train = [r for t, r, _ in trades if t < SPLIT]
                test = [r for t, r, _ in trades if t >= SPLIT]
                results.append(dict(sym=sym, tf=tf, sens=sens, atr_len=atr_len, stop_atr=stop_atr, rr=rr, opp=opp,
                                    session=sess, train=stats(train), test=stats(test), all=stats(train + test)))
        print("done", sym, tf, flush=True)

# Robustness: average train score over grid neighbours (±1 step in each numeric dimension).
keyed = {(r["sym"], r["tf"], r["opp"], r["session"], r["sens"], r["atr_len"], r["stop_atr"], r["rr"]): r for r in results}
pos = {k: {v: i for i, v in enumerate(GRID[k])} for k in ("sens", "atr_len", "stop_atr", "rr")}
for r in results:
    vals = []
    for d in itertools.product((-1, 0, 1), repeat=4):
        coords = []
        for dim, delta in zip(("sens", "atr_len", "stop_atr", "rr"), d):
            j = pos[dim][r[dim]] + delta
            if not 0 <= j < len(GRID[dim]):
                break
            coords.append(GRID[dim][j])
        else:
            n = keyed.get((r["sym"], r["tf"], r["opp"], r["session"], *coords))
            if n:
                vals.append(n["train"]["score"])
    r["robust"] = float(np.mean(vals))
json.dump(results, open(OUT, "w"))
print("saved", len(results))
