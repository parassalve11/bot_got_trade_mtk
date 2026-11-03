"""Read-only: export ~1 year of MT5 candles for research/optimize_ut.py.

Usage (from the repository root):
    .venv\\Scripts\\python.exe research\\export_mt5_data.py research\\data XAUUSD XAGUSD
    .venv\\Scripts\\python.exe research\\optimize_ut.py research\\data research\\results.json
    .venv\\Scripts\\python.exe research\\analyze_ut.py research\\results.json
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, ".")
from app.config import get_settings  # noqa: E402

out, symbols = Path(sys.argv[1]), sys.argv[2:]
out.mkdir(parents=True, exist_ok=True)
settings = get_settings()
if not mt5.initialize(settings.mt5_path):
    raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
end = datetime.now(timezone.utc)
start = end - timedelta(days=372)
try:
    for symbol in symbols:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
        for tf, name in (("15", "TIMEFRAME_M15"), ("30", "TIMEFRAME_M30"), ("60", "TIMEFRAME_H1")):
            rates = mt5.copy_rates_range(symbol, getattr(mt5, name), start, end)
            if rates is None or not len(rates):
                raise SystemExit(f"No {symbol} {tf}m history: {mt5.last_error()}")
            np.savez(
                out / f"{symbol}_{tf}.npz",
                time=rates["time"].astype("f8") - settings.mt5_server_utc_offset_seconds,
                open=rates["open"], high=rates["high"], low=rates["low"], close=rates["close"],
                spread=rates["spread"].astype("f8"), point=info.point, tick=info.trade_tick_size,
            )
            print(symbol, tf, len(rates), "candles")
finally:
    mt5.shutdown()
