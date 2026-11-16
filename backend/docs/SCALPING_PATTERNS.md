# Scalping Patterns script: test results (2026-11-16)

Script: `pine/scalping_patterns.pine` (v2, fixed). Python port for testing: `app/signals/scalping.py`
(line by line, including the indicator's own trade: TP1 half + breakeven, TP2, time stop, pause
after a loss, daily -3R stop). **Not used by the live bot.**

## Test
- Data: MT5 candles, 21 May - 16 Nov 2026 (6 months, the most the broker keeps for 1-minute):
  20 US stocks (AAPL MSFT NVDA AMD TSLA AMZN META GOOGL NFLX INTC AVGO MU PLTR COIN UBER BA JPM XOM
  ORCL SMCI) + XAUUSD, XAGUSD, EURUSD, on 1, 2, 3, 5 and 15-minute charts.
- Costs: spread (at least the normal spread; stocks at least 0.02% of price), trades during
  very wide spread skipped. First 4 months = pick period, last 2 months = unseen check.
- Modes More trades / Balanced / Strict and 12 setting variants (time stop 60/120 min, no
  breakeven, TP1 0.5R / 1.5R, ADX 25, pattern subsets, long only, short only).
- Exits also replayed on 1-minute candles (the Pine rule "stop first when a candle touches both"
  is pessimistic): same result.

## Result: no stock / timeframe has an edge
Default settings, net R per trade after costs (all symbols of the group together):

| | M1 | M2 | M3 | M5 | M15 |
|---|---|---|---|---|---|
| 20 stocks | -0.17 | -0.14 | -0.12 | -0.11 | -0.09 |
| Gold, silver, EURUSD | -0.23 | -0.14 | -0.12 | -0.09 | -0.05 |

Results are negative even before costs (about -0.07R per trade on M5). No pattern, mode, direction
or variant was positive across stocks; at most 3 of 20 stocks were positive in both periods,
which is what chance gives. Best single cases (PLTR 5m, AVGO 15m, XAUUSD 15m Balanced) were
near zero or failed the unseen 2 months, so none is recommended for real money.

## Fixes in v2
1. Stop gapped through: filled at the candle open (v1 always counted exactly -1R: optimistic).
2. "Reverse the trade on an opposite signal": after a losing trade the 3-bar pause blocked the
   new opposite trade, so it only closed instead of reversing.
3. BUY / SELL only on a closed candle (`barstate.isconfirmed`): no flickering labels/alerts.
4. New input "Cost per trade" so the dashboard can show R after costs (v1: before costs only).

Scripts: `research/export_intraday.py`, `research/backtest_scalping.py`,
`research/scalp_breakdown.py`, `research/scalp_variants.py`, `research/scalp_m1_exits.py`.
