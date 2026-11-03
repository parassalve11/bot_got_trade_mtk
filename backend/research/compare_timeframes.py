"""Per-timeframe comparison of high-win-rate results (Pine-exact HTF timing).

1) The Gold 1H High-Win settings applied unchanged on every timeframe.
2) The best high-win setting per timeframe chosen on TRAIN only (>=60% win, profit,
   >=60% profitable months, enough trades, most robust neighbourhood).
A 4H chart cannot use the 4H trend filter (Pine requires a higher timeframe), so for 4H
the filter options are "none" and "ema200" only.
Usage: compare_timeframes.py RESULTS_JSON
"""
import json
import sys

ONE_R = 500
MIN_TRAIN = {"15": 120, "30": 60, "60": 30, "240": 15}
G = dict(sens=[1.0, 2.0, 3.0, 4.0, 6.4], atr_len=[1, 2, 5, 10], stop_atr=[1.5, 2.0, 3.0, 4.0],
         rr=[0.3, 0.5, 0.75, 1.0, 1.5])
rows = [r for r in json.load(open(sys.argv[1])) if not (r["tf"] == "240" and r["trend"] == "htf240")]


def near(dim, value):
    i = G[dim].index(value)
    return G[dim][max(0, i - 1): i + 2]


def neighbours(r):
    return [x for x in rows if x["tf"] == r["tf"] and x["trend"] == r["trend"] and x["opp"] == r["opp"]
            and all(x[d] in near(d, r[d]) for d in G)]


def line(tf, r, note=""):
    s = r["test"]
    print(f"| {tf:>4} | {r['sens']:<4} | {r['atr_len']:<2} | {r['stop_atr']}x | {r['rr']}x | {r['trend']:<6} | "
          f"{s['n']:3d} | {s['wr']:5.1%} | {s['net'] * ONE_R:+7,.0f} | {s['pf']:4.2f} | {-s['dd'] * ONE_R:+7,.0f} | "
          f"{s['months_pos']:4.0%} | {note}")


header = ("| TF | sens | ATR | stop | target | filter | trades | win | profit $ | PF | worst DD $ | months+ | note |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|")
print("\n## 1) Gold 1H High-Win settings on every timeframe (unseen 3 months)\n")
print(header)
for tf in ("15", "30", "60", "240"):
    trend = "htf240" if tf != "240" else "none"
    r = next(x for x in rows if x["tf"] == tf and x["trend"] == trend and x["opp"] == "Close only"
             and (x["sens"], x["atr_len"], x["stop_atr"], x["rr"]) == (3.0, 2, 2.0, 0.75))
    line(tf, r, "4H: no higher TF filter possible" if tf == "240" else "")

print("\n## 2) Best high-win setting per timeframe, chosen on TRAIN only (unseen 3 months)\n")
print(header)
for tf in ("15", "30", "60", "240"):
    ok = [r for r in rows if r["tf"] == tf and r["opp"] == "Close only" and r["train"]["n"] >= MIN_TRAIN[tf]
          and r["train"]["wr"] >= 0.6 and r["train"]["net"] > 0 and r["train"]["months_pos"] >= 0.6]
    if not ok:
        print(f"| {tf:>4} | none qualify on train |")
        continue
    for r in ok:
        nb = neighbours(r)
        r["nb"] = sum(x["train"]["net"] > 0 for x in nb) / len(nb)
    ok.sort(key=lambda r: (r["nb"], r["train"]["score"]), reverse=True)
    best = ok[0]
    held = sum(r["test"]["wr"] >= 0.6 and r["test"]["net"] > 0 for r in ok)
    line(tf, best, f"{held}/{len(ok)} train qualifiers held >=60% + profit on test")

