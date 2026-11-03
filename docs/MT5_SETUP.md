# Complete setup: TradingView → BYTEFX → MT5

The complete execution path is implemented in this repository. These are installation and configuration steps, not future development phases. Local tests use a simulated broker; your actual terminal, TradingView alerts and VPS still need demo verification.

## 1. Prerequisites

- Windows PC/VPS and one logged-in Windows user for both MT5 and the worker.
- 64-bit Python 3.11 with pip (the version family used for testing).
- Your broker's **MetaTrader 5** desktop terminal, demo login and server name.
- TradingView alert/webhook access and two-factor authentication.
- For public alerts: domain, public IPv4, Caddy for Windows, and reachable TCP 80/443.

Neither MT4 nor MT5 Manager API is used. Passwords stay locally in `.env`; never put them in Pine or an alert.

## 2. Install

Open PowerShell in the project:

```powershell
cd C:\projects2\auto_treading_bot
.\scripts\setup.ps1
```

If Python is not on PATH:

```powershell
.\scripts\setup.ps1 -Python 'C:\Path\To\Python311\python.exe'
```

This creates `.venv`, installs the recorded dependencies, and creates `.env` once with two different random tokens. Existing configuration is not overwritten. If local PowerShell scripts are blocked, use your approved execution policy or run the equivalent Python commands from the script manually.

## 3. Configure the demo terminal

1. Open your broker's MT5 and log in to the intended demo account.
2. Enable algorithmic trading and allow trading through the external Python API in MT5 settings.
3. Locate `terminal64.exe` and copy the exact broker server name.
4. Edit `.env` locally, keeping its generated tokens:

```dotenv
TRADING_MODE=DEMO
ALLOW_LIVE_TRADING=false
TRADING_ENABLED=false
MT5_PATH=C:\Program Files\Your Broker MT5\terminal64.exe
MT5_LOGIN=12345678
MT5_PASSWORD=your_actual_demo_password
MT5_SERVER=YourBroker-Demo
```

Replace the examples. A blank password can use terminal-saved credentials; the configured login/server must still match. Restrict `.env`, logs and database access to the operating Windows account and administrators. Git ignore rules do not provide filesystem security.

DEMO refuses real/contest accounts. LIVE requires both `TRADING_MODE=LIVE` and `ALLOW_LIVE_TRADING=true`, the expected account, and enabled trading. The project starts disabled; no live account has been used.

The official Python package communicates with the installed terminal. [MetaQuotes connection documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py)

## 4. Map exact symbols

Edit `config/symbols.json`. Example:

```json
{
  "OANDA:EURUSD": {
    "broker_symbol": "EURUSD.a",
    "enabled": true,
    "price_multiplier": 1.0,
    "max_spread_points": 30,
    "max_price_drift_percent": 0.25,
    "max_lot": 1.0
  }
}
```

The key must match the exchange-qualified TradingView symbol. `broker_symbol` must match MT5 Market Watch, including any suffix. The supplied EURUSD, GBPUSD and XAUUSD mappings begin disabled; enable only verified mappings.

`price_multiplier=1` means both feeds use the same price units. Change it only for a verified unit conversion, never to make different products appear equivalent. Spread limits use **broker points**, not pips or TradingView ticks. The sample limits need review for your broker.

## 5. Review server risk limits

```dotenv
MAX_RISK_PERCENT=0.50
MAX_TOTAL_RISK_PERCENT=2.00
MAX_DAILY_LOSS_PERCENT=3.00
MAX_DAILY_ENTRIES=10
MAX_OPEN_POSITIONS=5
MAX_LOT=1.0
MAX_MARGIN_FRACTION=0.80
MAX_DEVIATION_POINTS=20
RISK_COST_BUFFER_PERCENT=10
ALLOWED_INSTANCES=["main"]
ALLOWED_TIMEFRAMES=["15","60","240"]
```

Requests above the server risk cap are rejected. Volume is calculated from real account equity and broker `order_calc_profit`, rounded down to the broker step, then checked against margin and limits. An unaffordable minimum lot is skipped. The cost buffer is an allowance, not guaranteed protection against gap losses. [MetaQuotes profit calculation](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcprofit_py)

One position per broker symbol is enforced across strategy instances. Account position-count limits include manual positions/orders; aggregate stop-risk covers bot positions. Avoid competing EAs/manual trading on managed symbols, especially on netting accounts.

## 6. Check configuration and tests

With the worker stopped:

```powershell
.\.venv\Scripts\python.exe -m app.cli check
.\.venv\Scripts\python.exe -m app.cli check --mt5
.\.venv\Scripts\python.exe -m pytest
```

`check --mt5` connects and reads identity/symbol metadata without submitting trades. It may launch the configured terminal. It takes the exclusive worker lock. Confirm the expected masked account and `trade_allowed: true`.

