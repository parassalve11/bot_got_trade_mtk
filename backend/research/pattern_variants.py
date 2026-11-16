"""Compare Classic Chart Patterns settings variants on exported 1H MT5 candles.

Usage (from backend/, after research/export_h1.py):
    .venv\\Scripts\\python.exe research\\pattern_variants.py research\\data "Short only" 0.25,0.5,0.75,1.0

Same trade simulation as research/backtest_patterns.py (spread paid, stop first when a candle
touches both, 150-bar time exit, opposite signal reverses). $ results: $1000 capital, 1% risk,
minimum lot allowed up to 5% risk, compounding per symbol. Year 1 / year 2 = first / last 365 days.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.signals.patterns import PatternSettings, pattern_signals  # noqa: E402

data = Path(sys.argv[1])
direction = sys.argv[2] if len(sys.argv) > 2 else "Short only"
targets = [float(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "0.25,0.5,0.75,1.0").split(",")]
CAP, RISK, MINLOT = 1000.0, 1.0, 5.0
specs = json.loads((data / "symbols.json").read_text())
STOCKS = [s for s, v in specs.items() if "Stock" in v["path"]]


def load(sym):
    z = np.load(data / f"{sym}_60.npz")
    point = float(z["point"])
    bars = [dict(time=float(t), high=float(h), low=float(l), close=float(c))
            for t, h, l, c in zip(z["time"], z["high"], z["low"], z["close"])]
    return bars, [float(x) * point for x in z["spread"]]


def simulate(sym, bars, spread, cfg):
    s = specs[sym]
    per_unit = lambda price: s["contract"] if s["profit"] == "USD" else s["contract"] / price  # noqa: E731
    split = bars[0]["time"] + 365 * 86400
    sigs = pattern_signals(bars, cfg)
    trades, pos = [], None

    def close(i, price):
        nonlocal pos
        move = price - pos["entry"] if pos["side"] == "LONG" else pos["entry"] - price
        trades.append(dict(r=move / pos["dist"], lot_risk=pos["dist"] * per_unit(pos["entry"]),
                           year=1 if pos["t"] < split else 2))
        pos = None

    for i, b in enumerate(bars):
        spr = spread[i]
        if pos and i > pos["i"]:
            long = pos["side"] == "LONG"
            hit_sl = b["low"] <= pos["sl"] if long else b["high"] + spr >= pos["sl"]
            hit_tp = b["high"] >= pos["tp"] if long else b["low"] + spr <= pos["tp"]
            if hit_sl:
                close(i, pos["sl"])
            elif hit_tp:
                close(i, pos["tp"])
            elif i - pos["i"] >= cfg.max_hold:
                close(i, b["close"] + (0 if long else spr))
        sig = sigs[i]
        if sig is None or (pos and pos["side"] == sig.side):
            continue
        if pos:
            close(i, b["close"] + (0 if pos["side"] == "LONG" else spr))
        entry = b["close"] + (spr if sig.side == "LONG" else 0)
        dist, tgt = abs(sig.close - sig.stop), abs(sig.target - sig.close)
        if dist > 0:
            sgn = 1 if sig.side == "LONG" else -1
            pos = dict(i=i, t=b["time"], side=sig.side, entry=entry, dist=dist,
                       sl=entry - sgn * dist, tp=entry + sgn * tgt)
    return trades


def dollars(sym, rows):
    s = specs[sym]
    equity = CAP
    for t in rows:
        lots = math.floor(equity * RISK / 100 / t["lot_risk"] / s["volume_step"] + 1e-9) * s["volume_step"]
        if lots < s["volume_min"]:
            if s["volume_min"] * t["lot_risk"] > equity * MINLOT / 100:
                continue
            lots = s["volume_min"]
        equity += t["r"] * lots * t["lot_risk"]
    return equity - CAP


def summary(rows):
    w = sum(1 for t in rows if t["r"] > 0)
    return len(rows), w, len(rows) - w, sum(t["r"] for t in rows)


loaded = {sym: load(sym) for sym in specs}
results = {}
for tp in targets:
    cfg = PatternSettings(trade_dir=direction, tp_mult=tp)
    print(f"\n=== {direction}, target {tp}x pattern height ===")
    print(f"{'symbol':7} | {'2 years: trades W/L  win%    R     $':38} | {'year 2 only: trades W/L win%    R     $':40}")
    tot = dict(n=0, w=0, r=0.0, usd=0.0)
    for sym, (bars, spread) in loaded.items():
        tr = simulate(sym, bars, spread, cfg)
        y2 = [t for t in tr if t["year"] == 2]
        n, w, l, r = summary(tr)
        n2, w2, l2, r2 = summary(y2)
        usd, usd2 = dollars(sym, tr), dollars(sym, y2)
        results[(tp, sym)] = dict(n=n, w=w, l=l, r=r, usd=usd, n2=n2, w2=w2, l2=l2, r2=r2, usd2=usd2)
        tot["n"] += n; tot["w"] += w; tot["r"] += r; tot["usd"] += usd  # noqa: E702
        wr = 100 * w / n if n else 0
        wr2 = 100 * w2 / n2 if n2 else 0
        tag = " (stock)" if sym in STOCKS else ""
        print(f"{sym:7} | {n:4} {w:3}/{l:<3} {wr:5.1f}% {r:+6.1f}R {usd:+7.0f} | "
              f"{n2:4} {w2:3}/{l2:<3} {wr2:5.1f}% {r2:+6.1f}R {usd2:+7.0f}{tag}")
    print(f"{'ALL':7} | {tot['n']:4} trades, {100 * tot['w'] / max(1, tot['n']):.1f}% win, {tot['r']:+.1f}R, "
          f"${tot['usd']:+.0f} (sum of 15 separate $1000 runs)")

(data / "pattern_variants.json").write_text(json.dumps({f"{k[0]}|{k[1]}": v for k, v in results.items()}, indent=1))
