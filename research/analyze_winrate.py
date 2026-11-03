"""Analyse research/optimize_winrate.py output. Selection uses TRAIN only.

Qualifies if (train, worse phase): win rate >= 60%, net > 0, >= 60% profitable months,
enough trades. Ranked by train score. Test results are reported, never used to choose.
Usage: analyze_winrate.py RESULTS_JSON
"""
import json
import sys

MIN_TRAIN = {"15": 120, "30": 60, "60": 30, "240": 15}
rows = json.load(open(sys.argv[1]))


def fmt(s):
    return (f"n={s['n']:4d} win={s['wr']:5.1%} net={s['net']:+7.1f}R pf={s['pf']:4.2f} dd={s['dd']:5.1f}R "
            f"months+={s['months_pos']:4.0%} TP={s['tp_share']:4.0%}")


def name(r):
    return (f"{r['tf']:>2}m sens={r['sens']:<4} atr={r['atr_len']:<2} stop={r['stop_atr']}xATR "
            f"tp={r['rr']}x {r['opp']:<10} trend={r['trend']}")


print("THE TRAP - highest train win rates regardless of profit:")
for r in sorted(rows, key=lambda r: r["train"]["wr"], reverse=True)[:3]:
    print(f"  {name(r)}\n     train {fmt(r['train'])}\n     test  {fmt(r['test'])}")

ok = [r for r in rows if r["train"]["n"] >= MIN_TRAIN[r["tf"]] and r["train"]["wr"] >= 0.6
      and r["train"]["net"] > 0 and r["train"]["months_pos"] >= 0.6]
ok.sort(key=lambda r: r["train"]["score"], reverse=True)
print(f"\n{len(ok)} of {len(rows)} settings reach >=60% win rate AND profit AND >=60% good months on TRAIN.")
for tf in ("15", "30", "60"):
    sub = [r for r in ok if r["tf"] == tf]
    if not sub:
        print(f"\n--- {tf}m: none qualify")
        continue
    top = sub[:20]
    held = sum(r["test"]["wr"] >= 0.6 and r["test"]["net"] > 0 and r["test_other_phase"]["net"] > 0 for r in top)
    print(f"\n--- {tf}m: {len(sub)} qualify; {held}/{len(top)} of the top {len(top)} keep >=60% AND profit on TEST")
    for r in sub[:5]:
        print(f"  {name(r)}\n     train {fmt(r['train'])}\n     TEST  {fmt(r['test'])}")
for trend in ("none", "ema200", "htf240"):
    sub = [r for r in ok if r["trend"] == trend][:20]
    if sub:
        good = sum(r["test"]["net"] > 0 for r in sub)
        avg_wr = sum(r["test"]["wr"] for r in sub) / len(sub)
        print(f"\nTrend filter {trend:7}: top {len(sub)} -> {good} profitable on test, average test win rate {avg_wr:.1%}")
