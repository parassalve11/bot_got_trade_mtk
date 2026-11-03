"""Detailed backtest report for one engine preset on exported MT5 candles.

Uses the live signal maths (app/signals/ut_engine.py). Fills at next candle open, broker
SL/TP checked on each candle (both hit in one candle = stop), fixed cost per round trip.
Usage: report_preset.py DATA_DIR SYMBOL TF START(YYYY-MM-DD) [END] --sens 2 --atr 1 --stop 3 --rr 3
"""

import argparse
import math
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, ".")
from app.signals.ut_engine import atr, ut_stops  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("data")
p.add_argument("symbol")
p.add_argument("tf")
p.add_argument("start")
p.add_argument("end", nargs="?")
p.add_argument("--sens", type=float, required=True)
p.add_argument("--atr", type=int, required=True)
p.add_argument("--stop", type=float, required=True)
p.add_argument("--rr", type=float, required=True)
p.add_argument("--cost", type=float, default=None, help="round-trip cost in price units")
p.add_argument("--equity", type=float, default=100000)
p.add_argument("--risk", type=float, default=0.5)
a = p.parse_args()

COST = {"XAUUSD": 0.30, "XAGUSD": 0.030}
CONTRACT = {"XAUUSD": 100, "XAGUSD": 5000}
cost = a.cost if a.cost is not None else COST.get(a.symbol, 0)
d = np.load(f"{a.data}/{a.symbol}_{a.tf}.npz")
b = {k: d[k] for k in d.files}
tick = float(b["tick"])
tf_sec = int(a.tf) * 60
start = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc).timestamp()
end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc).timestamp() if a.end else 1e12

c, h, lo, o, t = b["close"], b["high"], b["low"], b["open"], b["time"]
stops = np.array(ut_stops(c.tolist(), atr(h.tolist(), lo.tolist(), c.tolist(), a.atr), a.sens))
risk_atr = np.array(atr(h.tolist(), lo.tolist(), c.tolist(), 14))
n = len(c)


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M")


trades, pos = [], None


def exit_scan(side, fill, sl, tp):
    for i in range(fill, n):
        s_hit = lo[i] <= sl if side > 0 else h[i] >= sl
        t_hit = h[i] >= tp if side > 0 else lo[i] <= tp
        if s_hit or t_hit:
            return i, (sl if s_hit else tp), ("stop loss" if s_hit else "take profit")
    return None, None, None


def book(position, exit_index, price, why):
    r = ((price - position["entry"]) * position["side"] - cost) / position["dist"]
    trades.append({**position, "exit_i": exit_index, "exit": price, "why": why, "r": r})


for i in range(1, n - 1):
    up = c[i] > stops[i] and c[i - 1] <= stops[i - 1]
    dn = c[i] < stops[i] and c[i - 1] >= stops[i - 1]
    if pos and pos["exit_i"] is not None and pos["exit_i"] <= i:
        book(pos, pos["exit_i"], pos["exit_px"], pos["why0"])
        pos = None
    if not (up or dn) or math.isnan(stops[i - 1]) or not risk_atr[i] > 0:
        continue
    side = 1 if up else -1
    # Replay continuously from the start of the data so the position state on the first
    # report day is realistic; only trades filled inside the window are reported (below).
    if t[i] + tf_sec >= end:
        continue
    if pos and pos["side"] == side:
        continue
    if pos:  # opposite signal: close only
        book(pos, i + 1, o[i + 1], "opposite signal")
        pos = None
        continue
    loss_ticks = max(1, math.ceil(risk_atr[i] * a.stop / tick - 1e-9))
    tp_ticks = max(1, math.ceil(loss_ticks * a.rr - 1e-9))
    entry = o[i + 1]
    sl, tp = entry - side * loss_ticks * tick, entry + side * tp_ticks * tick
    e, px, why = exit_scan(side, i + 1, sl, tp)
    pos = dict(side=side, signal_i=i, fill_i=i + 1, entry=entry, sl=sl, tp=tp, dist=loss_ticks * tick,
               exit_i=e, exit_px=px, why0=why)
