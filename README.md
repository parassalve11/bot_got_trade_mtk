# BYTEFX TradingView → MT5 Auto Trader

An integrated Pine v6 strategy, authenticated FastAPI webhook receiver, SQLite execution journal/queue, and single-account MT5 worker for Windows. Includes broker risk sizing, attached SL/TP, close/reverse handling, account/position ownership checks, restart reconciliation, local administration, and Caddy/Windows deployment files.

**Start here: [the complete Windows + MT5 + TradingView setup guide](docs/MT5_SETUP.md).**

**No paid TradingView plan?** The worker can generate the same UT Bot signals from MT5 candles: see [the built-in signal engine](docs/SIGNAL_ENGINE.md). For strategy inputs/backtesting, use [the TradingView guide](docs/TRADINGVIEW_SETUP.md).

```text
TradingView Pine v1.1 → HTTPS/Caddy → FastAPI → SQLite queue
                                                ↓
                                      Worker → risk checks → MT5 → broker
```

The code is built together, not split into future implementation phases. Tests exercise the HTTP-to-execution flow with a deterministic simulated broker. TradingView compilation, broker-specific demo execution, VPS startup and HTTPS deployment still require your account/domain configuration. No live trades have been submitted, and no win rate is claimed.

## Start locally

On Windows with 64-bit Python 3.11:

```powershell
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m app.cli check
.\.venv\Scripts\python.exe -m app.cli api
```

In another terminal:

```powershell
.\.venv\Scripts\python.exe -m app.cli worker
```

Setup generates distinct local secrets in `.env` without printing them. It defaults to **DISABLED**, and symbol mappings default to disabled. Follow the guide to enter your demo account and exact broker symbols. The API binds to `127.0.0.1:8000`; Caddy is the public HTTPS boundary.

## Main files

| Path | Purpose |
|---|---|
| `pine/bytefx_ut_multi_asset.pine` | Strategy and v1.1 alert contract |
| `app/api/` | Authenticated intake and health/status endpoints |
| `app/database.py` | Durable queue, duplicates, operation journal and positions |
| `app/trading/` | Official MT5 adapter, risk, execution, ownership and reconciliation |
| `app/cli.py` | Setup, launch, pause/resume, review and backup |
| `.env.example`, `config/symbols.json` | Account/risk settings and symbol mapping |
| `deploy/Caddyfile`, `scripts/` | HTTPS and Windows startup helpers |
| `docs/MT5_SETUP.md` | Complete installation and operating instructions |
| `docs/EXECUTION_CONTRACT.md` | Event semantics, recovery behavior and limits |
| `docs/backtest-results.csv` | Strategy comparison worksheet |

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check app tests/python
node --test tests/strategy-contract.test.cjs
```

`requirements.lock.txt` records the dependencies used for local Windows testing. Node checks extracted Pine helper expressions; it does **not** compile Pine. See [validation coverage](docs/VALIDATION.md).

Broker-held fixed SL/TP owns protection. Pine's simulated SL/TP events are audit-only. MT5 execution mode rejects Pine UT trailing because this contract does not stream trailing-stop updates. Unknown broker outcomes are reconciled or held for review, never blindly resent. Use one deployment per account and keep its database intact.
