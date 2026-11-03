"""Pick robust settings from research/optimize_ut.py output (v2 rules).

A setting qualifies only if, on the TRAIN period and in its WORSE starting phase, it has
enough trades, a positive net result and at least MIN_MONTHS_POS of months profitable.
Qualifiers are ranked by the neighbourhood-averaged worst-phase score. The test period is
only reported, never used to choose.
Usage: analyze_ut.py RESULTS_JSON
"""
import json
import sys

MIN_TRAIN = {"15": 120, "30": 60, "60": 30}
MIN_MONTHS_POS = 0.6
results = json.load(open(sys.argv[1]))


def fmt(s):
    return (f"n={s['n']:4d} win={s['wr']:5.1%} net={s['net']:+7.1f}R pf={s['pf']:4.2f} dd={s['dd']:5.1f}R "
            f"months+={s['months_pos']:4.0%} TP-exits={s['tp_share']:4.0%}")


def name(r):
    return (f"{r['tf']:>2}m sens={r['sens']:<4} atr={r['atr_len']:<2} stop={r['stop_atr']}xATR rr={r['rr']} "
            f"{r['opp']:<15} session={r['session']}")


def show(r):
    print(f"  {name(r)}  robust={r['robust']:.2f}")
    print(f"     train (worse phase) {fmt(r['train'])}")
    print(f"     TEST continuous     {fmt(r['test'])}")
    print(f"     test other phase    {fmt(r['test_other_phase'])}")
    print(f"     test fresh start    {fmt(r['test_fresh'])}")


def find(rows, tf, sens, atr_len, stop, rr, opp="Close only", session="all"):
    return next(r for r in rows if r["tf"] == tf and r["sens"] == sens and r["atr_len"] == atr_len
                and r["stop_atr"] == stop and r["rr"] == rr and r["opp"] == opp and r["session"] == session)


for sym, current in (("XAUUSD", ("60", 2.0, 1, 3.0, 3.0)), ("XAGUSD", ("30", 4.0, 10, 3.0, 3.0))):
    rows = [r for r in results if r["sym"] == sym]
    print(f"\n################ {sym} ################")
    print("Current v1.3 preset:")
    show(find(rows, *current))
    ok = [r for r in rows if r["train"]["n"] >= MIN_TRAIN[r["tf"]] and r["train"]["net"] > 0
          and r["train"]["months_pos"] >= MIN_MONTHS_POS]
    ok.sort(key=lambda r: r["robust"], reverse=True)
    print(f"\n{len(ok)} settings pass the v2 train rules. Top 6:")
    for r in ok[:6]:
        show(r)
    top = ok[:50]
    both = sum(r["test"]["net"] > 0 and r["test_other_phase"]["net"] > 0 for r in top)
    print(f"\nOf the top {len(top)} v2 picks, {both} were profitable on the unseen test in BOTH phases.")
