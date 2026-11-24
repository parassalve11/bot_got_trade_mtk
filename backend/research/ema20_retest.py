r"""Backtest pine/ema20_retest_scalp.pine (EMA 20 breakout & retest) on exported MT5 candles.

Usage (from backend/):
    .venv\Scripts\python.exe research\ema20_retest.py research\data_intraday [tf ...]

Same rules as the Pine strategy:
  BUY: green candle opens below and closes above EMA20 (previous close <= EMA); within the next 2
  candles a red candle that does not close below the EMA; buy stop 1 tick above that red candle's
  high, valid for 3 more candles; any close below the EMA before the entry cancels it.
  Exit: target = entry + 3 x (entry - EMA) (intrabar), or a candle closing below the EMA.
  Scalping day rules: setups reset at a new day, open trades close on the day's last candle.
  SELL is the mirror.
Costs once per trade: max(candle spread, median spread), stocks at least 0.02% of price; trades
whose candle spread is > 5x the median are skipped. Intrabar ambiguity is resolved against us.
Split: first 2/3 of the days = "first 4 months", last 1/3 = "last 2 months".
"""

import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.signals.scalping import _ema, _rma  # noqa: E402  (Pine-identical EMA)

FX_METALS = {"XAUUSD", "XAGUSD", "EURUSD"}
VARIANTS = {
    "video (1:3, close stop)": dict(rr=3.0, hard=False),
    "1:3 + hard stop at EMA": dict(rr=3.0, hard=True),
    "trail with EMA": dict(rr=0.0, hard=False),
    "1:2, close stop": dict(rr=2.0, hard=False),
    "1:1, close stop": dict(rr=1.0, hard=False),
    "1:3, close stop, min risk 0.5 ATR": dict(rr=3.0, hard=False, minr=0.5),
    "1:3, hard stop, min risk 0.5 ATR": dict(rr=3.0, hard=True, minr=0.5),
    "1:2, hard stop, min risk 0.5 ATR": dict(rr=2.0, hard=True, minr=0.5),
    "1:1, hard stop, min risk 0.5 ATR": dict(rr=1.0, hard=True, minr=0.5),
    "1:3, hard stop, min risk 1 ATR": dict(rr=3.0, hard=True, minr=1.0),
}