It also checks enabled-symbol quote freshness and spread, reports `preflight_passed`
and `blockers`, and exits with code 1 if those checks or terminal trading permissions
fail. This is a connection/quote preflight, not proof that a broker will fill an order.
Keep `TRADING_ENABLED=false` until the preflight passes.

If quotes have a consistent server-clock offset from UTC, verify it against advancing
ticks and a correct UTC system clock, then set `MT5_SERVER_UTC_OFFSET_SECONDS` in
`.env`. The default is `0`. On the inspected MetaQuotes-Demo terminal on 2026-09-30,
the observed offset was `10800` (UTC+3). Do not assume this for other servers or dates.
The adapter subtracts this explicit offset from tick/deal timestamps and expands
history query bounds to cover UTC and server-clock conventions. Stale and future
quotes still fail the original freshness checks. Recheck after daylight-saving,
broker or server changes, and restart both processes after changing the setting.

The tests use temporary databases and a simulated broker; they do not load your `.env` account into MT5.

## 7. Set up Pine v1.1

Follow [the TradingView guide](TRADINGVIEW_SETUP.md) to paste `pine/bytefx_ut_multi_asset.pine` and add **BYTEFX UT Multi-Asset v1.1** to standard candles.

In Inputs:

1. Choose the UT/filter/exit settings for your test.
2. Keep **Tighten stop with UT line** OFF.
3. Enable **MT5 execution contract (broker owns fixed SL/TP)**.
4. Set risk at or below the server cap.
5. Set **Alert instance tag** to an exact allowed instance.
6. Use an allowed chart timeframe and symbol mapping.

Pine's quantity is only for simulation. Python ignores TradingView `contracts` when calculating broker lots.

Start with Pine and MT5 both **flat**. If Pine already has a simulated historical position, wait until flat or configure the date-window start for a future candle before creating the alert. An initial reversal referring to a historical trade the executor never opened is rejected.

Do not change inputs/instance tags while that broker trade is open. Pause entries, resolve positions, configure the new version and recreate the alert from flat. The worker does not adopt unknown trades to conceal state mismatches.

## 8. Start both processes

When the demo configuration is ready, set `TRADING_ENABLED=true` in `.env`. Restart both processes after editing `.env` or symbol mappings.

```powershell
# PowerShell window 1
.\scripts\run-api.ps1
```

```powershell
# PowerShell window 2
.\scripts\run-worker.ps1
```

