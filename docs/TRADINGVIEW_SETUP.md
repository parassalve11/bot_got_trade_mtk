# BYTEFX: simple TradingView setup

You need the single file `pine/bytefx_ut_multi_asset.pine`. No server or installation is needed for the strategy itself. The flow is: **chart → UT signal → risk checks → simulated entry + SL/TP → strategy report + optional alert**.

This version supports multiple chart symbols. “70% accuracy” means a target of 70 profitable trades out of every 100 closed trades. **No results have been measured yet, and no setting guarantees that target.** First get it running; then test one market at a time.

## 1. Open a chart

1. Sign in to TradingView and open a full chart / Supercharts.
2. Choose your exact symbol and data provider. For gold, search `XAUUSD` and choose the intended provider. Keep that same provider during comparisons.
3. Choose **Candles** as the chart type, using a time-based interval. Do not use a Heikin Ashi, Renko or range chart.
4. Start with **15 minutes** as a convenient test interval. It is not a proven best interval.

## 2. Add the script

1. Open `pine/bytefx_ut_multi_asset.pine` in a text editor.
2. Select all text and copy it, including the first line `//@version=6`.
3. In TradingView, open **Pine Editor** (its position can vary with the layout).
4. Create a new script, remove the example code, and paste the whole file. Do not paste Markdown fences.
5. Click **Save** and name it `BYTEFX UT Multi-Asset`.
6. Click **Add to chart**.
7. Confirm that there is no red compiler/runtime error. A blue UT line and BYTEFX panel should appear.
8. Open **Strategy Tester / Strategy report** below the chart to inspect results.

Pine strategies produce hypothetical trades through TradingView's broker emulator. Adding this script does not connect it to a live account. [TradingView strategy overview](https://www.tradingview.com/pine-script-docs/concepts/strategies/)

## 3. Use the initial settings

Click the strategy's settings cog. Start with these defaults to get a reproducible baseline:

| Setting | Initial value | Meaning |
|---|---|---|
| Sensitivity / UT ATR period | 6.4 / 2 | Values from your architecture; not optimized |
| Use Heikin Ashi signal close | Off | Real candle close drives signals |
| Trade direction | Long + Short | Both simulated directions allowed |
| Opposite UT signal | Close only | Close an existing trade; wait for a new cross to enter again |
| Equity risk per trade | 0.5% | Planned stop-distance risk before fees/slippage |
| Maximum notional / equity | 95% | Caps exposure without leverage |
| Quantity step override | 0 | Uses the symbol's minimum contract metadata |
| Initial stop method | ATR | Separate risk ATR, independent of UT ATR |
| Risk ATR / Stop multiplier | 14 / 2 | Initial stop distance = risk ATR × 2 |
| Take-profit method / Reward-risk | Risk : Reward / 1.5 | Target = 1.5 × rounded initial stop distance |
| Tighten stop with UT line | Off | Initial stop stays fixed |
| Optional filters | Off / 0 | Establish the unfiltered baseline first |
| Session and date restrictions | Off | Use loaded chart history |
| Daily loss/entry limit, cooldown | 0 | Disabled for initial comparison |

Then open **Properties**:

1. Set initial capital and account currency to your intended **simulation**.
2. Set commission and slippage to match the instrument/provider. The code's **0.05% per order and 2 ticks** are placeholders, not estimates for every market. Account for spread in the cost assumptions; it is not modeled separately by this script.
3. Keep margins at **100%** for this unleveraged version. Expensive futures may not fit the account.
4. Keep recalculation **on every tick** and **after order fills** off. Keep **fill on bar close** off. The script is designed for candle-close decisions and next-tick market fills.
5. Leave pyramiding at zero. The strategy holds at most one position in its symbol.

The Properties order-size control does not override this script's explicit risk-based quantity. For the meaning of margin, costs and execution settings, see [TradingView strategy properties](https://www.tradingview.com/support/solutions/43000628599-strategy-properties/).

## 4. Read the chart

- **Blue line:** UT signal trailing line. It is separate from the actual protective SL.
- **BUY / SELL triangle:** an entry was submitted at that candle's close. A triangle is not proof that the order filled.
- **TradingView trade arrow:** simulated fill, normally at the next candle's opening tick, adjusted by configured slippage.
- **Gray / red / green levels:** filled entry, active SL, active TP. Because calculations run at close, levels first appear when the filled position is observed at a candle close. An entry and exit inside the same candle can have trade arrows without visible levels; the bracket was still submitted with the entry.
- **Panel:** symbol/timeframe, UT state, last decision, current simulated position and historical performance. P/L and drawdown are in account currency.
- **Show raw UT crosses:** optional dots for underlying signals, including those blocked by entry filters.

