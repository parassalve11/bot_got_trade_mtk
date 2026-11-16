"""Read-only: export 1H candles (default ~2 years) of every MT5 Market Watch symbol.

Usage (from backend/):
    .venv\\Scripts\\python.exe research\\export_h1.py research\\data [days]
Saves <SYMBOL>_60.npz (UTC times) plus symbols.json with contract specs for the backtests.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, ".")
from app.config import get_settings  # noqa: E402

out = Path(sys.argv[1])
days = int(sys.argv[2]) if len(sys.argv) > 2 else 730
out.mkdir(parents=True, exist_ok=True)
settings = get_settings()
if not mt5.initialize(settings.mt5_path):
    raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
end = datetime.now(timezone.utc)
specs = {}
try:
    for info in [s for s in mt5.symbols_get() if s.visible]:
        rates = mt5.copy_rates_range(info.name, mt5.TIMEFRAME_H1, end - timedelta(days=days), end)
        if rates is None or not len(rates):
            print(info.name, "no history", mt5.last_error())
            continue
        np.savez(out / f"{info.name}_60.npz",
                 time=rates["time"].astype("f8") - settings.mt5_server_utc_offset_seconds,
                 open=rates["open"], high=rates["high"], low=rates["low"], close=rates["close"],
                 spread=rates["spread"].astype("f8"), point=info.point, tick=info.trade_tick_size)
        specs[info.name] = dict(path=info.path, contract=info.trade_contract_size, volume_min=info.volume_min,
                                volume_step=info.volume_step, point=info.point, tick=info.trade_tick_size,
                                base=info.currency_base, profit=info.currency_profit)
        first = datetime.fromtimestamp(float(rates["time"][0]), timezone.utc).date()
        print(f"{info.name:8} {len(rates):6} candles from {first}")
finally:
    mt5.shutdown()
(out / "symbols.json").write_text(json.dumps(specs, indent=1))
