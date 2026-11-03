import json
import sys

results = json.load(open(sys.argv[1]))


def fmt(s):
    return (f"n={s['n']:4d} win={s['wr']:5.1%} net={s['net']:+7.1f}R pf={s['pf']:4.2f} "
            f"exp={s['exp']:+.3f}R dd={s['dd']:5.1f}R")


def name(r):
    return (f"{r['tf']:>2}m sens={r['sens']:<4} atr={r['atr_len']:<2} stop={r['stop_atr']}xATR rr={r['rr']} "
            f"{r['opp']:<15} session={r['session']}")


MIN_TRAIN = {"15": 120, "30": 60, "60": 30}
for sym in ("XAUUSD", "XAGUSD"):
    rows = [r for r in results if r["sym"] == sym]
    print(f"\n################ {sym} ################")
    for tf in ("15", "30", "60"):
        base = next(r for r in rows if r["tf"] == tf and r["sens"] == 6.4 and r["atr_len"] == 2 and r["stop_atr"] == 2.0
                    and r["rr"] == 1.5 and r["opp"] == "Close only" and r["session"] == "all")
        print(f"\nCURRENT DEFAULT {tf}m   train {fmt(base['train'])}\n{'':21}test  {fmt(base['test'])}")
    ok = [r for r in rows if r["train"]["n"] >= MIN_TRAIN[r["tf"]] and r["train"]["net"] > 0]
    ok.sort(key=lambda r: r["robust"], reverse=True)
    print("\nTop 8 by ROBUST train score (test = unseen last 3 months):")
    for r in ok[:8]:
        print(f"  {name(r)}  robust={r['robust']:.2f}\n     train {fmt(r['train'])}\n     test  {fmt(r['test'])}")
    best_raw = max(rows, key=lambda r: r["train"]["score"] if r["train"]["n"] >= MIN_TRAIN[r["tf"]] else -99)
    print(f"\n(For contrast) single best raw train score: {name(best_raw)}\n     train {fmt(best_raw['train'])}\n"
          f"     test  {fmt(best_raw['test'])}")
    test_pos = sum(r["test"]["net"] > 0 for r in ok[:50])
    print(f"Of the top 50 robust train picks, {test_pos} were profitable on the unseen test period.")
