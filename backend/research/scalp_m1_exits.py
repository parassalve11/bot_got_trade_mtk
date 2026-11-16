r"""Re-check Scalping Patterns exits on 1-minute candles (fairer than the Pine rule "stop first
when one candle touches both stop and target"). Entries come from the M2/M3/M5/M15 run; SL, TP1
(half + breakeven), TP2 and the time stop are then replayed on M1 candles. Same costs as
research/backtest_scalping.py.

Usage: .venv\Scripts\python.exe research\scalp_m1_exits.py research\data_intraday
"""
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.signals.scalping import ScalpSettings, scalp_trades  # noqa: E402

FXM = {"XAUUSD", "XAGUSD", "EURUSD"}
DATA = Path(sys.argv[1])


def load(path):
    z = np.load(path)
    return z, [dict(time=float(t), open=float(o), high=float(h), low=float(lo), close=float(c), volume=float(v))
               for t, o, h, lo, c, v in zip(z["time"], z["open"], z["high"], z["low"], z["close"], z["volume"])]


def run(path):
    sym, tf = path.stem.rsplit("_", 1)
    tf = int(tf)
    z, bars = load(path)
    m1 = np.load(DATA / f"{sym}_1.npz")
    mt, mo, mh, ml, mc = m1["time"], m1["open"], m1["high"], m1["low"], m1["close"]
    spread = z["spread"] * float(z["point"])
    med = float(np.median(spread))
    cfg = ScalpSettings()
    ts = max(3, int(np.floor(cfg.time_stop_min / tf + 0.5)))
    days = sorted({int(b["time"] // 86400) for b in bars})
    split = days[int(len(days) * 2 / 3)] * 86400
    pine, m1r = dict(pick=0.0, check=0.0, n=0), dict(pick=0.0, check=0.0, n=0)
    for t in scalp_trades(bars, tf, cfg):
        start = t.time + tf * 60
        if start < mt[0]:
            continue
        sp = float(spread[t.bar])
        if med > 0 and sp > 5 * med:
            continue
        cost = max(sp, med, 0.0 if sym in FXM else 0.0002 * t.entry) / t.risk
        d = 1 if t.side == "LONG" else -1
        slp, t1 = t.sl, False
        j = int(np.searchsorted(mt, start))
        res = None
        while j < len(mt):
            o, h, lo, c = mo[j], mh[j], ml[j], mc[j]
            k = int((mt[j] + 60 - start) // (tf * 60))  # finished tf-candles after entry when this M1 closes
            if (lo <= slp if d == 1 else h >= slp):
                fill = o if (o < slp if d == 1 else o > slp) else slp
                ex = d * (fill - t.entry) / t.risk
                res = 0.5 * cfg.tp1_r + 0.5 * ex if t1 else ex
                break
            if not t1 and (h >= t.tp1 if d == 1 else lo <= t.tp1):
                t1, slp = True, t.entry
            if (h >= t.tp2 if d == 1 else lo <= t.tp2):
                ex = d * (t.tp2 - t.entry) / t.risk
                res = 0.5 * cfg.tp1_r + 0.5 * ex if t1 else ex
                break
            if (mt[j] + 60 - start) % (tf * 60) == 0 and ((not t1 and k >= ts) or k >= 4 * ts):
                ex = d * (c - t.entry) / t.risk
                res = 0.5 * cfg.tp1_r + 0.5 * ex if t1 else ex
                break
            j += 1
        if res is None:
            continue
        key = "check" if t.time >= split else "pick"
        pine[key] += t.r - cost
        m1r[key] += res - cost
        pine["n"] += 1
        m1r["n"] += 1
    return sym, tf, pine, m1r


if __name__ == "__main__":
    files = [f for f in sorted(DATA.glob("*_*.npz")) if not f.stem.endswith("_1")]
    with Pool() as pool:
        res = pool.map(run, files)
    print("net R after costs, default settings.  Pine exits (stop first) vs exits replayed on 1-minute candles")
    print(f"{'symbol':7} {'tf':>3} {'trades':>6} | {'Pine pick':>9} {'check':>7} | {'M1 pick':>8} {'check':>7}")
    tot = {}
    for sym, tf, p, m in sorted(res, key=lambda r: -(r[3]["pick"] + r[3]["check"])):
        print(f"{sym:7} {tf:3} {m['n']:6} | {p['pick']:+9.1f} {p['check']:+7.1f} | {m['pick']:+8.1f} {m['check']:+7.1f}")
        g = "stocks" if sym not in FXM else "fx/metals"
        a = tot.setdefault((g, tf), [0, 0.0, 0.0, 0])
        a[0] += m["n"]
        a[1] += p["pick"] + p["check"]
        a[2] += m["pick"] + m["check"]
        a[3] += 1 if (m["pick"] > 0 and m["check"] > 0) else 0
    print("\nTOTALS  group, tf: trades | Pine net R | M1-exit net R | symbols positive in both periods")
    for (g, tf), a in sorted(tot.items()):
        print(f"{g:9} M{tf:<3} {a[0]:6} | {a[1]:+8.1f} | {a[2]:+8.1f} ({a[2] / max(1, a[0]):+.3f} R/trade) | {a[3]}")
