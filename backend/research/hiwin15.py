r"""Search for a 15-minute strategy with >= 70% win rate that ALSO makes money after costs.

Usage (from backend/):  .venv\Scripts\python.exe research\hiwin15.py research\data_intraday [tf]

Strategy families (classic high-win-rate mean reversion, entry at the NEXT candle's open):
  rsi2 : Connors RSI(2). BUY when close > SMA200 and RSI(2) < th; exit on a close above SMA5.
  bb   : Bollinger(20, 2). BUY when close < lower band and close > SMA200; exit on a close above
         the middle band.
  vwap : BUY when close < session VWAP - k x stdev and close > SMA200; exit on a close above VWAP.
  SELL = mirror (below SMA200, overbought). Every trade has a hard stop of s x ATR(14) and a time
  stop of N candles. Stocks: no entries in the last 2 candles of the day, close at the day's last
  candle. Costs as in the other research scripts (spread, stocks >= 0.02% of price).
Selection uses only the first ~4 months ("pick"); the last ~2 months ("check") are reported unseen.
"""

import itertools
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

FX_METALS = {"XAUUSD", "XAGUSD", "EURUSD"}


def sma(x, n):
    c = np.cumsum(np.r_[0.0, x])
    out = np.full(len(x), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def rma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = x[:n].mean()
    for i in range(n, len(x)):
        out[i] = (x[i] + (n - 1) * out[i - 1]) / n
    return out


def rsi(c, n):
    d = np.diff(c, prepend=c[0])
    up, dn = rma(np.maximum(d, 0), n), rma(np.maximum(-d, 0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(dn == 0, 100.0, 100 - 100 / (1 + up / dn))


def prep(path):
    sym, tf = path.stem.rsplit("_", 1)
    z = np.load(path)
    O, H, L, C, V, T = (np.asarray(z[k], float) for k in ("open", "high", "low", "close", "volume", "time"))
    D = (T // 86400).astype(np.int64)
    TR = np.maximum(H - L, np.maximum(abs(H - np.r_[C[0], C[:-1]]), abs(L - np.r_[C[0], C[:-1]])))
    ind = dict(sma200=sma(C, 200), sma5=sma(C, 5), sma20=sma(C, 20), atr=rma(TR, 14), rsi2=rsi(C, 2))
    sd = np.sqrt(np.maximum(sma(C * C, 20) - sma(C, 20) ** 2, 0))
    ind["bbl"], ind["bbu"] = ind["sma20"] - 2 * sd, ind["sma20"] + 2 * sd
    # session VWAP and its stdev
    vw, vsd = np.empty(len(C)), np.empty(len(C))
    hlc = (H + L + C) / 3
    w = np.where(V > 0, V, 1.0)
    s1 = s2 = s3 = 0.0
    for i in range(len(C)):
        if i == 0 or D[i] != D[i - 1]:
            s1 = s2 = s3 = 0.0
        s1 += w[i]; s2 += w[i] * hlc[i]; s3 += w[i] * hlc[i] ** 2
        vw[i] = s2 / s1
        vsd[i] = np.sqrt(max(s3 / s1 - vw[i] ** 2, 0))
    ind["vwap"], ind["vsd"] = vw, vsd
    spread = z["spread"] * float(z["point"])
    days = sorted(set(D.tolist()))
    split = days[int(len(days) * 2 / 3)]
    return dict(sym=sym, tf=int(tf), O=O, H=H, L=L, C=C, D=D, ind=ind, spread=spread,
                med=float(np.median(spread)), stock=sym not in FX_METALS, split=split)


def signals(d, fam, p):
    I, C = d["ind"], d["C"]
    up, dn = C > I["sma200"], C < I["sma200"]
    if fam == "rsi2":
        L = up & (I["rsi2"] < p["th"]); S = dn & (I["rsi2"] > 100 - p["th"])
        xL = C > I["sma5"]; xS = C < I["sma5"]
    elif fam == "bb":
        L = up & (C < I["bbl"]); S = dn & (C > I["bbu"])
        xL = C > I["sma20"]; xS = C < I["sma20"]
    else:
        L = up & (C < I["vwap"] - p["th"] * I["vsd"]); S = dn & (C > I["vwap"] + p["th"] * I["vsd"])
        xL = C > I["vwap"]; xS = C < I["vwap"]
    return L, S, xL, xS


def backtest(d, fam, p):
    O, H, L_, C, D, A = d["O"], d["H"], d["L"], d["C"], d["D"], d["ind"]["atr"]
    Ls, Ss, xL, xS = signals(d, fam, p)
    n = len(C)
    rows = []
    i = 200
    stock = d["stock"]
    while i < n - 2:
        lastday = D[i + 2] != D[i] or D[i + 1] != D[i]
        dirn = 1 if (Ls[i] and p["dir"] != -1) else (-1 if (Ss[i] and p["dir"] != 1) else 0)
        if dirn == 0 or np.isnan(A[i]) or (stock and lastday):
            i += 1
            continue
        e = i + 1                       # fill at next open
        if D[e] != D[i]:
            i += 1
            continue
        fill = O[e]
        risk = p["stop"] * A[i]
        st = fill - dirn * risk
        xi, xp = None, None
        for j in range(e, min(n, e + p["tmax"])):
            if (dirn == 1 and L_[j] <= st) or (dirn == -1 and H[j] >= st):
                xi, xp = j, (O[j] if (dirn == 1 and O[j] < st) or (dirn == -1 and O[j] > st) else st)
                break
            if (dirn == 1 and xL[j]) or (dirn == -1 and xS[j]):
                xi, xp = j, C[j]; break
            if stock and (j == n - 1 or D[j + 1] != D[j]):
                xi, xp = j, C[j]; break
        if xi is None:
            xi = min(n - 1, e + p["tmax"] - 1); xp = C[xi]
        sp = float(d["spread"][e])
        if not (d["med"] > 0 and sp > 5 * d["med"]):
            cost = max(sp, d["med"], 0.0002 * fill if stock else 0.0)
            r = (dirn * (xp - fill) - cost) / risk
            rows.append((dirn, r, D[e] >= d["split"]))
        i = xi + 1
    return rows


FAMS = {
    "rsi2": [dict(th=t) for t in (5, 10, 20)],
    "bb": [dict()],
    "vwap": [dict(th=t) for t in (1.5, 2.0, 2.5)],
}
GRID = [dict(stop=s, tmax=t, dir=dr) for s, t, dr in itertools.product((1.0, 2.0, 3.0), (8, 16), (0, 1, -1))]


def work(path):
    d = prep(path)
    out = {}
    for fam, plist in FAMS.items():
        for pf in plist:
            for g in GRID:
                p = {**pf, **g}
                key = fam + "|" + ",".join(f"{k}={v}" for k, v in sorted(p.items()))
                out[key] = backtest(d, fam, p)
    return d["sym"], out


def st(rows):
    n = len(rows)
    if not n:
        return (0, 0.0, 0.0)
    return (n, 100 * sum(r[1] > 0 for r in rows) / n, sum(r[1] for r in rows))


if __name__ == "__main__":
    data = Path(sys.argv[1])
    tf = sys.argv[2] if len(sys.argv) > 2 else "15"
    files = sorted(data.glob(f"*_{tf}.npz"))
    with Pool(2) as pool:
        res = pool.map(work, files)
    keys = list(res[0][1].keys())
    groups = {"stocks": [s for s, _ in res if s not in FX_METALS], "metals/fx": [s for s, _ in res if s in FX_METALS]}
    R = dict(res)
    print(f"{tf}-minute.  win = profit after costs.  pick = first 4 months, check = last 2 months (unseen)\n")
    for g, syms in groups.items():
        rows = []
        for k in keys:
            allr = [r for s in syms for r in R[s][k]]
            pk, ck = st([r for r in allr if not r[2]]), st([r for r in allr if r[2]])
            rows.append((k, pk, ck))
        print(f"== {g}: best by pick-period net R among settings with pick win >= 70%")
        hi = sorted([x for x in rows if x[1][1] >= 70 and x[1][0] >= 50], key=lambda x: -x[1][2])[:8]
        for k, pk, ck in hi:
            print(f"  {k:45} pick n {pk[0]:5} win {pk[1]:5.1f}% net {pk[2]:+7.1f}R | check n {ck[0]:5} win {ck[1]:5.1f}% net {ck[2]:+7.1f}R")
        print(f"== {g}: best by pick-period net R (any win rate)")
        for k, pk, ck in sorted(rows, key=lambda x: -x[1][2])[:5]:
            print(f"  {k:45} pick n {pk[0]:5} win {pk[1]:5.1f}% net {pk[2]:+7.1f}R | check n {ck[0]:5} win {ck[1]:5.1f}% net {ck[2]:+7.1f}R")
    print("\n== single symbols: pick win >= 70%, pick net > 0, >= 30 pick trades -> how they did unseen")
    cand = []
    for s, out in res:
        for k, rows in out.items():
            pk, ck = st([r for r in rows if not r[2]]), st([r for r in rows if r[2]])
            if pk[0] >= 30 and pk[1] >= 70 and pk[2] > 0:
                cand.append((s, k, pk, ck))
    ok = sum(1 for c in cand if c[3][2] > 0 and c[3][1] >= 70)
    print(f"  {len(cand)} symbol+setting combos qualified; {ok} also had >= 70% win AND profit in the unseen months")
    for s, k, pk, ck in sorted(cand, key=lambda x: -x[2][2])[:25]:
        print(f"  {s:7} {k:45} pick n {pk[0]:4} win {pk[1]:5.1f}% net {pk[2]:+6.1f}R | check n {ck[0]:4} win {ck[1]:5.1f}% net {ck[2]:+6.1f}R")
