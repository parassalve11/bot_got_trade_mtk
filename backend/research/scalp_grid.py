r"""Grid search Scalping Patterns settings for a high win rate WITHOUT losing money.

Usage: .venv\Scripts\python.exe research\scalp_grid.py research\data_intraday 3,5,15 out.json
Every variant is run on every symbol/timeframe; results are kept per symbol, split into the
pick period (first 4 months: used to choose) and check period (last 2 months: unseen).
Win = result > 0. Net = after costs (same as research/backtest_scalping.py).
"""
import itertools
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.signals.scalping import ScalpSettings, scalp_trades  # noqa: E402

FXM = {"XAUUSD", "XAGUSD", "EURUSD"}
PATSETS = {
    "all": {},
    "no Sweep/MicroPB": dict(use_swp=False, use_mpb=False),
    "ORB+Flag+IB+Double": dict(use_swp=False, use_mpb=False, use_vwp=False),
}


def variants():
    for tp, slm, trend, ts, pats, window in itertools.product(
            [0.3, 0.5], [1.0, 1.5, 2.0], [0, 200], [15, 45], PATSETS, ["all day", "first 2h"]):
        kw = dict(single_tp=True, tp1_r=tp, sl_mult=slm, trend_len=trend, time_stop_min=ts, **PATSETS[pats])
        if window == "first 2h":
            kw["end_min"] = 120
        yield f"TP {tp}R | SL x{slm} | trend {trend or 'off'} | time {ts}m | {pats} | {window}", kw


def run(path):
    sym, tf = path.stem.rsplit("_", 1)
    z = np.load(path)
    bars = [dict(time=float(t), open=float(o), high=float(h), low=float(lo), close=float(c), volume=float(v))
            for t, o, h, lo, c, v in zip(z["time"], z["open"], z["high"], z["low"], z["close"], z["volume"])]
    spread = z["spread"] * float(z["point"])
    med = float(np.median(spread))
    days = sorted({int(b["time"] // 86400) for b in bars})
    split = days[int(len(days) * 2 / 3)] * 86400
    out = {}
    for name, kw in variants():
        if sym in FXM and kw.get("end_min"):
            continue  # no "session open" on 24h markets
        acc = dict(pn=0, pw=0, pr=0.0, cn=0, cw=0, cr=0.0)
        for t in scalp_trades(bars, int(tf), ScalpSettings(**kw)):
            sp = float(spread[t.bar])
            if med > 0 and sp > 5 * med:
                continue
            net = t.r - max(sp, med, 0.0 if sym in FXM else 0.0002 * t.entry) / t.risk
            k = "c" if t.time >= split else "p"
            acc[k + "n"] += 1
            acc[k + "w"] += net > 0
            acc[k + "r"] += net
        out[name] = acc
    return f"{sym}|{tf}", out


if __name__ == "__main__":
    tfs = sys.argv[2].split(",")
    files = [f for f in sorted(Path(sys.argv[1]).glob("*_*.npz")) if f.stem.rsplit("_", 1)[1] in tfs]
    with Pool(2, maxtasksperchild=1) as pool:
        res = dict(pool.map(run, files))
    Path(sys.argv[3]).write_text(json.dumps(res))
    print("saved", len(res))
