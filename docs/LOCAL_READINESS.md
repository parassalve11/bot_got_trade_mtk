# Local demo readiness — 2026-09-30

The local API, worker and MT5 connection have been checked. Actual broker execution
and public TradingView webhook delivery have not yet been verified. No orders were sent.

Follow-up check: Algo Trading is now enabled. The read-only preflight returned
`trade_allowed: true`, `quote_ready: true`, `preflight_passed: true`, and no blockers.
The worker was restarted afterward; bot entries remain disabled. Steps 1 and 2 below
are complete. The next milestone is the public HTTPS webhook endpoint.

## Verified

- 84 Python tests and 8 Pine contract tests pass; Ruff and `pip check` pass.
- The Pine tests check the source contract; they do not compile the chart in TradingView.
- MT5 is connected to demo account ending 123 on MetaQuotes-Demo.
- `.env` now matches that account. It uses terminal-saved authentication successfully;
  passwords and webhook/admin tokens were not printed or replaced.
- Only OANDA:EURUSD is enabled, mapped to EURUSD. Minimum lot and step are both 0.01.
- API responds on `http://127.0.0.1:8000`; worker connects and reconciles successfully.
- Detailed status endpoints reject unauthenticated requests; Swagger is disabled.
- SQLite integrity is OK. The queue is empty, with no uncertain operations or safety hold.
- No broker positions or pending orders existed during inspection.
- Margin/profit calculations are available for EURUSD.
- The terminal's advancing ticks were consistently about 10800 seconds ahead of UTC.
  Explicit `MT5_SERVER_UTC_OFFSET_SECONDS=10800` now normalizes those timestamps.
  EURUSD passed the unchanged quote-age and spread checks after this adjustment.

## Remaining steps, in order

1. In MT5, enable **Algo Trading** on the toolbar. The account allows trading and
   external Python trading is already allowed, but the terminal-wide switch was off.
2. Recheck terminal permission. With the worker stopped, run:

   ```powershell
   .\.venv\Scripts\python.exe -m app.cli check --mt5
   ```

   Require `trade_allowed: true`, `quote_ready: true`, and `preflight_passed: true`.
   The check takes the worker lock, so do not run it alongside a running worker.
   It never sends an order. A passing preflight is not proof of a successful fill.
3. Keep `TRADING_MODE=DEMO` and `ALLOW_LIVE_TRADING=false`. Entries remain deliberately
   disabled with `TRADING_ENABLED=false` until the terminal and signal path are ready.
4. For the initial integration test, use this PC. Before connecting TradingView,
   configure a public HTTPS endpoint. This machine currently has no configured
   public hostname or Caddy binary; `deploy/Caddyfile` still has its example hostname.
   Localhost cannot receive TradingView's remote webhooks.
5. Check the actual chart: Pine v1.1, OANDA:EURUSD, standard candles, 15m, instance
   `main`, MT5 execution contract on, UT trailing off, and Pine/MT5 both flat.
6. Once the endpoint and demo terminal are ready, enable demo entries in `.env`
   and restart API/worker. Create the TradingView alert with **Order fills only**.
   Copy the exact message from `examples/order-fill-alert.json.txt`; an older pasted
   conversation contained a malformed version, so use the file.
7. Use `https://YOUR_HOST/api/v1/webhooks/tradingview/YOUR_WEBHOOK_TOKEN`.
   Copy the webhook token privately from `.env`. Never use the admin token or MT5
   credentials. Enable TradingView 2FA. Verify delivery, queued/executed event state,
   and the actual demo position with SL/TP on the first new signal.
8. Complete broker-level demo checks from `MT5_SETUP.md` before moving to a Windows
   VPS for continuous operation and registering startup tasks. Those checks include
   close/reverse, SL/TP, duplicates and restart recovery.

TradingView's current [webhook requirements](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)
allow ports 80/443, require 2FA, and impose a three-second response deadline.

## Current processes and monitoring

API and worker were left running in hidden background processes, with demo entries
disabled. They are not registered startup tasks. Do not launch duplicate copies.
Parent process IDs are recorded in `logs/local-processes.json`; Microsoft Store
Python also launches child interpreter processes. When restarting, stop the matching
API/worker process trees, not every Python process on the PC.

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/health'
.\.venv\Scripts\python.exe -m app.cli status
```

`status: degraded` is expected while entries are disabled. `api`, `worker`, and `mt5`
should all be `true`. Console logs are `logs/api-console.err.log` and
`logs/worker-console.err.log`; application logs use `.jsonl` files in that folder.

Recheck the broker UTC offset after daylight-saving or server changes. The explicit
offset does not infer historical DST transitions. Stale/future quote checks remain
enabled. The first real demo fill and recovery must still verify broker history behavior.

## Folder-copy error

The screenshot identifies `.pytest_cache`, which is disposable pytest cache data.
Skip that folder when copying. This checkout passed tests with cache creation disabled.
Do not copy `.venv` between computers; recreate it with `scripts/setup.ps1` on the
destination. Preserve `.env` privately and use the documented SQLite backup procedure
for the trading database.