Check:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/health'
.\.venv\Scripts\python.exe -m app.cli status
```

The API binds to loopback. `/health` is public-safe; detailed `/health/mt5` and `/api/v1/status` require `Authorization: Bearer <ADMIN_TOKEN>` and remain local through Caddy. The CLI is the easiest way to inspect detailed status without putting a token in shell history.

`degraded` can mean the worker/MT5 is unavailable, trading is paused, or review is required. The API can still save alerts when MT5 is unavailable. Old entry signals expire instead of trading hours later.

## 9. Configure public HTTPS

1. Get the official Windows Caddy binary and place it at `tools/caddy.exe`.
2. Point a DNS A record, such as `trade.yourdomain.com`, directly at the VPS public IPv4.
3. Replace `trade.example.com` in `deploy/Caddyfile` with your domain.
4. Permit TCP 80/443 in the provider and Windows firewall. Keep API port 8000 and Caddy admin port 2019 private.
5. Validate and run:

```powershell
.\tools\caddy.exe validate --config .\deploy\Caddyfile --adapter caddyfile
.\scripts\run-caddy.ps1
```

Caddy provides HTTPS when DNS/reachability are correct. Its configuration exposes `/health` and allowlisted TradingView webhook POSTs; detailed status and Swagger remain local. Access logging is off and runtime request URIs are redacted because the webhook token is in the path.

The TradingView sender IP list was checked on 2026-09-30; verify it again when deploying. Use DNS-only/direct routing. A CDN/proxy changes the peer IP and needs a deliberate trusted-proxy configuration; do not trust arbitrary forwarding headers. [Caddy request matching](https://caddyserver.com/docs/caddyfile/matchers#remote-ip)

## 10. Create the TradingView alert

1. Confirm the desired settings and a flat starting state.
2. Select **Create alert → BYTEFX UT Multi-Asset v1.1 → Order fills only**.
3. Use the complete message from `examples/order-fill-alert.json.txt` (normally prefilled).
4. Set webhook URL to:

```text
https://trade.yourdomain.com/api/v1/webhooks/tradingview/YOUR_WEBHOOK_TOKEN
```

Copy the actual `WEBHOOK_TOKEN` from `.env`. Never use the admin token or MT5 credentials here.

5. Save the alert and inspect its delivery log, BYTEFX status, and the MT5 Trade/History tabs on a new realtime event. Historical chart arrows are not replayed.

TradingView requires a quick webhook response and notes delivery can fail. The API commits to SQLite before HTTP 200; execution happens separately. [TradingView webhook requirements](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)

Alerts preserve a saved configuration. Recreate them after code, settings, symbol or timeframe changes. [TradingView alert snapshots](https://www.tradingview.com/pine-script-docs/concepts/alerts/)

## 11. Verify the demo behavior

- An entry becomes `QUEUED`, then `EXECUTED`; inspect its actual symbol, direction, lots and magic in MT5.
- SL is attached on entry; TP is attached when enabled. Fill-based levels are verified/adjusted.
- A duplicate webhook opens no additional trade.
- Pine `stop_loss` and `take_profit` events are `LOGGED`. Broker-held SL/TP controls actual protection.
- An explicit close affects only its identified owned trade.
- A reversal closes the previous position, confirms flat, then opens the opposite side.
- A failed/uncertain broker action can produce `REVIEW` and pause entries; inspect it rather than resending.

`EXECUTED` does not mean profitable. Broker and simulated exit times can differ. A new same-side signal while an actual position remains is ignored; an incompatible identity/reversal is rejected. Reset from flat after inspecting both sides instead of forcing synchronization.

## 12. Register Windows startup

After foreground operation is verified:

```powershell
.\scripts\register-tasks.ps1 -IncludeCaddy
```

This registers `BYTEFX-api`, `BYTEFX-worker` and optional `BYTEFX-caddy` for the current user. It does not immediately start tasks or overwrite existing ones. Stop foreground copies, then use Task Scheduler to start them. Logs are under `logs/`.

**Tasks start at user logon.** After reboot, log in as the configured Windows user. MT5 is a desktop terminal: this project does not promise unattended Session 0 support or store Windows auto-login credentials. Validate your VPS's session behavior; disconnect RDP instead of signing out. Reconnecting the terminal triggers broker reconciliation before entries resume.

One OS lock protects workers using the same database. Do not start another deployment/database against the same account/magic to bypass it.

## 13. Pause, recover, and back up

Pause new entries without removing broker protection:

```powershell
.\.venv\Scripts\python.exe -m app.cli pause --note 'Pausing entries for account maintenance'
.\.venv\Scripts\python.exe -m app.cli status
```

Closes and protective management can still operate during an entry pause. `TRADING_MODE=DISABLED` blocks all executor trading; already-held broker orders remain.

```powershell
.\.venv\Scripts\python.exe -m app.cli resume --note 'Maintenance complete and account checked'
```

A safety hold must be resolved before acknowledging it. A fresh clean worker reconciliation is required:

```powershell
.\.venv\Scripts\python.exe -m app.cli acknowledge-hold --note 'Broker position and protective orders inspected'
```

For an UNKNOWN OPEN without identifiable broker evidence, never delete the row or resend it. Stop the worker and inspect broker positions, orders and history. Only after establishing that no fill occurred:

```powershell
.\.venv\Scripts\python.exe -m app.cli resolve-no-fill '12:OPEN' --broker-checked --note 'Verified no position, order or deal with broker support'
```

This refuses matching broker evidence or any active position/order on that symbol, abandons/tombstones the event, and saves the operator note. It never resends the order. Restart the worker and resolve any remaining hold. Uncertain close/protection actions must be resolved from actual position state and reconciled; this command is limited to opens.

Create a consistent WAL-aware backup:

```powershell
.\.venv\Scripts\python.exe -m app.cli backup .\data\backups\trading-2026-09-30.db
```

Use a new filename. Do not copy only the main SQLite file while writes are active, delete the journal to clear an error, or restore old data and blindly replay alerts. Stop the worker for restores and reconcile with the broker before enabling entries.

## Troubleshooting

| Symptom | Check |
|---|---|
| 401 | Correct webhook token; not admin token |
| Public webhook 404 | Exact route and TradingView source IP; your own public IP is intentionally blocked |
| 422 | Updated Pine v1.1, full wrapper, MT5 contract enabled, allowed symbol/settings |
| 409 | Event ID reused with different data |
| 503 | Queue/database availability, disk space, backlog |
| RETRY | Known pre-send read/connection issue; retries and signal age are bounded |
| REVIEW | Inspect broker outcome and ownership; do not force resend |
| Requested risk above limit | Pine risk exceeds server cap |
| Risk below minimum lot | Smallest broker lot is too large for the budget |
| Stop violation | Requested distance fails broker/spread/stop rules |
| Previous-trade mismatch | Pine and MT5 are not synchronized to that trade ID; restart from flat |
| Ownership/volume changed | Manual or other-EA intervention, or partial result |
| Account binding mismatch | Database belongs to another account/server/magic |
| Worker active but no entries | Config, operator pause, daily limits or review hold |
| `stale_quote` with ticks hours in the future | Verify UTC clock and broker timestamp offset; do not increase freshness limits |
| `terminal_or_account_trading_disabled` | MT5 Algo Trading, external Python trading permission, and account trading permissions |
| No trading after reboot | Windows logon/session, task history, terminal and alert expiry |

See [execution semantics](EXECUTION_CONTRACT.md) and [validation coverage](VALIDATION.md). There is no measured 70% win-rate claim.
