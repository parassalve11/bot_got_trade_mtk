# Classic Chart Patterns strategy (live since 2026-11-16)

Source: `pine/classic_chart_patterns.pine` (the TradingView indicator). Python port:
`app/signals/patterns.py`, line by line, default inputs. The bot acts on the same candles as
the chart's BUY / SELL labels:

| Item | Rule |
|---|---|
| Patterns | Head and Shoulders, Inverted H&S, Diamond Top/Bottom, Cup and Handle, Rounding Bottom, Symmetrical / Broadening / Ascending / Descending Triangle, Rising / Falling Wedge |
| Entry | 1H candle closes beyond the pattern line (not more than 1 ATR beyond it: "late breakout" is skipped) |
| Stop-loss | Pattern swing (e.g. right shoulder) − 0.2 ATR, at the broker |
| Target | 1 × pattern height, at the broker |
| Time exit | Closed after 150 candles (journal event `date_end`) |
| Opposite signal | Reverses the position |

Ties in `ta.pivothigh/low` (exactly equal highs) are resolved as "first bar counts"; TradingView
data (OANDA) also differs slightly from MetaQuotes data, so a rare pattern can differ from the chart.

## Account: $1,000 bot capital on the 100k demo

`.env`: `RISK_CAPITAL=1000` (capital = 1000 + bot P/L since set), 1% risk per trade
(`risk_percent` in config/engine.json), `MIN_LOT_MAX_RISK_PERCENT=5` (gold's 0.01 lot already
risks $15–50, so without this most gold trades would be skipped), total open risk 15%,
daily loss limit 10%, max 9 open trades.

## Backtest (MT5 1H candles, Nov 2024 – Nov 2026, spread included)

`research/export_h1.py` → `research/backtest_patterns.py` → `research/pattern_report.py`.
Symbols were picked on year 1; year 2 was unseen. Results in R (1R = the trade's stop):

| Symbol | Year 1 | Year 2 (unseen) |
|---|---|---|
| XAUUSD | 40 trades, 45% win, +12.0R | 47 trades, 47% win, **+22.4R** |
| XAGUSD | 52, 33%, −8.5R | 47, 23%, −7.1R |
| NVDA | 12, 33%, +9.9R | 12, 50%, +6.0R |
| AMD | 12, 33%, −0.2R | 13, 31%, −4.2R |
| USDCHF | 53, 40%, +4.5R | 55, 31%, −11.4R |
| GBPUSD | 52, 39%, +1.0R | 47, 32%, −4.4R |
| USDCAD | 44, 36%, −0.6R | 53, 38%, −0.4R |
| EURUSD | 45, 36%, −1.5R | 42, 31%, −0.7R |
| USDCNH | 54, 32%, −7.3R | 49, 43%, +15.2R |

Only gold was clearly positive in both years. The other symbols are near break-even as a group;
switch any of them to Watch on the dashboard (Strategies) to keep recording without trading.