def trades(O, H, L, C, E, tick, rr=3.0, hard=False, win=2, wait=3, minr=0.0, A=None, T=None):
    n = len(C)
    D = (np.asarray(T) // 86400).astype(np.int64)
    out = []
    lSt = sSt = 0
    lBar = sBar = 0
    lTrig = sTrig = 0.0
    pend = None          # (dir, entry, target, stop, risk) placed at the previous close
    pos = None           # dict
    for i in range(1, n):
        o, h, lo, c, e = O[i], H[i], L[i], C[i], E[i]
        entered_now = False
        if D[i] != D[i - 1]:            # new day / session: old setups and orders are dropped
            lSt = sSt = 0
            pend = None
        last_bar = i == n - 1 or D[i + 1] != D[i]
        if pos is None and pend:
            for d, en, tg, st, rk in pend:
                if (d == 1 and h >= en) or (d == -1 and lo <= en):
                    fill = max(o, en) if d == 1 else min(o, en)
                    if (tg is not None and d * (tg - fill) <= 0) or (st is not None and d * (fill - st) <= 0):
                        break                   # gapped past the target / stop: order not taken
                    pos = dict(d=d, bar=i, fill=fill, tg=tg, st=st, risk=rk)
                    entered_now = True
                    break
        if pos is not None:
            d, tg, st = pos["d"], pos["tg"], pos["st"]
            ex = None
            stop_hit = st is not None and ((d == 1 and lo <= st) or (d == -1 and h >= st))
            tgt_hit = tg is not None and ((d == 1 and h >= tg) or (d == -1 and lo <= tg))
            if entered_now and o != pos["fill"]:
                # filled inside the candle: assume the usual path (green O-L-H-C, red O-H-L-C)
                with_trade = (c >= o) if d == 1 else (c <= o)   # candle moves our way after the low/high
                if with_trade:   # extreme against us came BEFORE the fill; after it only the close matters
                    stop_hit = st is not None and ((d == 1 and c <= st) or (d == -1 and c >= st)) and not tgt_hit
                # else: fill, then our-side extreme (target?), then the other extreme (stop?)
            if stop_hit:                                   # stop first when both touched (conservative)
                gap = (d == 1 and o <= st) or (d == -1 and o >= st)
                ex = (o if gap and not entered_now else st, "hard stop")
            elif tgt_hit:
                gap = (d == 1 and o >= tg) or (d == -1 and o <= tg)
                ex = (o if gap and not entered_now else tg, "target")
            elif (d == 1 and c < e) or (d == -1 and c > e):
                ex = (c, "close across EMA")
            elif last_bar:
                ex = (c, "end of day")
            if ex:
                pos.update(exit=ex[0], reason=ex[1], r=d * (ex[0] - pos["fill"]) / pos["risk"], xbar=i)
                out.append(pos)
                pos = None
        # setup state on this closed candle
        green, red = c > o, c < o
        upB = green and c > e and o < e and C[i - 1] <= E[i - 1]
        dnB = red and c < e and o > e and C[i - 1] >= E[i - 1]
        if lSt:
            age = i - lBar
            if c < e:
                lSt = 0
            else:
                if red and age <= win:
                    lTrig, lSt = h, 2
                if lSt == 1 and age >= win:
                    lSt = 0
                if lSt == 2 and age > win + wait:
                    lSt = 0
        if upB and lSt == 0:
            lSt, lBar = 1, i
        if sSt:
            age = i - sBar
            if c > e:
                sSt = 0
            else:
                if green and age <= win:
                    sTrig, sSt = lo, 2
                if sSt == 1 and age >= win:
                    sSt = 0
                if sSt == 2 and age > win + wait:
                    sSt = 0
        if dnB and sSt == 0:
            sSt, sBar = 1, i
        pend = None
        if pos is not None:
            lSt = sSt = 0
        elif not last_bar:
            pend = []
            if lSt == 2:
                en = lTrig + tick
                rk = max(en - e, minr * A[i]) if minr else en - e
                if rk > 0:
                    pend.append((1, en, en + rr * rk if rr else None, en - rk if hard else None, rk))
            if sSt == 2:
                en = sTrig - tick
                rk = max(e - en, minr * A[i]) if minr else e - en
                if rk > 0:
                    pend.append((-1, en, en - rr * rk if rr else None, en + rk if hard else None, rk))
    return out


def run(path):
    sym, tf = path.stem.rsplit("_", 1)
    z = np.load(path)
    O, H, L, C, T = (np.asarray(z[k], float) for k in ("open", "high", "low", "close", "time"))
    point = float(z["point"])
    spread = z["spread"] * point
    med = float(np.median(spread))
    E = np.array(_ema(list(C), 20), float)
    E[np.isnan(E)] = C[np.isnan(E)]
    TR = np.maximum(H - L, np.maximum(abs(H - np.r_[C[0], C[:-1]]), abs(L - np.r_[C[0], C[:-1]])))
    A = np.array(_rma(list(TR), 14), float)
    A[np.isnan(A)] = TR[np.isnan(A)]
    days = sorted({int(t // 86400) for t in T})
    split = days[int(len(days) * 2 / 3)] * 86400
    stock = sym not in FX_METALS
    res = {}
    for name, v in VARIANTS.items():
        rows = []
        for t in trades(O, H, L, C, E, point, A=A, T=T, **v):
            sp = float(spread[t["bar"]])
            if med > 0 and sp > 5 * med:
                continue
            cost = max(sp, med, 0.0002 * t["fill"] if stock else 0.0) / t["risk"]
            rows.append((t["d"], t["r"], t["r"] - cost, T[t["bar"]] >= split, t["reason"]))
        res[name] = rows
    return sym, int(tf), res


def st(rows):
    n = len(rows)
    if not n:
        return dict(n=0, win=0.0, net=0.0, avg=0.0, gross=0.0)
    net = sum(r[2] for r in rows)
    return dict(n=n, win=100 * sum(r[2] > 0 for r in rows) / n, net=net, avg=net / n, gross=sum(r[1] for r in rows))


if __name__ == "__main__":
    data = Path(sys.argv[1])
    tfs = [int(x) for x in sys.argv[2:]] or [5]
    files = [p for p in sorted(data.glob("*_*.npz")) if p.stem.rsplit("_", 1)[1].isdigit()
             and int(p.stem.rsplit("_", 1)[1]) in tfs]
    with Pool(2) as pool:
        out = pool.map(run, files)
    for tf in tfs:
        print(f"\n===== {tf}-minute charts =====")
        for name in VARIANTS:
            groups = {"20 stocks": [], "Gold/silver/EURUSD": []}
            per_sym = []
            for sym, t, res in out:
                if t != tf:
                    continue
                groups["Gold/silver/EURUSD" if sym in FX_METALS else "20 stocks"] += res[name]
                a, p, k = st(res[name]), st([r for r in res[name] if not r[3]]), st([r for r in res[name] if r[3]])
                per_sym.append((sym, a, p, k, st([r for r in res[name] if r[0] == 1]), st([r for r in res[name] if r[0] == -1])))
            print(f"\n-- {name}")
            for g, rows in groups.items():
                a, b, s = st(rows), st([r for r in rows if r[0] == 1]), st([r for r in rows if r[0] == -1])
                p, k = st([r for r in rows if not r[3]]), st([r for r in rows if r[3]])
                print(f"  {g:19} trades {a['n']:5}  win {a['win']:4.1f}%  avg {a['avg']:+.3f}R  net {a['net']:+7.1f}R"
                      f" (before costs {a['gross']:+7.1f}R) | BUY win {b['win']:4.1f}% {b['net']:+6.1f}R  SELL win {s['win']:4.1f}% {s['net']:+6.1f}R"
                      f" | first4m {p['net']:+6.1f}R  last2m {k['net']:+6.1f}R")
            if name in ("video (1:3, close stop)", "1:3, hard stop, min risk 0.5 ATR"):
                for sym, a, p, k, b, s in sorted(per_sym, key=lambda x: -x[1]["net"]):
                    print(f"     {sym:7} n {a['n']:4} win {a['win']:4.1f}% net {a['net']:+6.1f}R | BUY {b['win']:4.1f}% {b['net']:+5.1f}R"
                          f" SELL {s['win']:4.1f}% {s['net']:+5.1f}R | first4m {p['net']:+5.1f} last2m {k['net']:+5.1f}")