The historical win rate is measured from closed simulated trades, not a confidence score or forecast.

## 5. Test another market

1. Save the baseline results in `docs/backtest-results.csv` (open in Excel or another spreadsheet).
2. Change the chart symbol, for example to a forex pair, a stock, or a crypto pair. The strategy reads that chart automatically; there is no gold-only symbol restriction.
3. Check costs, session, contract size, capital and short-selling assumptions again.
4. Run the same baseline before tuning. Record the provider as well as the symbol.
5. Keep separate results and alerts for each symbol/timeframe/settings combination.

| Market | Check before trusting results |
|---|---|
| Gold / forex | Quote provider, spread assumptions, trading hours and how chart units map to broker lots |
| Stocks | Whole-share minimums, regular/extended hours and whether the intended account can short |
| Crypto | Fractional quantity step; a simulated short does not imply spot shorting is available |
| Futures | Point value and minimum contract; the default exposure cap may skip all trades if one contract is too large |

This sizing model assumes a positive-price instrument with linear P/L represented by TradingView's point value. Inverse/quanto contracts and options require a separate sizing/execution model. Index feeds may be analytical rather than directly tradable. Portfolio exposure is not shared between charts: ten separate strategies can each consume their own risk budget.

## 6. Compare improvements toward your 70% target

The optional filters are experiments, not claims of better accuracy. Keep the same dates and costs while comparing one change at a time.

1. **Record the baseline.** Save closed trades, win rate, net profit, profit factor, maximum drawdown and average trade.
2. **Separate older and newer history.** Use an older segment for selecting settings and reserve a newer segment that you do not inspect while tuning. Enable the date window for each run; keep enough earlier chart bars loaded to warm up the indicators.
3. **Try a few UT settings.** For example, compare sensitivity `3`, `4.5`, `6.4`, and then ATR periods `2`, `7`, `14`. These are illustrative test values, not market-specific recommendations. Avoid an exhaustive search for one perfect result.
4. **Test higher-timeframe agreement separately.** On a 15-minute chart, try the 1-hour or 4-hour UT filter. The filter uses only the previous completed higher-timeframe candle and can miss early reversals.
5. **Test candle strength separately.** A minimum directional body/risk-ATR of `0.2`, for example, rejects small or wrong-direction candles. Keep it only if the held-out results support it.
6. **Compare exits.** Try reward/risk `1`, `1.5`, and `2` independently. Optionally test UT trailing with TP off. Do not widen losses just to manufacture more winners.
7. **Freeze settings and run the reserved period.** If you retune after seeing it, it is no longer unseen data; reserve another period.
8. **Forward-test with simulated trades and alerts.** Check actual observed fill timing, costs and missed/repeated events before considering a broker bridge.

Aim for a meaningful sample (for example, at least 100 closed trades in a held-out run, and preferably substantially more across conditions). This is a practical comparison threshold, not proof. Seventy wins out of 100 is still an uncertain estimate; correlated trades and changing market conditions make future performance less predictable.

A high win rate can lose money: `0.70 × 0.3R − 0.30 × 1R = −0.09R` per trade before costs. Track profitability and drawdown alongside win rate. An acceptable result needs positive net expectancy after costs and losses you can tolerate; 70% by itself is not an acceptance criterion.

## 7. Create an alert

Do this after choosing and saving settings:

1. In Inputs, choose a distinct **Alert instance tag**, such as `gold15-test-a`. Use a different tag for another configuration.
2. Click **Create alert**.
3. In **Condition**, select `BYTEFX UT Multi-Asset v1.0`.
4. Select **Order fills only**, if that choice is shown. This script uses fill alerts and has no separate `alert()` stream.
5. Check the **Message** field. It should contain the JSON template below. If needed, copy the entire line from `examples/order-fill-alert.json.txt`.
6. Enable the desired app/browser notification. For notification-only use, leave the webhook URL empty.
7. Create the alert. Wait for a new realtime simulated order fill; historical arrows do not trigger a new alert.

