# Built-in signal engine (no TradingView alerts needed)

The worker can generate the UT Bot signals itself from MT5 candles, so TradingView's paid
webhook alerts are optional. Signals enter the **same durable queue** as webhook alerts, so
every executor safeguard still applies: risk sizing from real equity, broker-held SL/TP,
daily loss/entry limits, duplicate protection, reconciliation and safety holds.

```text
MT5 closed candle → app/signals (UT Bot, ported from Pine) → SQLite queue → executor → MT5
```

## Modes (`.env`)

| `ENGINE_MODE` | Behaviour |
|---|---|
| `off` | Engine disabled (TradingView webhooks only). Default in `.env.example`. |
| `watch` | Signals are written to the audit log only. No orders. Use this first. |
| `trade` | Signals are queued and executed. |

Restart the worker after changing `.env` or `config/engine.json`.

## Strategy settings (`config/engine.json`)

A list of streams, one per symbol/timeframe. Field names and defaults mirror the Pine inputs
(`sensitivity` 6.4, `atr_length` 2, ATR stop ×2 on ATR 14, 1.5 R:R target, opposite signal
"Close only"). `tv_symbol` must be a key in `config/symbols.json`; entries also require that
symbol mapping to be `enabled`. `risk_percent` must not exceed `MAX_RISK_PERCENT`.

Not ported (Pine defaults are off): HTF filter, candle-body/ATR% filters, session/date
windows, cooldown, Heikin Ashi source and Pine's own daily limits. The server-side daily
loss and entry limits still apply.

## How it decides

- Only **closed** candles are evaluated; the forming candle is never used.
- A candle that closed more than 120 s ago (e.g. worker was down) is skipped, never traded late.
- Position state comes from the bot's own journal, not a simulation: flat + signal → entry;
  opposite signal → close (or reverse with `"Close + reverse"`); same side → ignored.
- Event IDs are derived from the candle close time, so a restart cannot double-trade a candle.
- Engine errors are logged and never stop the worker that manages open positions.

## Compare with TradingView before trading

```powershell
.\.venv\Scripts\python.exe -m app.cli engine-scan --bars 2000
```

Read-only; safe while the worker runs. Lists every UT signal (candle close time = when the
Pine strategy draws its arrow) and an approximate replay of trades. Compare with the Pine
strategy on a free TradingView chart of the same symbol/timeframe.

Expect most, not all, signals to match: TradingView's OANDA feed and the MetaQuotes-Demo
feed differ slightly. Prefer 15m/1h; 4h candles start at different times because the
broker server runs on UTC+2/+3. The replay ignores spread and commission and uses a small
sample; it is not a performance promise.

## Going live with the engine

1. Run in `watch` for a few days. Check signals with
   `python -m app.cli status` or the audit table (`engine_signal_watch_only`).
2. Set `ENGINE_MODE=trade` and restart the worker (`BYTEFX-worker` task).
3. If you stop using TradingView webhooks, disable the public endpoint:
   `tailscale funnel --https=443 off`.
