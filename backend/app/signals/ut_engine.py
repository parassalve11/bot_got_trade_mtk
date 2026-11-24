"""Pure UT Bot signal maths, ported line-by-line from pine/bytefx_ut_multi_asset.pine.

No MT5, database or clock access here, so the logic can be tested deterministically.
Pine `na` is represented by float NaN; Pine comparisons with na are false, which is
also how Python compares NaN, and Pine math.max/min with na return na (see _max/_min).
"""

import bisect
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.signals.asianbreak import BreakoutSettings
from app.signals.meanrev import MeanRevSettings
from app.signals.patterns import PatternSettings

NA = float("nan")
TIMEFRAME_SECONDS = {"1": 60, "5": 300, "15": 900, "30": 1800, "60": 3600, "240": 14400}


class StreamConfig(BaseModel):
    """One symbol/timeframe strategy instance. Defaults equal the Pine input defaults."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    enabled: bool = True
    instance: str = Field(default="engine", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    tv_symbol: str = Field(min_length=3, max_length=64)  # Key in config/symbols.json
    timeframe: Literal["1", "5", "15", "30", "60", "240"] = "15"
    sensitivity: float = Field(default=6.4, gt=0)
    atr_length: int = Field(default=2, ge=1, le=500)
    risk_atr_length: int = Field(default=14, ge=1, le=500)
    stop_mode: Literal["ATR", "UT distance", "Fixed %", "Price distance"] = "ATR"
    stop_atr: float = Field(default=2, gt=0)
    stop_percent: float = Field(default=1, gt=0)
    stop_price: float = Field(default=10, gt=0)
    target_mode: Literal["Risk : Reward", "ATR", "Fixed %", "Off"] = "Risk : Reward"
    reward_ratio: float = Field(default=1.5, gt=0)
    target_atr: float = Field(default=3, gt=0)
    target_percent: float = Field(default=1.5, gt=0)
    direction: Literal["Long + Short", "Long only", "Short only"] = "Long + Short"
    opposite_mode: Literal["Close + reverse", "Close only", "Ignore"] = "Close only"
    risk_percent: float = Field(default=0.5, gt=0, le=100)
    history_bars: int = Field(default=1000, ge=200, le=5000)
    # Pine "Require higher-timeframe UT agreement": entries only with the previous COMPLETED
    # 4H candle's close vs its UT line (same UT settings). Closes are never filtered.
    htf_filter: Literal["none", "240"] = "none"
    # Record signals only, even when ENGINE_MODE=trade (for streams still being evaluated).
    watch_only: bool = False
    # "ut" = UT Bot (fields above); "patterns" = Classic Chart Patterns (app/signals/patterns.py,
    # settings in `patterns`; stop/target come from the pattern, the UT fields are ignored).
    # "meanrev" = 15-minute RSI(2) mean reversion (app/signals/meanrev.py, settings in `meanrev`).
    # "breakout" = gold Asian-range breakout (app/signals/asianbreak.py, settings in `breakout`).
    strategy: Literal["ut", "patterns", "meanrev", "breakout"] = "ut"
    patterns: PatternSettings = Field(default_factory=PatternSettings)
    meanrev: MeanRevSettings = Field(default_factory=MeanRevSettings)
    breakout: BreakoutSettings = Field(default_factory=BreakoutSettings)

    @property
    def seconds(self) -> int:
        return TIMEFRAME_SECONDS[self.timeframe]

    @property
    def group(self) -> str:
        """Dashboard section: "intraday" (below 1 hour, e.g. 15-minute scalps) or "swing"."""
        return "intraday" if self.seconds < 3600 else "swing"


def load_streams(path: Path) -> list[StreamConfig]:
    streams = TypeAdapter(list[StreamConfig]).validate_python(json.loads(path.read_text("utf-8")))
    keys = [(s.instance, s.tv_symbol) for s in streams if s.enabled]
    if len(keys) != len(set(keys)):
        raise ValueError("Each enabled engine stream needs a unique instance + tv_symbol")
    return streams


def _na(value: float) -> bool:
    return value != value


def _max(a: float, b: float) -> float:
    return NA if _na(a) or _na(b) else max(a, b)


def _min(a: float, b: float) -> float:
    return NA if _na(a) or _na(b) else min(a, b)


def true_range(highs, lows, closes) -> list[float]:
    """ta.tr(true): high-low when the previous close is unavailable."""
    values = []
    for i, (high, low) in enumerate(zip(highs, lows)):
        if i == 0:
            values.append(high - low)
        else:
            prev = closes[i - 1]
            values.append(max(high - low, abs(high - prev), abs(low - prev)))
    return values


def rma(values, length: int) -> list[float]:
    """ta.rma: seeded with ta.sma(src, length) while the previous value is na."""
    alpha = 1 / length
    out, previous = [], NA
    for i, value in enumerate(values):
        if _na(previous):
            window = values[i + 1 - length : i + 1] if i + 1 >= length else []
            current = NA if not window or any(_na(v) for v in window) else sum(window) / length
        else:
            current = alpha * value + (1 - alpha) * previous
        out.append(current)
        previous = current
    return out


def atr(highs, lows, closes, length: int) -> list[float]:
    return rma(true_range(highs, lows, closes), length)


def ut_stops(src, atr_values, sensitivity: float) -> list[float]:
    """Pine f_ut(): ATR trailing stop that ratchets with the trend."""
    out, stop = [], NA
    for i, value in enumerate(src):
        loss = sensitivity * atr_values[i]
        previous = 0.0 if _na(stop) else stop  # nz(stop[1], 0)
        prior_src = src[i - 1] if i > 0 else NA
        if value > previous and prior_src > previous:
            stop = _max(previous, value - loss)
        elif value < previous and prior_src < previous:
            stop = _min(previous, value + loss)
        else:
            stop = value - loss if value > previous else value + loss
        out.append(stop)
    return out


@dataclass(frozen=True)
class BarSignal:
    side: str  # LONG or SHORT
    close: float
    loss_ticks: float
    profit_ticks: float | None


def signal_series(bars: list[dict], cfg: StreamConfig, tick_size: float) -> list[BarSignal | None]:
    """Signal for every CLOSED bar in `bars` (oldest first). Never pass a forming bar."""
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    ut_atr = atr(highs, lows, closes, cfg.atr_length)
    risk_atr = atr(highs, lows, closes, cfg.risk_atr_length)
    stops = ut_stops(closes, ut_atr, cfg.sensitivity)
    result: list[BarSignal | None] = [None]
    for i in range(1, len(bars)):
        close, stop = closes[i], stops[i]
        # ta.crossover / ta.crossunder of close vs UT line.
        up = close > stop and closes[i - 1] <= stops[i - 1]
        down = close < stop and closes[i - 1] >= stops[i - 1]
        ready = not _na(stops[i - 1]) and not _na(risk_atr[i]) and risk_atr[i] > 0 and close > 0
        if not (ready and (up or down)):
            result.append(None)
            continue
        side = "LONG" if up else "SHORT"
        distance = {
            "ATR": risk_atr[i] * cfg.stop_atr,
            "UT distance": close - stop if up else stop - close,
            "Fixed %": close * cfg.stop_percent / 100,
            "Price distance": cfg.stop_price,
        }[cfg.stop_mode]
        if not distance > 0:
            result.append(None)  # Pine: "Skipped: size / stop invalid"
            continue
        loss_ticks = max(1, math.ceil(distance / tick_size - 1e-9))
        target = {
            "Risk : Reward": loss_ticks * tick_size * cfg.reward_ratio,
            "ATR": risk_atr[i] * cfg.target_atr,
            "Fixed %": close * cfg.target_percent / 100,
            "Off": None,
        }[cfg.target_mode]
        profit_ticks = None if target is None else max(1, math.ceil(target / tick_size - 1e-9))
        result.append(BarSignal(side, close, float(loss_ticks), None if profit_ticks is None else float(profit_ticks)))
    return result


def htf_series(htf_bars: list[dict], cfg: StreamConfig, htf_seconds: int = 14400):
    """(close times, direction +1/-1/0) for each CLOSED higher-timeframe candle, oldest first."""
    closes = [b["close"] for b in htf_bars]
    stops = ut_stops(closes, atr([b["high"] for b in htf_bars], [b["low"] for b in htf_bars], closes,
                                 cfg.atr_length), cfg.sensitivity)
    directions = [0 if _na(s) else 1 if c > s else -1 if c < s else 0 for c, s in zip(closes, stops)]
    return [b["time"] + htf_seconds for b in htf_bars], directions


def htf_direction_at(series, chart_close_time: float) -> int:
    """Pine request.security([close[1], line[1]], lookahead_on): the HTF candle BEFORE the one that
    contains this chart candle. A 4H candle closing at the same moment is not used yet."""
    close_times, directions = series
    k = bisect.bisect_left(close_times, chart_close_time) - 1
    return directions[k] if k >= 0 else 0


def decide(
    signal: BarSignal | None, position_side: str | None, cfg: StreamConfig, trend: int | None = None
) -> str | None:
    """Pine order logic: returns entry, reverse, close or None.

    `trend` is the higher-timeframe direction (+1/-1/0) when cfg.htf_filter is on; it gates
    entries only, exactly like Pine's buyQuality/sellQuality. Opposite signals still close.
    """
    if signal is None:
        return None
    allowed = cfg.direction == "Long + Short" or (
        cfg.direction == "Long only" if signal.side == "LONG" else cfg.direction == "Short only"
    )
    if cfg.htf_filter != "none":
        allowed = allowed and trend == (1 if signal.side == "LONG" else -1)
    if position_side is None:
        return "entry" if allowed else None
    if position_side == signal.side:
        return None  # pyramiding = 0
    if cfg.opposite_mode == "Close + reverse" and allowed:
        return "reverse"
    return "close" if cfg.opposite_mode != "Ignore" else None
