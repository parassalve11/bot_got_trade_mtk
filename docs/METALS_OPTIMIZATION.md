# Gold and silver: 1-year walk-forward tuning (Nov 2026)

**Status: watch-only.** The presets below are recorded by the engine but do not trade until
you opt in (see the end of this page). The evidence is modest; read the caveats.

## Method

- Data: MetaQuotes-Demo MT5 candles, 27 Oct 2025 – 3 Nov 2026, XAUUSD and XAGUSD, 15m/30m/1h.
- **Train** 3 Nov 2025 – 2 Aug 2026 (≈9 months). **Test** 3 Aug – 3 Nov 2026 (≈3 months),
  never used for selection.
- 12,000 combinations per metal: timeframe, UT sensitivity, UT ATR period, stop (× ATR 14),
  reward:risk, opposite-signal mode, session filter.
- Signals use the live engine maths (`app/signals/ut_engine.py`). Fills at next candle open;
  SL/TP hit in the same candle counts as the stop. Cost per round trip: **$0.30/oz gold,
  $0.03/oz silver** (the demo's recorded spreads are unrealistically small).
- Selection: highest **neighbourhood-averaged** train score (expectancy ÷ volatility × √trades),
  i.e. settings whose neighbours also worked, not the single best result.
- Reproduce: `research/export_mt5_data.py` → `research/optimize_ut.py` → `research/analyze_ut.py`.

## Results (R = one trade's risk; 0.5% risk → 1 R = $500 on $100k)

| | Settings | Train (9 mo) | **Test (3 mo, unseen)** |
|---|---|---|---|
| Gold, old default 15m | sens 6.4, ATR 2, stop 2×, RR 1.5 | 188 trades, 40.4% win, +1.2 R | 65 trades, 41.5% win, +1.4 R |
| **Gold preset 1H** | sens 2.0, ATR 1, stop 3×, RR 3, close only | 156 trades, 41.0% win, +27.0 R, PF 1.64 | **51 trades, 39.2% win, +3.4 R, PF 1.22** |
| Silver, old default 15m | sens 6.4, ATR 2, stop 2×, RR 1.5 | 230 trades, 38.7% win, −16.2 R | 73 trades, 41.1% win, −3.0 R |
| **Silver preset 30m** | sens 4.0, ATR 10, stop 3×, RR 3, close only | 104 trades, 41.3% win, +28.1 R, PF 1.53 | **36 trades, 38.9% win, +5.2 R, PF 1.26** |

The win rate does **not** go up (≈39–41%). Profit comes from wider stops and 3:1 targets:
break-even at 3:1 is a 25% win rate. Session filtering (07–20 UTC) and "Close + reverse"
did not help.

## Caveats

- **Overfitting is visible.** Of the top 50 train-selected settings, only 10 (gold) and 19
  (silver) were profitable on the test period. The train results above overstate the edge;
  trust the test column more, and even that is only 36–51 trades.
- One year, one broker feed, demo spreads; no commission/swap. Gold 1H loses in some neighbours.
- TradingView (OANDA feed) will show slightly different signals.

## Using the presets

- **Pine v1.3:** Inputs → *Asset preset* → "Gold 1H" (1-hour chart) or "Silver 30m"
  (30-minute chart). Presets override the UT/stop/target/opposite inputs; other chart
  timeframes raise an error.
- **Engine:** `config/engine.json` streams `gold1h` and `silver30` with `"watch_only": true`.
  Signals appear in the audit log as `engine_signal_watch_only`.

To let a metal trade after a few weeks of acceptable watch results:

1. `config/symbols.json`: set that symbol's `"enabled": true`.
2. `config/engine.json`: set that stream's `"watch_only": false`.
3. `.env`: `ENGINE_MODE=trade`, then restart the `BYTEFX-worker` task.

Re-run the research every few months; markets change.
