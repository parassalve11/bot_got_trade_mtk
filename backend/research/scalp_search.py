r"""Search for a 5-minute scalping strategy that survives costs out of sample.

Usage (from backend/):
    .venv\Scripts\python.exe research\scalp_search.py research\data_intraday research\data_gold2y

Families (entry at the next candle's open, stop first when a candle touches stop and target):
  orb    US stocks, 5-minute Opening Range Breakout (Zarattini, Barbon & Aziz 2024): the first
         5-minute candle's direction decides (green -> BUY, red -> SELL), entry at the 2nd candle's
         open, stop = s x daily ATR(14), target k x risk or none (exit at the session end).
         "In play" filter: first-candle volume / its 14-day average >= rv, top `top` per day.
  lon    Gold M5 London-open breakout: range = the `n` candles from 10:00 server time, first close
         beyond it until `until` -> trade, stop other side / middle, target k x risk, exit at `xh`.
  asia5  Gold M5 Asian range (01-09) breakout, stop middle, target k x risk, exit at `xh`.
Costs: stocks max(spread, median spread, 0.02% of price); gold max(spread, median spread).
Stocks: pick = first 4 months, check = last 2. Gold M5: pick = first 60% of days, check = rest.
"""

import itertools
import json
import sys
from pathlib import Path

import numpy as np

STOCK_DIR, GOLD_DIR = Path(sys.argv[1]), Path(sys.argv[2])
FX = {"XAUUSD", "XAGUSD", "EURUSD"}


