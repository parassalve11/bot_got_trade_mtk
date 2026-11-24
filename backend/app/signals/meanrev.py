"""15-minute mean reversion: Connors RSI(2) pullback (research/hiwin15.py, mql5/MeanReversion15.mq5).

BUY  when the candle closes above SMA200 and RSI(2) < `rsi_level` (oversold dip in an uptrend).
SELL when it closes below SMA200 and RSI(2) > 100 - `rsi_level`.
Stop  = `stop_atr` x ATR(14) from the entry, on the broker. No fixed target.
Exit  = first candle closing back above SMA5 (BUY) / below SMA5 (SELL), or after `max_hold` candles.

Tested 2026-05..11 in the MT5 Strategy Tester (real ticks) on XAGUSD M15, BUY only, rsi 5,
stop 2 ATR, 8 candles: 125 trades, 68.8% win, +13R. Small sample - running on demo first.
Pure maths (no MT5 / DB / clock); bars are CLOSED candles, oldest first.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MeanRevSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    trade_dir: Literal["Long & Short", "Long only", "Short only"] = "Long only"
    rsi_level: float = Field(default=5, gt=0, lt=50)
    stop_atr: float = Field(default=2.0, gt=0)
    max_hold: int = Field(default=8, ge=1, le=200)
    trend_len: int = Field(default=200, ge=10, le=1000)
    exit_len: int = Field(default=5, ge=2, le=100)


@dataclass(frozen=True)
class MeanRevState:
    close: float
    atr: float
    rsi: float
    trend: float        # SMA(trend_len)
    exit_ma: float      # SMA(exit_len)
    entry: str | None   # "LONG" / "SHORT" signal on this candle, or None

    def exit_for(self, side: str) -> bool:
        """True when an open trade of `side` should close on this candle."""
        return self.close > self.exit_ma if side == "LONG" else self.close < self.exit_ma

    def stop_for(self, side: str, stop_atr: float) -> float:
        return self.close - stop_atr * self.atr if side == "LONG" else self.close + stop_atr * self.atr


def _rma_last(values, n):
    if len(values) < n:
        return None
    v = sum(values[:n]) / n
    for x in values[n:]:
        v = (x + (n - 1) * v) / n
    return v


def meanrev_state(bars: list[dict], cfg: MeanRevSettings | None = None) -> MeanRevState | None:
    """Indicators and signal on the newest closed candle (None until enough history)."""
    cfg = cfg or MeanRevSettings()
    if len(bars) < max(cfg.trend_len, 30) + 1:
        return None
    C = [b["close"] for b in bars]
    H = [b["high"] for b in bars]
    L = [b["low"] for b in bars]
    d = [0.0] + [C[i] - C[i - 1] for i in range(1, len(C))]
    up = _rma_last([max(x, 0.0) for x in d], 2)
    dn = _rma_last([max(-x, 0.0) for x in d], 2)
    rsi = 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)
    tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, len(C))]
    atr = _rma_last(tr, 14)
    trend = sum(C[-cfg.trend_len:]) / cfg.trend_len
    exit_ma = sum(C[-cfg.exit_len:]) / cfg.exit_len
    c = C[-1]
    entry = None
    if c > trend and rsi < cfg.rsi_level and cfg.trade_dir != "Short only":
        entry = "LONG"
    elif c < trend and rsi > 100 - cfg.rsi_level and cfg.trade_dir != "Long only":
        entry = "SHORT"
    return MeanRevState(c, atr, rsi, trend, exit_ma, entry)