open_trade = pos
trades = [x for x in trades if t[x["fill_i"]] >= start]

one_r = a.equity * a.risk / 100
rs = np.array([x["r"] for x in trades])
print(f"\n=== {a.symbol} {a.tf}m | sens {a.sens} | UT ATR {a.atr} | stop {a.stop}x ATR14 | target {a.rr}R | "
      f"close-only ===")
print(f"Period: {stamp(start)} -> {stamp(min(end, t[-1] + tf_sec))} UTC | cost ${cost} per unit round trip | "
      f"1R = {a.risk}% of ${a.equity:,.0f} = ${one_r:,.0f}")
if not len(rs):
    raise SystemExit("No trades")
wins, losses = rs[rs > 0], rs[rs <= 0]
eq = np.cumsum(rs)
dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max())
streak = best = 0
for r in rs:
    streak = streak + 1 if r <= 0 else 0
    best = max(best, streak)
print(f"\nTrades {len(rs)} | Wins {len(wins)} | Losses {len(losses)} | WIN RATE {len(wins) / len(rs):.1%}")
print(f"Net {rs.sum():+.2f} R = ${rs.sum() * one_r:+,.0f}  ({rs.sum() * a.risk:+.1f}% of account)")
print(f"Profit factor {wins.sum() / -losses.sum():.2f} | Avg win {wins.mean():+.2f} R | Avg loss {losses.mean():+.2f} R"
      f" | Expectancy {rs.mean():+.3f} R/trade (${rs.mean() * one_r:+,.0f})")
print(f"Max drawdown {dd:.1f} R (${dd * one_r:,.0f}) | Longest losing streak {best}")
print(f"Exits: take profit {sum(x['why'] == 'take profit' for x in trades)}, stop loss "
      f"{sum(x['why'] == 'stop loss' for x in trades)}, opposite signal "
      f"{sum(x['why'] == 'opposite signal' for x in trades)}")
for label, side in (("Longs ", 1), ("Shorts", -1)):
    sub = np.array([x["r"] for x in trades if x["side"] == side])
    if len(sub):
        print(f"{label}: {len(sub):3d} trades, win {np.mean(sub > 0):.1%}, net {sub.sum():+.2f} R")
print("\nBy month:")
months = {}
for x in trades:
    months.setdefault(stamp(t[x["fill_i"]])[:7], []).append(x["r"])
for m, v in months.items():
    v = np.array(v)
    print(f"  {m}: {len(v):3d} trades, win {np.mean(v > 0):5.1%}, net {v.sum():+6.2f} R (${v.sum() * one_r:+,.0f})")
avg_dist = np.mean([x["dist"] for x in trades])
print(f"\nAverage stop distance ${avg_dist:.2f} -> about {one_r / (avg_dist * CONTRACT.get(a.symbol, 1)):.2f} lots "
      f"per trade at {a.risk}% risk")
print("\nTrade list (UTC):")
for k, x in enumerate(trades, 1):
    print(f"  {k:3d} {'BUY ' if x['side'] > 0 else 'SELL'} {stamp(t[x['fill_i']])} @ {x['entry']:.2f}  "
          f"SL {x['sl']:.2f} TP {x['tp']:.2f}  -> {stamp(t[x['exit_i']]) if x['exit_i'] < n else '?'} "
          f"@ {x['exit']:.2f}  {x['why']:<15} {x['r']:+.2f} R")
if open_trade and open_trade["exit_i"] is None:
    print(f"  open {'BUY' if open_trade['side'] > 0 else 'SELL'} since {stamp(t[open_trade['fill_i']])} "
          f"@ {open_trade['entry']:.2f} (SL {open_trade['sl']:.2f}, TP {open_trade['tp']:.2f})")
