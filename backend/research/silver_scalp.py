r"""Search for a silver (XAGUSD) 5-minute scalp that survives costs out of sample.

Usage (from backend/):  .venv\Scripts\python.exe research\silver_scalp.py research\data_silver2y

Silver often breaks its Asian range and snaps back (the gold breakout scalp loses on silver), so
the families are fades plus classic mean reversion:
  fade     after the first close beyond the Asian range (01-09 server time), a later close back
           inside -> trade back toward the range (stop beyond the poke extreme + 0.1 ATR).
  fadenow  fade the FIRST breakout close at once (stop = poke extreme + b x ATR).
  rsi2/bb/vwap  research/hiwin15.py families on M5 (trend SMA200, ATR stop, time stop).
Costs = max(candle spread, median spread). Pick = first 60% of days, check = the rest.
"""

import itertools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "research")
import hiwin15  # noqa: E402
import scalp_search as ss  # noqa: E402

DATA = Path(sys.argv[1])
D = ss.load(DATA / "XAGUSD_5.npz")
TR = np.maximum(D["high"] - D["low"], np.maximum(abs(D["high"] - np.r_[D["close"][0], D["close"][:-1]]),
                                                 abs(D["low"] - np.r_[D["close"][0], D["close"][:-1]])))
ATR = np.empty(len(TR))
ATR[:14] = TR[:14].mean()
for i in range(14, len(TR)):
    ATR[i] = (TR[i] + 13 * ATR[i - 1]) / 14
DAYS = sorted(D["days"])
SPLIT = DAYS[int(len(DAYS) * 0.6)]


def asian(ix):
    rng = [i for i in ix if 1 <= D["hr"][i] < 9]
    if len(rng) < 24:
        return None
    return D["high"][rng].max(), D["low"][rng].min()


def fade(p, immediate=False):
    H, L, C, O, HR = D["high"], D["low"], D["close"], D["open"], D["hr"]
    out = []
    for dd in DAYS:
        ix = D["days"][dd]
        r = asian(ix)
        ends = [i for i in ix if HR[i] < p["xh"]]
        if r is None or not ends:
            continue
        hi, lo = r
        last = ends[-1]
        side, ext = 0, None
        for i in ix:
            if HR[i] < 9:
                continue
            if HR[i] >= p["until"] or i >= last:
                break
            if side == 0:
                if C[i] > hi:
                    side, ext = 1, H[i]
                elif C[i] < lo:
                    side, ext = -1, L[i]
                if side == 0 or not immediate:
                    continue
            else:
                ext = max(ext, H[i]) if side == 1 else min(ext, L[i])
                if not ((side == 1 and C[i] < hi) or (side == -1 and C[i] > lo)):
                    continue
            d = -side
            if p["dir"] and d != p["dir"]:
                break
            e = i + 1
            stop = ext + side * p["b"] * ATR[i]
            mid = (hi + lo) / 2
            tgt = {"mid": mid, "opp": lo if d == -1 else hi}.get(p["tgt"])
            if tgt is None:
                tgt = O[e] + d * float(p["tgt"]) * abs(O[e] - stop)
            if d * (tgt - O[e]) <= 0:
                break
            x = ss.trade(D, e, d, stop, tgt, last, max(D["spread"][e], D["med"]))
            if x is not None:
                out.append((dd, x))
            break
    return out


def grid(**kw):
    keys = list(kw)
    return [dict(zip(keys, v)) for v in itertools.product(*kw.values())]


def summarize(name, res):
    good = [x for x in res if x[1]["n"] >= 60 and x[1]["net"] > 0]
    both = [x for x in good if x[2]["net"] > 0]
    print(f"\n=== {name}: {len(res)} settings; {len(good)} profitable in the pick period; {len(both)} also in the check period")
    for p, a, b in sorted(good, key=lambda x: -x[1]["net"])[:8]:
        ps = ",".join(f"{k}={v}" for k, v in p.items())
        print(f"  {ps:46} pick n {a['n']:4} win {a['win']:5.1f}% net {a['net']:+6.1f}R dd {a['dd']:6.1f} | "
              f"check n {b['n']:4} win {b['win']:5.1f}% net {b['net']:+6.1f}R dd {b['dd']:6.1f}")


def run(fn, plist):
    res = []
    for p in plist:
        rows = fn(p)
        res.append((p, ss.st([x for x in rows if x[0] < SPLIT]), ss.st([x for x in rows if x[0] >= SPLIT])))
    return res


if __name__ == "__main__":
    print(f"XAGUSD M5, {len(DAYS)} days, median spread {D['med']:.3f}")
    g = grid(tgt=("mid", "opp", "0.5", "1"), b=(0.1, 0.5), until=(13, 17), dir=(0, 1, -1), xh=(17, 23))
    summarize("fade after a failed breakout", run(lambda p: fade(p), g))
    g = grid(tgt=("mid", "0.5", "1"), b=(0.5, 1.0, 2.0), until=(13, 17), dir=(0, 1, -1), xh=(17, 23))
    summarize("fade the first breakout at once", run(lambda p: fade(p, immediate=True), g))
    # classic mean reversion (research/hiwin15.py) on the same M5 file; its own 2/3 split
    d5 = hiwin15.prep(DATA / "XAGUSD_5.npz")
    for fam, plist in hiwin15.FAMS.items():
        res = []
        for pf in plist:
            for g5 in hiwin15.GRID:
                p = {**pf, **g5}
                rows = hiwin15.backtest(d5, fam, p)
                res.append((p, ss.st([(0, r[1]) for r in rows if not r[2]]), ss.st([(0, r[1]) for r in rows if r[2]])))
        summarize(f"{fam} mean reversion on M5 (split 2/3)", res)
