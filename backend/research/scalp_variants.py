r"""Try Scalping Patterns setting variants on all exported symbols / timeframes (same costs as
research/backtest_scalping.py). Prints net R per timeframe for the 20 stocks, split pick / check.

Usage: .venv\Scripts\python.exe research\scalp_variants.py research\data_intraday
"""
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.signals.scalping import ScalpSettings, scalp_trades  # noqa: E402

FXM = {"XAUUSD", "XAGUSD", "EURUSD"}
ONLY = lambda keep: {k: (k in keep) for k in ["use_orb", "use_vwp", "use_mpb", "use_flag", "use_ib", "use_swp", "use_dbl"]}  # noqa: E731
VARIANTS = {
    "default (More trades)": {},
    "time stop 60 min": dict(time_stop_min=60),
    "time stop 120 min": dict(time_stop_min=120),
    "no breakeven": dict(be_after_tp1=False),
    "TP1 0.5R": dict(tp1_r=0.5),
    "TP1 1.5R, max 4R": dict(tp1_r=1.5, max_tp_r=4.0),
    "ADX >= 25": dict(adx_min=25),
    "only ORB + VWAP": ONLY({"use_orb", "use_vwp"}),
    "only Sweep + Double": ONLY({"use_swp", "use_dbl"}),
    "only Flag + Inside Bar": ONLY({"use_flag", "use_ib"}),
    "Long only": dict(trade_dir="Long only"),
    "Short only": dict(trade_dir="Short only"),
}


def run(args):
    path, name, kw = args
    sym, tf = path.stem.rsplit("_", 1)
    z = np.load(path)
    point = float(z["point"])
    bars = [dict(time=float(t), open=float(o), high=float(h), low=float(lo), close=float(c), volume=float(v))
            for t, o, h, lo, c, v in zip(z["time"], z["open"], z["high"], z["low"], z["close"], z["volume"])]
    spread = z["spread"] * point
    med = float(np.median(spread))
    days = sorted({int(b["time"] // 86400) for b in bars})
    split = days[int(len(days) * 2 / 3)] * 86400
    out = dict(pick=[0.0, 0], check=[0.0, 0], gross=0.0)
    for t in scalp_trades(bars, int(tf), ScalpSettings(**kw)):
        sp = float(spread[t.bar])
        if med > 0 and sp > 5 * med:
            continue
        cost = max(sp, med, 0.0 if sym in FXM else 0.0002 * t.entry) / t.risk
        part = out["check" if t.time >= split else "pick"]
        part[0] += t.r - cost
        part[1] += 1
        out["gross"] += t.r
    return name, sym, int(tf), out


if __name__ == "__main__":
    files = sorted(Path(sys.argv[1]).glob("*_*.npz"))
    jobs = [(f, name, kw) for name, kw in VARIANTS.items() for f in files]
    with Pool() as pool:
        res = pool.map(run, jobs, chunksize=4)
    tfs = [1, 2, 3, 5, 15]
    for group, keep in [("20 STOCKS", lambda s: s not in FXM), ("GOLD / SILVER / EURUSD", lambda s: s in FXM)]:
        print(f"\n### {group}: net R after costs, per timeframe  (pick 4 months | check 2 months)   [symbols positive in BOTH]")
        print(f"{'variant':24}" + "".join(f"{'M' + str(t):>22}" for t in tfs))
        for name in VARIANTS:
            line = f"{name:24}"
            for tf in tfs:
                rows = [o for n, s, t, o in res if n == name and t == tf and keep(s)]
                p = sum(o["pick"][0] for o in rows)
                c = sum(o["check"][0] for o in rows)
                both = sum(1 for o in rows if o["pick"][0] > 0 and o["check"][0] > 0)
                line += f"{p:+8.0f} |{c:+7.0f} [{both:2}]  "
            print(line)
