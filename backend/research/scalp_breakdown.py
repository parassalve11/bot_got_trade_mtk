r"""Per-pattern / per-direction totals of research/backtest_scalping.py results, all stocks together.

Usage: .venv\Scripts\python.exe research\scalp_breakdown.py research\data_intraday "More trades"
"""
import json
import sys
from pathlib import Path

data = Path(sys.argv[1])
mode = sys.argv[2].replace(" ", "_")
res = json.loads((data / f"scalp_results_{mode}.json").read_text())
FXM = {"XAUUSD", "XAGUSD", "EURUSD"}
for group, keep in [("20 stocks", lambda s: s not in FXM), ("gold/silver/EURUSD", lambda s: s in FXM)]:
    print(f"\n### {group} - {sys.argv[2]}  (net R after costs, trades)")
    tfs = sorted({int(k.split("|")[1]) for k in res})
    print(f"{'':18}" + "".join(f"{'M' + str(t):>16}" for t in tfs))
    rows = {}
    for k, v in res.items():
        sym, tf = k.split("|")
        if not keep(sym):
            continue
        for name, st in list(v["patterns"].items()) + [("LONG side", v["long"]), ("SHORT side", v["short"]),
                                                        ("ALL", v["all"]), ("ALL check-period", v["check"])]:
            cell = rows.setdefault(name, {}).setdefault(int(tf), [0.0, 0])
            cell[0] += st["net"]
            cell[1] += st["n"]
    for name, cells in rows.items():
        print(f"{name:18}" + "".join(f"{cells.get(t, [0, 0])[0]:+9.1f} ({cells.get(t, [0, 0])[1]:4})" for t in tfs))