def load(path):
    z = np.load(path)
    d = {k: np.asarray(z[k], float) for k in ("open", "high", "low", "close", "volume", "time")}
    d["spread"] = np.asarray(z["spread"], float) * float(z["point"])
    d["day"] = (d["time"] // 86400).astype(np.int64)
    d["hr"] = ((d["time"] % 86400) // 3600).astype(int)
    d["mn"] = ((d["time"] % 3600) // 60).astype(int)
    d["med"] = float(np.median(d["spread"]))
    idx = {}
    for i, dd in enumerate(d["day"]):
        idx.setdefault(int(dd), []).append(i)
    d["days"] = idx
    return d


def trade(d, e, side, stop, tgt, last, cost):
    O, H, L, C = d["open"], d["high"], d["low"], d["close"]
    fill = O[e]
    risk = abs(fill - stop)
    if risk <= 0 or side * (stop - fill) >= 0:
        return None
    px = C[last]
    for j in range(e, last + 1):
        if (side == 1 and L[j] <= stop) or (side == -1 and H[j] >= stop):
            px = O[j] if side * (O[j] - stop) < 0 else stop
            break
        if tgt is not None and side * ((H[j] if side == 1 else L[j]) - tgt) >= 0:
            px = O[j] if side * (O[j] - tgt) > 0 else tgt
            break
    return (side * (px - fill) - cost) / risk


# ------------------------------------------------------------------ stocks: 5-minute ORB
def orb_prepare():
    out = {}
    for f in sorted(STOCK_DIR.glob("*_5.npz")):
        sym = f.stem.rsplit("_", 1)[0]
        if sym in FX:
            continue
        d = load(f)
        days = sorted(d["days"])
        rows = []
        for dd in days:
            ix = d["days"][dd]
            if len(ix) < 20:
                continue
            rows.append(dict(day=dd, ix=ix, hi=d["high"][ix].max(), lo=d["low"][ix].min(), close=d["close"][ix[-1]],
                             v0=d["volume"][ix[0]]))
        # daily ATR(14) and first-candle relative volume, both from PREVIOUS days only
        for k, r in enumerate(rows):
            prev = rows[max(0, k - 14):k]
            if len(prev) < 14:
                r["atr"] = r["rv"] = None
                continue
            trs = [max(p["hi"] - p["lo"], abs(p["hi"] - rows[k - 15 + m]["close"]) if k - 15 + m >= 0 else 0,
                       abs(p["lo"] - rows[k - 15 + m]["close"]) if k - 15 + m >= 0 else 0) for m, p in enumerate(prev)]
            r["atr"] = float(np.mean(trs))
            avg = np.mean([p["v0"] for p in prev])
            r["rv"] = r["v0"] / avg if avg > 0 else None
        out[sym] = (d, rows)
    allday = sorted({r["day"] for _, rows in out.values() for r in rows})
    split = allday[int(len(allday) * 2 / 3)]
    return out, split


def orb(data, p):
    res = []
    cands = {}
    for sym, (d, rows) in data.items():
        O, C = d["open"], d["close"]
        for r in rows:
            if r["atr"] is None or r["rv"] is None or r["rv"] < p["rv"]:
                continue
            i0 = r["ix"][0]
            side = 1 if C[i0] > O[i0] else -1 if C[i0] < O[i0] else 0
            if side == 0 or (p["dir"] and side != p["dir"]):
                continue
            cands.setdefault(r["day"], []).append((r["rv"], sym, r, side))
    for day, lst in cands.items():
        for rv, sym, r, side in sorted(lst, key=lambda x: -x[0])[:p["top"]]:
            d = data[sym][0]
            e, last = r["ix"][1], r["ix"][-1]
            stop = d["open"][e] - side * p["s"] * r["atr"]
            tgt = None if not p["k"] else d["open"][e] + side * p["k"] * p["s"] * r["atr"]
            cost = max(d["spread"][e], d["med"], 0.0002 * d["open"][e])
            x = trade(d, e, side, stop, tgt, last, cost)
            if x is not None:
                res.append((day, x))
    return res


# ------------------------------------------------------------------ gold M5
def lon(d, p):
    res = []
    H, L, C, O, HR, MN = d["high"], d["low"], d["close"], d["open"], d["hr"], d["mn"]
    for dd, ix in d["days"].items():
        st = [k for k, i in enumerate(ix) if HR[i] == 10 and MN[i] == 0]
        if not st:
            continue
        k0 = st[0]
        rng = ix[k0:k0 + p["n"]]
        if len(rng) < p["n"]:
            continue
        hi, lo = H[rng].max(), L[rng].min()
        ends = [i for i in ix if HR[i] < p["xh"]]
        if not ends:
            continue
        last = ends[-1]
        for i in ix[k0 + p["n"]:]:
            if HR[i] >= p["until"] or i >= last:
                break
            side = 1 if C[i] > hi else -1 if C[i] < lo else 0
            if side == 0:
                continue
            if p["dir"] and side != p["dir"]:
                break
            e = i + 1
            stop = (lo if side == 1 else hi) if p["stop"] == "opp" else (hi + lo) / 2
            tgt = None if not p["k"] else O[e] + side * p["k"] * abs(O[e] - stop)
            x = trade(d, e, side, stop, tgt, last, max(d["spread"][e], d["med"]))
            if x is not None:
                res.append((dd, x))
            break
    return res


def asia5(d, p):
    res = []
    H, L, C, O, HR = d["high"], d["low"], d["close"], d["open"], d["hr"]
    for dd, ix in d["days"].items():
        rng = [i for i in ix if 1 <= HR[i] < 9]
        if len(rng) < 24:
            continue
        hi, lo = H[rng].max(), L[rng].min()
        ends = [i for i in ix if HR[i] < p["xh"]]
        if not ends:
            continue
        last = ends[-1]
        for i in ix:
            if HR[i] < 9:
                continue
            if HR[i] >= p["until"] or i >= last:
                break
            side = 1 if C[i] > hi else -1 if C[i] < lo else 0
            if side == 0:
                continue
            e = i + 1
            stop = (hi + lo) / 2
            tgt = None if not p["k"] else O[e] + side * p["k"] * abs(O[e] - stop)
            x = trade(d, e, side, stop, tgt, last, max(d["spread"][e], d["med"]))
            if x is not None:
                res.append((dd, x))
            break
    return res


def st(rows):
    if not rows:
        return dict(n=0, win=0.0, net=0.0, dd=0.0)
    r = np.array([x[1] for x in sorted(rows)])
    eq = np.cumsum(r)
    return dict(n=len(r), win=100 * (r > 0).mean(), net=r.sum(), dd=(eq - np.maximum.accumulate(eq)).min())


def grid(**kw):
    keys = list(kw)
    return [dict(zip(keys, v)) for v in itertools.product(*kw.values())]


def report(name, plist, fn, split, min_n):
    res = []
    for p in plist:
        rows = fn(p)
        res.append((p, st([x for x in rows if x[0] < split]), st([x for x in rows if x[0] >= split])))
    good = [x for x in res if x[1]["n"] >= min_n and x[1]["net"] > 0]
    both = [x for x in good if x[2]["net"] > 0]
    print(f"\n=== {name}: {len(res)} settings; {len(good)} profitable in the pick period; {len(both)} also in the check period")
    for p, a, b in sorted(good, key=lambda x: -x[1]["net"])[:8]:
        ps = ",".join(f"{k}={v}" for k, v in p.items())
        print(f"  {ps:44} pick n {a['n']:4} win {a['win']:5.1f}% net {a['net']:+7.1f}R dd {a['dd']:6.1f} | "
              f"check n {b['n']:4} win {b['win']:5.1f}% net {b['net']:+7.1f}R dd {b['dd']:6.1f}")
    return res


if __name__ == "__main__":
    data, split = orb_prepare()
    report("stocks 5-min ORB", grid(s=(0.05, 0.1, 0.2), k=(0, 2, 5, 10), rv=(0, 1.0, 1.5), top=(3, 5, 20), dir=(0, 1, -1)),
           lambda p: orb(data, p), split, 60)
    g5 = load(GOLD_DIR / "XAUUSD_5.npz")
    gdays = sorted(g5["days"])
    gsplit = gdays[int(len(gdays) * 0.6)]
    report("gold M5 London-open breakout", grid(n=(3, 6, 12), until=(12, 14), stop=("opp", "mid"), k=(0, 1, 1.5, 2),
                                                  dir=(0, 1, -1), xh=(13, 17)),
           lambda p: lon(g5, p), gsplit, 60)
    report("gold M5 Asian-range breakout scalp", grid(k=(0, 0.5, 1, 1.5, 2), until=(12, 17), xh=(13, 17, 23)),
           lambda p: asia5(g5, p), gsplit, 60)
