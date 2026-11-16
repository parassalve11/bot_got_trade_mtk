r"""Backtest Scalping Patterns (pine/scalping_patterns.pine) on exported intraday MT5 candles.

Usage (from backend/, after research/export_intraday.py):
    .venv\Scripts\python.exe research\backtest_scalping.py research\data_intraday [mode] [fixed 1|0]

Runs every <SYMBOL>_<tf>.npz (tf = 1, 2, 3, 5, 15 minutes) through app/signals/scalping.py with the
indicator's own trade rules (TP1 half + breakeven + TP2 / time exit, R exactly as its dashboard).
Costs, paid once per trade and converted to R with the trade's stop distance:
  max(candle spread, the symbol's median spread), and for stocks at least 0.02% of price
  (MT5 history stores only the candle's minimum spread, 1 cent on stocks: too optimistic).
  A trade whose candle spread is > 5x the median is skipped (the bot's max-spread filter).
Split: first ~2/3 of the days = "pick" period, last ~1/3 = "check" (unseen) period.
Writes <data>/scalp_results.json.
"""

import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.signals.scalping import ScalpSettings, scalp_trades  # noqa: E402

data = Path(sys.argv[1])
MODE = sys.argv[2] if len(sys.argv) > 2 else "More trades"
FX_METALS = {"XAUUSD", "XAGUSD", "EURUSD"}
FIXED = (sys.argv[3] if len(sys.argv) > 3 else "1") == "1"


def run(path: Path):
    sym, tf = path.stem.rsplit("_", 1)
    tf = int(tf)
    z = np.load(path)
    point = float(z["point"])
    bars = [dict(time=float(t), open=float(o), high=float(h), low=float(lo), close=float(c), volume=float(v))
            for t, o, h, lo, c, v in zip(z["time"], z["open"], z["high"], z["low"], z["close"], z["volume"])]
    spread = z["spread"] * point
    med = float(np.median(spread))
    stock = sym not in FX_METALS
    t0 = time.perf_counter()
    trades = scalp_trades(bars, tf, ScalpSettings(mode=MODE, fixed=FIXED))
    days = sorted({int(b["time"] // 86400) for b in bars})
    split = days[int(len(days) * 2 / 3)] * 86400
    rows = []
    for t in trades:
        sp = float(spread[t.bar])
        if med > 0 and sp > 5 * med:
            continue
        price_cost = max(sp, med, 0.0002 * t.entry if stock else 0.0)
        cost = price_cost / t.risk if t.risk > 0 else 0.0
        rows.append(dict(time=t.time, side=t.side, pattern=t.pattern, r=t.r, net=t.r - cost, cost=cost,
                         reason=t.reason, tp1=t.tp1_hit, check=t.time >= split))
    return sym, tf, rows, time.perf_counter() - t0


def stats(rows):
    n = len(rows)
    w = sum(1 for r in rows if r["net"] > 0)
    return dict(n=n, win=100 * w / n if n else 0.0, gross=sum(r["r"] for r in rows), net=sum(r["net"] for r in rows),
                cost=sum(r["cost"] for r in rows) / n if n else 0.0)


if __name__ == "__main__":
    files = sorted(data.glob("*_*.npz"))
    with Pool() as pool:
        out = pool.map(run, files)
    res = {}
    for sym, tf, rows, secs in out:
        pick = [r for r in rows if not r["check"]]
        chk = [r for r in rows if r["check"]]
        pats = {}
        for r in rows:
            pats.setdefault(r["pattern"], []).append(r)
        res[f"{sym}|{tf}"] = dict(all=stats(rows), pick=stats(pick), check=stats(chk),
                                  long=stats([r for r in rows if r["side"] == "LONG"]),
                                  short=stats([r for r in rows if r["side"] == "SHORT"]),
                                  patterns={k: stats(v) for k, v in pats.items()})
    (data / f"scalp_results{'' if FIXED else '_orig'}_{MODE.replace(' ', '_')}.json").write_text(json.dumps(res, indent=1))
    print(f"mode {MODE}, fixed={FIXED}.  net R = after spread.  pick = first 4 months, check = last 2 (unseen)")
    print(f"{'symbol':7} {'tf':>3} | {'trades':>6} {'win%':>5} {'grossR':>7} {'netR':>7} {'cost/tr':>7} | "
          f"{'pick n':>6} {'netR':>6} | {'check n':>7} {'netR':>6}")
    for k, v in sorted(res.items(), key=lambda kv: -kv[1]["all"]["net"]):
        sym, tf = k.split("|")
        a, p, c = v["all"], v["pick"], v["check"]
        print(f"{sym:7} {tf:>3} | {a['n']:6} {a['win']:5.1f} {a['gross']:+7.1f} {a['net']:+7.1f} {a['cost']:7.3f} | "
              f"{p['n']:6} {p['net']:+6.1f} | {c['n']:7} {c['net']:+6.1f}")
