# Premium indicators (user-supplied, tested 2026-11-26)

Original TradingView scripts as received. Not used by the bot.

| File | What it is | Test result (MT5, real ticks, last 12 months) | Test code |
|---|---|---|---|
| `wolf_radar.pine` | "Wolfs Radar+": Ghost Scalp liquidity-sweep entries (TP 2000 / SL 500 pips) + Wolfs Radar dip signals | Ghost Scalp loses on gold and silver, 5m and 15m (e.g. gold 5m: 1607 trades, 17.1% win, -284.6R). Wolfs Radar: 0-8 signals in 2 years. The script hides stopped-out trades by default. | `research/wolf_radar.py`, `mql5/GhostScalp.mq5` |
| `lk-sniper.pine` | "LK Sniper" (MPL-2.0, Apex_ALGO5): trend-flip UP/DOWN with SL at EMA34 -/+ 1.15 ATR, TP 1/2/3R | Gold 15m -18.5R (577 trades, 29.1% win); gold 1h +0.5R; silver 1h -1.6R. 2 years on gold 15m was +51.7R but only from a few trending quarters (edge ~+0.06R/trade, smaller than quarterly luck). | `research/lk_sniper.py`, `mql5/LKSniper.mq5` |