```json
{"context":{{strategy.order.alert_message}},"fill_price":{{strategy.order.price}},"action":"{{strategy.order.action}}","contracts":{{strategy.order.contracts}},"position":"{{strategy.market_position}}","position_size":{{strategy.market_position_size}},"previous_position":"{{strategy.prev_market_position}}","sent_at":"{{timenow}}"}
```

This is a **template**, so it becomes valid JSON only after TradingView substitutes the placeholders. Do not add quotes around `{{strategy.order.alert_message}}`; it expands to an object.

Alerts run on TradingView's servers with a saved snapshot of the script, inputs, symbol and timeframe. **Delete and recreate the alert after changing those settings or updating the code.** Check availability/limits in your account. [TradingView alerts documentation](https://www.tradingview.com/pine-script-docs/concepts/alerts/)

## 8. Understand the alert before using a webhook

The `context` object contains the strategy version, instance tag, exchange-qualified symbol, timeframe, trade ID, event ID, original signal timestamp, reference price, stop/target distances in ticks and optional absolute SL/TP.

- `fill_price` is the **TradingView simulated fill**, not a broker confirmation.
- `reference_price` is the signal candle close, never a promised fill.
- Entry/reversal messages have `stop_loss` and `take_profit` set to JSON `null`. The relative ticks are known; actual fill-based price levels are not yet available to the script. A same-candle exit can also have null absolute levels.
- Compute initial levels from entry fill `E`, tick size `t`, loss ticks `L`, target ticks `P`: long SL `E − L×t`, TP `E + P×t`; short SL `E + L×t`, TP `E − P×t`. A null target means TP off.
- `stop_ticks` always describes initial risk, even after a trailing stop tightens. Updated `stop_loss` describes the last absolute stop sent to the emulator.
- Events are `entry`, `reverse`, `stop_loss`, `take_profit`, `opposite_signal`, `daily_loss`, or `date_end`.
- `context.side` identifies the trade direction. `action` identifies the filled transaction: closing a LONG is a sell.
- A reversal's `contracts` includes closing the old position plus opening the new one. Use `position` and `position_size` to understand the resulting target position. See [TradingView strategy alert placeholders](https://www.tradingview.com/support/solutions/43000481368-strategy-alerts/).
- Event IDs combine version, instance, symbol, timeframe, entry signal timestamp, direction and event type. A future receiver must deduplicate by instance/event ID and reconcile actual positions.

No broker bridge is included. Pine strategy orders do not automatically become orders in TradingView Paper Trading or a connected live broker account. The strategy itself is your initial simulation.

For later automation, use an execution service with broker symbol/lot mapping, authentication, replay checks, position reconciliation and broker-held protection. This version emits order fills, **not stop-modification events**: a bridge cannot mirror the UT trailing stop solely from these messages. It must implement that trailing logic or receive an explicitly added update stream. Broker protective orders should be created from broker-confirmed entry fills rather than waiting for a future TradingView stop alert.

TradingView webhooks require two-factor authentication; supported ports are 80/443, the receiver must respond within three seconds, and delivery can fail. These are reasons to reconcile positions rather than assume a webhook is guaranteed execution. [TradingView webhook requirements](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)

## 9. Troubleshooting

| What you see | What to check |
|---|---|
| Compile error after pasting | Include all lines; first line must be `//@version=6`; do not include Markdown fences. Record the exact error and line if it persists. |
| Standard chart runtime error | Switch the chart type to Candles; use the script's HA input if you want HA-derived signals. |
| Higher-timeframe error | Set the HTF above the chart interval, or turn that filter off. |
| Quantity-step error | Use 0 for the symbol default, or a positive multiple of its minimum contract size. |
| No trades | Read “Last decision”; temporarily disable filters/session/dates, load more history, and inspect raw UT crosses. |
| “Size / stop invalid” | Risk budget/exposure cap may be below one minimum contract, or conversion metadata may be unavailable. Do not force a larger size just to produce trades. |
| Triangle but no fill | The next tick may not have arrived, or a gap/cost may make the order unaffordable. Check Properties and the trade report. |
| Order size differs across symbols | Contract point value, currency conversion, price, risk distance and quantity rounding differ. Chart units are not interchangeable broker lots. |
| SL or TP differs from signal estimate | Initial levels use the filled entry, with distances rounded up to whole ticks. Gaps/slippage affect fills. |
| Too many/few signals | Check UT sensitivity, ATR, timeframe and raw crosses before adding filters. |
| Old settings in notifications | Delete the old alert and recreate it after saving the new configuration. |
| No notification from historical trades | Only new realtime fills trigger alerts. |
| Daily pause reset seems unexpected | It follows TradingView's exchange daily bars, not the chart display timezone or custom entry-session timezone. |

