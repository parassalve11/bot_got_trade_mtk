"""Per-symbol last-12-months results of research/backtest_patterns.py for config/backtests.json,
plus the latest signals (to compare with the TradingView chart).

Usage (from backend/, after backtest_patterns.py wrote research/data/pattern_trades.json):
    .venv\\Scripts\\python.exe research\\pattern_report.py research\\data [capital] [risk%] [min_lot_max_risk%]
"""

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.signals.patterns import pattern_signals  # noqa: E402

data = Path(sys.argv[1])
CAP = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0
RISK = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
MINLOT = float(sys.argv[4]) if len(sys.argv) > 4 else 5.0
specs = json.loads((data / "symbols.json").read_text())
trades = json.loads((data / "pattern_trades.json").read_text())
IST = timezone(timedelta(hours=5, minutes=30))

out = {}
for sym in specs:
    rows = sorted([t for t in trades if t["sym"] == sym and t["period"] == "B"], key=lambda t: t["t"])
    s = specs[sym]
    equity, peak, dd, results, skipped = CAP, CAP, 0.0, [], 0
    for t in rows:
        lots = math.floor(equity * RISK / 100 / t["dist_usd_per_lot"] / s["volume_step"] + 1e-9) * s["volume_step"]
        if lots < s["volume_min"]:
            if s["volume_min"] * t["dist_usd_per_lot"] > equity * MINLOT / 100:
                skipped += 1
                continue
            lots = s["volume_min"]
        pl = t["r"] * lots * t["dist_usd_per_lot"]
        results.append(pl)
        equity += pl
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    wins = [x for x in results if x > 0]
    losses = [x for x in results if x <= 0]
    total_r = sum(t["r"] for t in rows)
    start = datetime.fromtimestamp(rows[0]["t"], timezone.utc).date() if rows else None
    out["cp_" + sym.lower()] = dict(
        period=f"last 12 months (from {start})", trades=len(results), wins=len(wins), losses=len(losses),
        win_rate=round(100 * len(wins) / len(results), 1) if results else 0.0, net=round(sum(results), 2),
        gross_profit=round(sum(wins), 2), gross_loss=round(sum(losses), 2), max_drawdown=round(dd, 2),
        note=(f"MT5 1H candles, ${CAP:.0f} capital, {RISK}% risk (min lot allowed up to {MINLOT}%), "
              f"spread included. {len(rows)} signals, {skipped} skipped (min lot too big). "
              f"In R: {total_r:+.1f}R."),
    )
    print(f"{sym:7} {out['cp_' + sym.lower()]['trades']:3} trades {len(wins):3}W/{len(losses):<3} "
          f"{out['cp_' + sym.lower()]['win_rate']:5.1f}%  net ${sum(results):+8.2f}  maxDD ${dd:8.2f}  {total_r:+6.1f}R")

if len(sys.argv) > 5:
    Path(sys.argv[5]).write_text(json.dumps(out, indent=2) + "\n")
    print("wrote", sys.argv[5])

print("\nLatest signals (MT5 data; compare with the TradingView 1H chart):")
for sym in ("XAUUSD", "XAGUSD"):
    z = np.load(data / f"{sym}_60.npz")
    bars = [dict(time=float(t), high=float(h), low=float(l), close=float(c))
            for t, h, l, c in zip(z["time"], z["high"], z["low"], z["close"])][-3000:]
    for b, s in [(b, s) for b, s in zip(bars, pattern_signals(bars)) if s][-4:]:
        close_at = datetime.fromtimestamp(b["time"] + 3600, IST)
        print(f"  {sym} {close_at:%d %b %H:%M} IST  {'BUY ' if s.side == 'LONG' else 'SELL'} {s.pattern:28} "
              f"close {s.close:.2f} stop {s.stop:.2f} target {s.target:.2f}")
