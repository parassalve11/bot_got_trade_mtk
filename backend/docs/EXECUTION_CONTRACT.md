# Execution contract and recovery behavior

## Pine contract v1.1.0

The API accepts the **full order-fill envelope**, not a bare signal. Use `examples/order-fill-alert.json.txt`. New fields inside `context`:

| Field | Meaning |
|---|---|
| `source` | Must be `tradingview` |
| `version` | Server allowlist defaults to `1.1.0` |
| `risk_percent` | Requested percentage of actual MT5 equity; bounded by server |
| `previous_trade_id` | Required for reversal; preceding trade in the same instance |
| `exit_owner` | `broker_fixed` required for executable entries/reversals |

The context also contains strategy, instance, event/trade IDs, original signal timestamp, exchange-qualified symbol, timeframe, direction, reference price, stop/target ticks, tick size and optional absolute SL/TP. `event_id` must equal `trade_id:event`. Numbers must be finite and appropriately positive; unknown fields and duplicate JSON keys are rejected.

The wrapper supplies `sent_at`, simulated fill/action/contracts and resulting/previous simulated position. `sent_at` requires a timezone. Wrapper quantity is diagnostic only. `reference_price` is used for cross-feed drift checks, not as a promised fill.

Freshness is checked at intake and before execution using `sent_at`. Entries also require a recent original signal timestamp. A week-old trade can validly close on a newly sent exit event. Identical duplicates return their saved status even when old; ID reuse with changed data returns 409.

## Event handling

| Event | Behavior |
|---|---|
| `entry` | Open flat; ignore same-instance same-side repeats; reject incompatible positions |
| `reverse` | Verify previous identity, preflight, close, confirm flat, recalculate, open opposite |
| `opposite_signal`, `daily_loss`, `date_end` | Close only the identified owned trade |
| `stop_loss`, `take_profit` | Log only; broker protection owns actual exits |

An unknown explicit close creates a tombstone so a delayed entry cannot reopen that trade. Same-side ignored entries are tombstoned too. One position per broker symbol applies across instances. Manual positions or working orders on the same symbol prevent entries.

Server mode, expected account, allowlists, pauses, daily limits, spread/drift, tick freshness, margin, max lot, aggregate bot risk and broker lot/stop rules cannot be bypassed by Pine. Account identity is checked again immediately before a broker send. The journal is bound to one account/server/magic.

## Broker protection

The opening request includes SL and optional TP based on the current broker quote and requested distances. Volume uses broker `order_calc_profit`, adverse-entry allowance and a cost buffer. Price levels use the broker tick grid; volume rounds down. Too-close stops or unaffordable minimum lots are rejected instead of forcing a trade.

Once the opening deal is identified, protection is recalculated from the actual fill, risk is checked, levels are modified if needed and the resulting position is verified. Excessive slippage/risk or definitive protection failure triggers emergency close and a review hold. During an outage a close itself may be uncertain; successful closure cannot be guaranteed without broker confirmation.

MT5 supports attached SL/TP; `order_check` is preflight rather than an execution guarantee. [Order requests](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py), [order checking](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py)

FOK is preferred; IOC is used when appropriate. Partial opens retain the actual protected volume without topping up. Partial closes stop reversal and require review. RETURN-only filling is excluded because it can leave a working remainder. [MetaQuotes filling policies](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants#enum_symbol_filling)

UT trailing remains available for Pine-only testing. MT5 mode rejects it because no stop-update stream is implemented. Python does not reproduce the UT signal algorithm or claim fixed broker exits match a trailing backtest.

## Journal and ordering

SQLite uses WAL, full synchronous commits, short transactions and unique `(instance,event_id)` keys. Intake commits before HTTP 200; a separate worker executes. FIFO is preserved per actual broker symbol, including aliases. Entry watermarks reject older signals within an instance/symbol. Review events do not block later explicit closes from reducing risk.

Events can finish `EXECUTED`, `IGNORED`, `LOGGED`, `REJECTED`, `FAILED`, or `REVIEW`. Known pre-send transient failures retry with bounded exponential delay while freshness allows.

Each side effect has an operation record: `PREPARED → SENDING → CONFIRMED/REJECTED/UNKNOWN`. The request and a short unique correlation comment are committed before `order_send`. Close, open and protection updates are distinct journal operations. Private journal metadata is removed before calling MT5.

If the worker dies after marking SENDING, that operation becomes UNKNOWN on restart and is **never blindly resent**. Reconciliation uses broker deals, positions and working orders to recover identifiable results. No evidence is not proof of no fill: ambiguous operations remain under review. Broker-rewritten comments or incomplete history can require operator inspection. This is not a mathematical exactly-once execution guarantee.

Broker positions are authoritative. Ownership checks include magic, position identifier, symbol, side, expected volume/entry and deal history. Tickets can change independently of position identifiers and are refreshed. Mixed manual/EA netting, orphan bot positions and unexpected working orders pause entries rather than being adopted or closed blindly. [MetaQuotes deal history](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py)

## Operating limits

- Use one Windows user, terminal/account and deployment/database per account. The OS lock coordinates workers sharing that database, not other machines/databases.
- Keep SQLite on local disk and retain dedupe history. Use the backup command. Old restores require explicit broker reconciliation before any new entry.
- Daily risk uses UTC and the first observed equity of that UTC day. The baseline and pause latch survive restart. A first mid-day installation cannot reconstruct earlier losses. Deposits, withdrawals and manual P/L affect equity. This sampled limit blocks new entries; it is not a guaranteed maximum loss or automatic account-wide liquidation.
- Daily entry limits count OPEN send attempts, including definitive broker rejections; preflight failures do not count. Aggregate stop-risk covers bot positions; position-count limits cover all positions/orders.
- An entry pause permits closes/protection/reconciliation. DISABLED blocks executor trading entirely; previously attached broker orders remain in place.
- Stops, deviation and cost allowances cannot bound realized losses through every gap/disconnection. There is no unprotected-entry fallback if attached stops are rejected.
- TradingView and broker fills can diverge. Trade IDs deliberately reject ambiguous synchronization. Start/reconfigure from flat; this is not a portfolio copier.
- Caddy must see the real sender IP. API forwarding headers are ignored. Do not publicly expose the loopback API/admin routes.
- Trading logs/audit records contain financial data. Protect them and the database, even though credentials and webhook paths are excluded from application access logs.
