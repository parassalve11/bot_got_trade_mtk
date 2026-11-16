r"""Win rate of BUY and SELL signals per pattern and timeframe (fixed v2 rules, default settings).

Usage: .venv\Scripts\python.exe research\scalp_winrates.py research\data_intraday [mode]
Win = trade result > 0 as the Pine dashboard counts it (TP1 then breakeven = +0.5R = win).
"Net" = average R per trade after the same costs as research/backtest_scalping.py.
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.signals.scalping import ScalpSettings, scalp_trades  # noqa: E402

FXM = {"XAUUSD", "XAGUSD", "EURUSD"}
MODE = sys.argv[2] if len(sys.argv) > 2 else "More trades"


def run(path):
    sym, tf = path.stem.rsplit("_", 1)
    z = np.load(path)
    bars = [dict(time=float(t), open=float(o), high=float(h), low=float(lo), close=float(c), volume=float(v))
            for t, o, h, lo, c, v in zip(z["time"], z["open"], z["high"], z["low"], z["close"], z["volume"])]
    spread = z["spread"] * float(z["point"])
    med = float(np.median(spread))
    rows = []
    for t in scalp_trades(bars, int(tf), ScalpSettings(mode=MODE)):
        sp = float(spread[t.bar])
        if med > 0 and sp > 5 * med:
            continue
        cost = max(sp, med, 0.0 if sym in FXM else 0.0002 * t.entry) / t.risk
        rows.append((t.pattern, t.side, t.r, t.r - cost, t.reason))
    return sym, int(tf), rows


if __name__ == "__main__":
    with Pool() as pool:
        res = pool.map(run, sorted(Path(sys.argv[1]).glob("*_*.npz")))
    out = {}
    for sym, tf, rows in res:
        g = "Gold/Silver/EURUSD" if sym in FXM else "20 stocks"
        for pat, side, r, net, reason in rows:
            for key in [(g, tf, pat, side), (g, tf, "ALL", side), (g, tf, "ALL", "BOTH")]:
                a = out.setdefault(key, dict(n=0, w=0, gross=0.0, net=0.0, tp2=0, sl=0))
                a["n"] += 1
                a["w"] += r > 0
                a["gross"] += r
                a["net"] += net
                a["tp2"] += reason == "TP2 hit"
                a["sl"] += reason == "SL hit"
    Path(sys.argv[1], f"scalp_winrates_{MODE.replace(' ', '_')}.json").write_text(
        json.dumps({"|".join(map(str, k)): v for k, v in out.items()}, indent=1))
    pats = ["ORB", "VWAP Pullback", "Micro Pullback", "Flag", "Inside Bar", "Sweep", "Double Top/Bottom", "ALL"]
    for g in ["20 stocks", "Gold/Silver/EURUSD"]:
        for side in ["LONG", "SHORT"]:
            print(f"\n### {g} - {'BUY' if side == 'LONG' else 'SELL'} signals ({MODE}): win% / avg net R per trade (trades)")
            print(f"{'pattern':18}" + "".join(f"{'M' + str(t):>24}" for t in [1, 2, 3, 5, 15]))
            for p in pats:
                line = f"{p:18}"
                for tf in [1, 2, 3, 5, 15]:
                    a = out.get((g, tf, p, side))
                    line += f"{100 * a['w'] / a['n']:6.1f}% {a['net'] / a['n']:+6.2f}R ({a['n']:5})  " if a else f"{'-':>24}"
                print(line)
