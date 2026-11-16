"""Backtest Classic Chart Patterns (app/signals/patterns.py) on exported 1H MT5 candles.

Usage (from backend/):
    .venv\\Scripts\\python.exe research\\export_h1.py research\\data
    .venv\\Scripts\\python.exe research\\backtest_patterns.py research\\data [capital] [risk%] [min_lot_max_risk%]

Trades exactly like the bot: entry at the signal candle close (buys pay the candle's spread),
broker stop/target at the signal's distances from the fill (long exits at bid, short at ask),
stop wins when a candle touches both, 150-bar time exit, opposite signal reverses.
Sizing: risk% of capital (compounding), rounded down to the lot step; when that is below the
minimum lot the minimum lot is used only if it risks <= min_lot_max_risk% of capital.
Period A = first year (used to pick symbols), period B = last year (unseen check).
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.signals.patterns import pattern_signals  # noqa: E402

data = Path(sys.argv[1])
CAPITAL = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0
RISK = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
MINLOT_MAX = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0
specs = json.loads((data / "symbols.json").read_text())
MAX_HOLD = 150


def usd_per_unit(sym, price):
    """$ P/L of 1 lot for a 1.0 price move."""
    s = specs[sym]
    return s["contract"] if s["profit"] == "USD" else s["contract"] / price


def run(sym):
    z = np.load(data / f"{sym}_60.npz")
    point = float(z["point"])
    bars = [dict(time=float(t), high=float(h), low=float(l), close=float(c))
            for t, h, l, c in zip(z["time"], z["high"], z["low"], z["close"])]
    spread = [float(x) * point for x in z["spread"]]
    sigs = pattern_signals(bars)
    split = bars[0]["time"] + 365 * 86400
    trades, pos = [], None

    def b_time(i):
        return bars[i]["time"]

    def close_pos(i, price, why):
        nonlocal pos
        side, entry, lots, risk_usd, sl_dist = pos["side"], pos["entry"], pos["lots"], pos["risk_usd"], pos["dist"]
        move = (price - entry) if side == "LONG" else (entry - price)
        trades.append(dict(sym=sym, t=pos["t"], side=side, pattern=pos["pattern"], why=why, r=move / sl_dist,
                           dist_usd_per_lot=sl_dist * usd_per_unit(sym, entry), exit_t=b_time(i),
                           period="A" if pos["t"] < split else "B"))
        pos = None

    for i, b in enumerate(bars):
        spr = spread[i]
        if pos and i > pos["i"]:
            if pos["side"] == "LONG":
                hit_sl, hit_tp = b["low"] <= pos["sl"], b["high"] >= pos["tp"]
            else:
                hit_sl, hit_tp = b["high"] + spr >= pos["sl"], b["low"] + spr <= pos["tp"]
            if hit_sl:
                close_pos(i, pos["sl"], "stop")
            elif hit_tp:
                close_pos(i, pos["tp"], "target")
            elif i - pos["i"] >= MAX_HOLD:
                close_pos(i, b["close"] + (spr if pos["side"] == "SHORT" else 0), "time")
        sig = sigs[i]
        if sig is None:
            continue
        if pos and pos["side"] == sig.side:
            continue
        if pos:
            close_pos(i, b["close"] + (spr if pos["side"] == "SHORT" else 0), "reverse")
        entry = b["close"] + (spr if sig.side == "LONG" else 0)
        dist = abs(sig.close - sig.stop)
        tgt = abs(sig.target - sig.close)
        if dist <= 0:
            continue
        pos = dict(i=i, t=b["time"], side=sig.side, entry=entry, dist=dist, pattern=sig.pattern,
                   sl=entry - dist if sig.side == "LONG" else entry + dist,
                   tp=entry + tgt if sig.side == "LONG" else entry - tgt, lots=None, risk_usd=None)
    return trades


def size_and_compound(trades):
    """Replay all symbols' trades in time order on one $CAPITAL account (approximation: one
    trade's result is booked at its entry time order)."""
    equity = CAPITAL
    taken = skipped = 0
    for t in sorted(trades, key=lambda x: x["t"]):
        s = specs[t["sym"]]
        # risk per lot = stop distance * $/unit; approximate stop distance from R: use stored dist
        lot_risk = t["dist_usd_per_lot"]
        budget = equity * RISK / 100
        lots = math.floor(budget / lot_risk / s["volume_step"] + 1e-9) * s["volume_step"]
        if lots < s["volume_min"]:
            if s["volume_min"] * lot_risk <= equity * MINLOT_MAX / 100:
                lots = s["volume_min"]
            else:
                t["sized"] = None
                skipped += 1
                continue
        t["sized"] = t["r"] * lots * lot_risk
        equity += t["sized"]
        taken += 1
    return equity, taken, skipped


def stats(rows):
    n = len(rows)
    if not n:
        return dict(n=0, w=0, l=0, wr=0.0, r=0.0, pf=0.0)
    wins = [x["r"] for x in rows if x["r"] > 0]
    losses = [x["r"] for x in rows if x["r"] <= 0]
    gl = -sum(losses)
    return dict(n=n, w=len(wins), l=len(losses), wr=100 * len(wins) / n, r=sum(x["r"] for x in rows),
                pf=(sum(wins) / gl) if gl > 0 else float("inf"))


all_trades = []
print(f"{'symbol':8} | {'A: trades W/L  win%  total R   PF':34} | {'B: trades W/L  win%  total R   PF':34}")
for sym in specs:
    tr = run(sym)
    # $ risk per lot for sizing, from the actual stop distance of each trade
    z = np.load(data / f"{sym}_60.npz")
    all_trades += tr
    a = stats([t for t in tr if t["period"] == "A"])
    b = stats([t for t in tr if t["period"] == "B"])
    fmt = lambda s: f"{s['n']:4} {s['w']:3}/{s['l']:<3} {s['wr']:5.1f}% {s['r']:+7.1f}R {s['pf']:5.2f}"
    print(f"{sym:8} | {fmt(a):34} | {fmt(b):34}")

picked = sys.argv[5].split(",") if len(sys.argv) > 5 else None
if picked:
    for period in ("A", "B"):
        rows = [dict(t) for t in all_trades if t["sym"] in picked and t["period"] == period]
        end, taken, skipped = size_and_compound(rows)
        st = stats([r for r in rows if r.get("sized") is not None])
        print(f"${CAPITAL:.0f} account, {RISK}% risk, period {period}: {taken} trades taken, {skipped} skipped "
              f"(min lot too big), {st['w']}W/{st['l']}L {st['wr']:.1f}%, end equity ${end:,.2f}")
out = Path(data / "pattern_trades.json")
out.write_text(json.dumps(all_trades))
print("saved", out)
