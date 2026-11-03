# Validation scope

Tests run against the actual API, schema, database, risk and execution code with a deterministic broker simulator. They do not initialize MT5 or submit broker orders. `requirements.lock.txt` records the Windows/Python 3.11 dependency versions used.

Coverage includes:

- HTTP → durable queue → worker execution; authentication, source checks, ignored forwarding headers, body limits, strict schemas, allowlists, duplicates/conflicts, timestamps and protected health/status.
- Broker-sized long/short entries, attached/fill-adjusted SL/TP, explicit exits, serial reversals, simulated SL/TP logging and no pyramiding.
- Risk, spread, stops, margin, minimum volume, price drift, daily-loss persistence, daily entry counts, demo/live refusal and account binding.
- Concurrent duplicate intake, symbol FIFO, WAL-aware backup and exclusive Windows worker locking.
- Manual/orphan positions, mixed netting ownership, broker protective exits, partial fills, failed stop changes and emergency closure.
- Crashes before send, after fill before result commit, and after response commit before position persistence; uncertain open/close/protection reconciliation without blind resend.
- The shipped `examples/order-fill-alert.json.txt` template rendered with TradingView-style placeholder values (entry → reverse → close) through HTTP to broker execution.
- Extracted Pine helper arithmetic/JSON through Node. This does not compile Pine or run a TradingView backtest.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check app tests/python
.\.venv\Scripts\python.exe -m compileall -q app
node --test tests/strategy-contract.test.cjs
```

Still required in your configured environment:

1. Compile Pine v1.1 in TradingView; inspect real alert substitution.
2. Connect the official MT5 adapter to the actual demo terminal and verify symbol/account/lot/filling metadata and protective order behavior.
3. Exercise demo entry, exit, reversal, outages and terminal/process/VPS restarts under the intended Windows user session.
4. Validate domain DNS, HTTPS, IP allowlisting and alert delivery to the VPS.
5. Check broker history/comment behavior for reconciliation and compare planned versus observed risk.
6. Measure strategy performance after costs using held-out and forward data. No 70% accuracy result is asserted.

A passing simulated-broker suite verifies implemented code paths; it cannot certify an untested broker or future trading performance.
