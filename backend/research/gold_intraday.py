r"""Search for a gold (XAUUSD) intraday strategy that holds up out of sample.

Usage (from backend/):  .venv\Scripts\python.exe research\gold_intraday.py research\data_gold2y

Data: XAUUSD M15, ~2 years, MT5 server time (EET: London open = 10:00, New York open = 15:30).
Families (all flat by the end of the day, one trade per family-setting per day):
  arb   Asian range breakout: range of hours [rs, re); first close beyond it before `until`
        -> enter next open. Stop: other side / middle of the range / 1.5 ATR. Target: k x risk or
        none (exit at the day end).
  fake  Asian range fake breakout: price closes beyond the range, then a later candle closes back
        inside -> fade it. Stop beyond the poke extreme, target the middle / other side / k x risk.
  tod   Time of day: BUY (or SELL) at hour h1, exit at hour h2 (3 ATR safety stop).
  nyorb New York opening range (first n candles from 15:30): breakout, stop other side / middle.
Costs: every trade pays max(candle spread, median spread). Stop is assumed hit first when a
candle touches stop and target. Pick = first 365 days, check = the rest (unseen).
"""

import itertools
import sys
from pathlib import Path

import numpy as np

z = np.load(Path(sys.argv[1]) / "XAUUSD_15.npz")
O, H, L, C, T = (np.asarray(z[k], float) for k in ("open", "high", "low", "close", "time"))
SP = np.asarray(z["spread"], float) * float(z["point"])
MED = float(np.median(SP))
N = len(C)
DAY = (T // 86400).astype(np.int64)
HR = ((T % 86400) // 3600).astype(int)
MIN = ((T % 3600) // 60).astype(int)
SPLIT = DAY[0] + 365
TR = np.maximum(H - L, np.maximum(abs(H - np.r_[C[0], C[:-1]]), abs(L - np.r_[C[0], C[:-1]])))
ATR = np.empty(N)
ATR[:14] = TR[:14].mean()
for i in range(14, N):
    ATR[i] = (TR[i] + 13 * ATR[i - 1]) / 14

days = {}
for i, d in enumerate(DAY):
    days.setdefault(int(d), []).append(i)
DAYS = sorted(days)


def run_trade(e, d, stop, tgt, last):
    """Enter at O[e] (direction d), manage until bar `last` (inclusive). Returns R after costs."""
    fill = O[e]
    risk = abs(fill - stop)
    if risk <= 0 or d * (stop - fill) >= 0:
        return None
    for j in range(e, last + 1):
        if (d == 1 and L[j] <= stop) or (d == -1 and H[j] >= stop):
            px = O[j] if (d == 1 and O[j] < stop) or (d == -1 and O[j] > stop) else stop
            break
        if tgt is not None and ((d == 1 and H[j] >= tgt) or (d == -1 and L[j] <= tgt)):
            px = O[j] if (d == 1 and O[j] > tgt) or (d == -1 and O[j] < tgt) else tgt
            break
    else:
        px = C[last]
    cost = max(SP[e], MED)
    return (d * (px - fill) - cost) / risk


def day_end(idx, eod):
    last = [i for i in idx if HR[i] < eod]
    return last[-1] if last else None


def arb(p):
    out = []
    for dd in DAYS:
        idx = days[dd]
        rng = [i for i in idx if p["rs"] <= HR[i] < p["re"]]
        if len(rng) < 8:
            continue
        hi, lo = H[rng].max(), L[rng].min()
        a = ATR[rng[-1]]
        if p["maxw"] and hi - lo > p["maxw"] * a:
            continue
        last = day_end(idx, p["eod"])
        cand = [i for i in idx if p["re"] <= HR[i] < p["until"] and i < (last or 0)]
        for i in cand:
            d = 1 if C[i] > hi else -1 if C[i] < lo else 0
            if d == 0:
                continue
            if (p["dir"] == 1 and d == -1) or (p["dir"] == -1 and d == 1):
                break
            e = i + 1
            if e > last:
                break
            stop = {"opp": lo if d == 1 else hi, "mid": (hi + lo) / 2,
                    "atr": O[e] - d * 1.5 * ATR[i]}[p["stop"]]
            tgt = None if not p["k"] else O[e] + d * p["k"] * abs(O[e] - stop)
            r = run_trade(e, d, stop, tgt, last)
            if r is not None:
                out.append((dd, r))
            break
    return out


def fake(p):
    out = []
    for dd in DAYS:
        idx = days[dd]
        rng = [i for i in idx if p["rs"] <= HR[i] < p["re"]]
        if len(rng) < 8:
            continue
        hi, lo = H[rng].max(), L[rng].min()
        last = day_end(idx, p["eod"])
        cand = [i for i in idx if p["re"] <= HR[i] < p["until"] and i < (last or 0)]
        side, ext = 0, None
        for i in cand:
            if side == 0:
                if C[i] > hi:
                    side, ext = 1, H[i]
                elif C[i] < lo:
                    side, ext = -1, L[i]
                continue
            ext = max(ext, H[i]) if side == 1 else min(ext, L[i])
            back = (side == 1 and C[i] < hi) or (side == -1 and C[i] > lo)
            if not back:
                continue
            d = -side
            if (p["dir"] == 1 and d == -1) or (p["dir"] == -1 and d == 1):
                break
            e = i + 1
            if e > last:
                break
            stop = ext + side * 0.1 * ATR[i]
            tgt = {"mid": (hi + lo) / 2, "opp": lo if d == -1 else hi,
                   "1R": O[e] + d * abs(O[e] - stop), "2R": O[e] + d * 2 * abs(O[e] - stop)}[p["tgt"]]
            if d * (tgt - O[e]) <= 0:
                break
            r = run_trade(e, d, stop, tgt, last)
            if r is not None:
                out.append((dd, r))
            break
    return out


def tod(p):
    out = []
    for dd in DAYS:
        idx = days[dd]
        ent = [i for i in idx if HR[i] == p["h1"] and MIN[i] == 0]
        ext = [i for i in idx if HR[i] == p["h2"] - 1 and MIN[i] == 45]
        if not ent or not ext or ext[0] <= ent[0]:
            continue
        e, last, d = ent[0], ext[0], p["dir"]
        r = run_trade(e, d, O[e] - d * 3 * ATR[e - 1], None, last)
        if r is not None:
            out.append((dd, r))
    return out


def nyorb(p):
    out = []
    for dd in DAYS:
        idx = days[dd]
        start = [k for k, i in enumerate(idx) if HR[i] == 15 and MIN[i] == 30]
        if not start:
            continue
        k0 = start[0]
        rng = idx[k0:k0 + p["n"]]
        if len(rng) < p["n"]:
            continue
        hi, lo = H[rng].max(), L[rng].min()
        last = day_end(idx, p["eod"])
        for i in idx[k0 + p["n"]:]:
            if HR[i] >= p["until"] or i >= last:
                break
            d = 1 if C[i] > hi else -1 if C[i] < lo else 0
            if d == 0:
                continue
            if (p["dir"] == 1 and d == -1) or (p["dir"] == -1 and d == 1):
                break
            e = i + 1
            stop = lo if (p["stop"] == "opp" and d == 1) else hi if p["stop"] == "opp" else (hi + lo) / 2
            tgt = None if not p["k"] else O[e] + d * p["k"] * abs(O[e] - stop)
            r = run_trade(e, d, stop, tgt, last)
            if r is not None:
                out.append((dd, r))
            break
    return out


def grid(keys, *vals):
    return [dict(zip(keys, v)) for v in itertools.product(*vals)]


FAMS = {
    "arb": (arb, grid(["rs", "re", "until", "stop", "k", "dir", "maxw", "eod"],
                      (1, 3), (9, 10), (13, 17), ("opp", "mid", "atr"), (0, 1, 1.5, 2), (0, 1, -1), (0, 8), (23,))),
    "fake": (fake, grid(["rs", "re", "until", "tgt", "dir", "eod"],
                        (1, 3), (9, 10), (13, 17), ("mid", "opp", "1R", "2R"), (0, 1, -1), (23,))),
    "tod": (tod, [dict(h1=a, h2=b, dir=d) for a in range(1, 23) for b in range(a + 1, min(a + 13, 24)) for d in (1, -1)]),
    "nyorb": (nyorb, grid(["n", "until", "stop", "k", "dir", "eod"],
                          (2, 4), (19, 21), ("opp", "mid"), (0, 1, 2), (0, 1, -1), (23,))),
}


def st(rows):
    n = len(rows)
    if not n:
        return dict(n=0, win=0, net=0, avg=0, dd=0)
    r = np.array([x[1] for x in rows])
    eq = np.cumsum(r)
    return dict(n=n, win=100 * (r > 0).mean(), net=r.sum(), avg=r.mean(), dd=(eq - np.maximum.accumulate(eq)).min())


if __name__ == "__main__":
    from datetime import datetime, timezone
    f = lambda d: datetime.fromtimestamp(d * 86400, timezone.utc).date()  # noqa: E731
    print(f"XAUUSD M15 {f(DAYS[0])} .. {f(DAYS[-1])}; pick = until {f(SPLIT)}, check = after; median spread {MED:.2f}")
    for fam, (fn, plist) in FAMS.items():
        res = []
        for p in plist:
            rows = fn(p)
            a, b = st([x for x in rows if x[0] < SPLIT]), st([x for x in rows if x[0] >= SPLIT])
            res.append((p, a, b))
        good = [x for x in res if x[1]["n"] >= 60 and x[1]["net"] > 0]
        both = [x for x in good if x[2]["net"] > 0]
        print(f"\n=== {fam}: {len(res)} settings; {len(good)} profitable in year 1 (>=60 trades); "
              f"{len(both)} of those also profitable in year 2")
        for p, a, b in sorted(good, key=lambda x: -x[1]["net"])[:8]:
            ps = ",".join(f"{k}={v}" for k, v in p.items())
            print(f"  {ps:55} Y1 n {a['n']:4} win {a['win']:5.1f}% net {a['net']:+6.1f}R dd {a['dd']:6.1f} | "
                  f"Y2 n {b['n']:4} win {b['win']:5.1f}% net {b['net']:+6.1f}R dd {b['dd']:6.1f}")