## 10. Acceptance checks in TradingView

These remain manual because this workspace has no TradingView/Pine runtime. Local JavaScript checks cannot prove Pine compilation or broker-emulator behavior.

1. **Compile:** add the complete file on a standard intraday chart with defaults; confirm no errors. Try a second market and a different timeframe.
2. **Long and short brackets:** in the trade list, find both directions. With trailing off, verify stop/target distances from actual entry match the rounded input-derived distances. Inspect an entry/exit within one bar if available.
3. **Gap behavior:** inspect a gap and verify relative protection is based on the filled entry. Remember stop execution can be worse than the specified stop.
4. **Quantity:** choose a trade, compute stop-distance loss × chart quantity × point value, convert to account currency, and compare with pre-entry equity × risk %. It should not exceed planned risk before costs under the initial conversion assumption. The notional cap/rounding may reduce it.
5. **Direction and opposite modes:** compare Long only, Short only, Close only, Close + reverse and Ignore. Blocked reversal entries should still close existing positions unless Ignore is selected.
6. **Trailing:** with UT trailing on, confirm long stops never decrease and short stops never increase within each trade.
7. **Restrictions:** set a small date window/session and a daily entry limit. Existing brackets must remain active outside entry times. Daily-loss pause should close at the next available tick after detection and reset next exchange day.
8. **Confirmed HTF:** enable a higher timeframe; refresh/reload and inspect historical crosses for stability. HTF gating uses `[1]` values with `lookahead_on`, so incomplete HTF candles are never treated as confirmed. [TradingView higher-timeframe request guidance](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/)
9. **Realtime alerts:** inspect one entry and one exit message, parse the substituted JSON, and check IDs, direction, fill, quantity and null fields. Check reversal messages separately if enabled.
10. **Record outcomes:** save the exact settings/costs, results and any error text. Do not label the strategy 70% accurate until actual held-out data supports the measured claim, and do not treat that measurement as a future guarantee.

## Implementation details and limits

- This is a fresh UT-style implementation. Your attachment described the algorithm but did not include the original indicator source, so visual/exact parity is not established.
- HA affects only the chart-timeframe signal close; ATR/risk/body filters use regular candles. The optional HTF UT filter always uses regular candles.
- UT distance mode measures the distance from the signal close to the UT line, then anchors that distance to the eventual entry fill. It does not promise the initial SL will equal the signal-time UT price after a gap.
- Initial stop ticks are rounded up, then used for sizing and R:R. Quantity is rounded down. Currency conversion is delegated to TradingView; fees, spread, stop slippage and conversion changes can make realized loss exceed planned risk.
- The 95% notional cap is estimated at the signal close, not enforced at the unknown fill price. Large gaps can change exposure or reject orders. Pending order state is separate from filled position state; existing brackets remain attached during attempted reversals.
- Daily entry count means entry **submissions**, including reversals and orders later rejected. The cooldown also starts on submission. It is not a count of closed or winning trades.
- Daily loss uses equity including open P/L, checked at close, and latches until the next exchange daily bar. It is a pause mechanism, not a guaranteed intraday loss ceiling. On daily/weekly charts this is coarse; use intraday charts for daily controls.
- Sessions govern new signal submissions and leave open trades protected; there is no forced end-of-session liquidation. Align session boundaries to chart intervals. An order submitted on the last session candle can fill outside the session.
- The date end requests a market close on the first calculated bar reaching that boundary; fill requires a later tick. If history ends with no next tick, a position can remain open. Signals outside the range are blocked, but loaded pre-window data still warms indicators.
- Historical OHLC cannot establish exact tick ordering. Use TradingView's higher historical detail / Bar Magnifier when available to inspect ambiguous fills. This changes simulation detail, not the strategy's signal rules.
- Runtime costs, live fills, broker order mapping, funding/borrow fees and external execution reliability remain outside this single-script V1. There is no martingale, pyramiding, machine-learning confidence score or built-in portfolio optimization.
