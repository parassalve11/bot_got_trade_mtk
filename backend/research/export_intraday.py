r"""Read-only: export intraday MT5 candles (M1, M2, M3, M5, M15) for the scalping backtests.

Usage (from backend/):
    .venv\Scripts\python.exe research\export_intraday.py research\data_intraday [days] [SYM,SYM,...]
Fetches in 20-day chunks (one big request fails with "Invalid params"). Times are kept in MT5
server time (EET) so a "day" matches the broker session / TradingView day. Saves
<SYMBOL>_<minutes>.npz and symbols.json.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, ".")
from app.config import get_settings  # noqa: E402

DEFAULT = ("AAPL,MSFT,NVDA,AMD,TSLA,AMZN,META,GOOGL,NFLX,INTC,AVGO,MU,PLTR,COIN,UBER,"
           "BA,JPM,XOM,ORCL,SMCI,XAUUSD,XAGUSD,EURUSD")
out = Path(sys.argv[1])
days = int(sys.argv[2]) if len(sys.argv) > 2 else 180
names = (sys.argv[3] if len(sys.argv) > 3 else DEFAULT).split(",")
TFS = {1: mt5.TIMEFRAME_M1, 2: mt5.TIMEFRAME_M2, 3: mt5.TIMEFRAME_M3, 5: mt5.TIMEFRAME_M5, 15: mt5.TIMEFRAME_M15}
out.mkdir(parents=True, exist_ok=True)
settings = get_settings()
if not mt5.initialize(settings.mt5_path):
    raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
end = datetime.now(timezone.utc) + timedelta(days=1)
specs_path = out / "symbols.json"
specs = json.loads(specs_path.read_text()) if specs_path.exists() else {}
try:
    for name in names:
        info = mt5.symbol_info(name)
        if info is None:
            print(name, "not offered by the broker")
            continue
        specs[name] = dict(path=info.path, contract=info.trade_contract_size, volume_min=info.volume_min,
                           volume_step=info.volume_step, point=info.point, tick=info.trade_tick_size,
                           base=info.currency_base, profit=info.currency_profit)
        for minutes, tf in TFS.items():
            parts, t = [], end - timedelta(days=days)
            while t < end:
                r = mt5.copy_rates_range(name, tf, t, min(end, t + timedelta(days=20)))
                if r is not None and len(r):
                    parts.append(r)
                t += timedelta(days=20)
            if not parts:
                print(f"{name:7} M{minutes}: no history {mt5.last_error()}")
                continue
            r = np.unique(np.concatenate(parts))
            vol = r["real_volume"] if r["real_volume"].sum() > 0 else r["tick_volume"]
            np.savez(out / f"{name}_{minutes}.npz", time=r["time"].astype("f8"), open=r["open"], high=r["high"],
                     low=r["low"], close=r["close"], volume=vol.astype("f8"), spread=r["spread"].astype("f8"),
                     point=info.point)
            first = datetime.fromtimestamp(float(r["time"][0]), timezone.utc).date()
            print(f"{name:7} M{minutes:<2} {len(r):7} candles from {first}")
finally:
    mt5.shutdown()
specs_path.write_text(json.dumps(specs, indent=1))
