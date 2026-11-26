r"""Read research/scalp_grid.py output: best settings with >= 70% win rate, chosen on the pick
period only, then shown on the unseen check period.

Usage: .venv\Scripts\python.exe research\scalp_grid_report.py research\data_intraday\grid_3_5_15.json
"""
import json
import sys

FXM = {"XAUUSD", "XAGUSD", "EURUSD"}
res = json.loads(open(sys.argv[1]).read())
tfs = sorted({int(k.split("|")[1]) for k in res})
names = list(next(iter(res.values())).keys())


def agg(keys, name):
    a = dict(pn=0, pw=0, pr=0.0, cn=0, cw=0, cr=0.0)
    for k in keys:
        v = res[k].get(name)
        if v:
            for f in a:
                a[f] += v[f]
    return a


def fmt(n, w, r):
    return f"{n:5} tr {100 * w / max(1, n):5.1f}% {r / max(1, n):+.3f}R" if n else f"{'-':>24}"


for group, keep in [("20 STOCKS", lambda s: s not in FXM), ("GOLD/SILVER/EURUSD", lambda s: s in FXM)]:
    for tf in tfs:
        keys = [k for k in res if int(k.split("|")[1]) == tf and keep(k.split("|")[0])]
        rows = []
        for name in names:
            a = agg(keys, name)
            if a["pn"] >= 100 and a["pw"] / a["pn"] >= 0.70:
                rows.append((a["pr"] / a["pn"], name, a))
        rows.sort(reverse=True)
        print(f"\n### {group} M{tf}: settings with >= 70% win in the pick period, best avg R first "
              f"({len(rows)} of {len(names)} qualify)")
        print(f"{'settings':78} | {'PICK (4 months)':24} | {'CHECK (unseen 2 months)':24}")
        for _, name, a in rows[:6]:
            print(f"{name:78} | {fmt(a['pn'], a['pw'], a['pr'])} | {fmt(a['cn'], a['cw'], a['cr'])}")
        if rows:
            # best stocks for the top setting: chosen on pick, judged on check
            name = rows[0][1]
            good = [k for k in keys if res[k][name]["pn"] >= 10 and res[k][name]["pr"] > 0]
            a = agg(good, name)
            print(f"  -> symbols positive in pick with top setting: {', '.join(k.split('|')[0] for k in good) or 'none'}")
            if good:
                print(f"     those symbols together: pick {fmt(a['pn'], a['pw'], a['pr'])} | check {fmt(a['cn'], a['cw'], a['cr'])}")
