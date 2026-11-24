"""Gold Asian-range breakout on 15-minute candles (research/gold_intraday.py "arb", mql5/AsianBreakout.mq5).

Range = high / low of the candles from `range_start` to `range_end` (MT5 server time, the time the
research used; London opens at 10:00 server time). The FIRST candle of the day that closes beyond
the range (from `range_end` until `entry_until`) decides: BUY above, SELL below, one trade a day.
Stop = middle of the range (or the other side). No target by default: the trade is closed on the
candle that ends `exit_hour` - `exit_early_min` (gold stops trading at 23:00 server time).

MT5 Strategy Tester (real ticks, Nov 2025 - Nov 2026): 181 trades, 49.7% win, +29.5R, worst
drawdown -11R; 2 years (M1 OHLC): 403 trades, +76R, profitable in both years.
Gold-led mode (`leader` set): research/silver_scalp.py - silver follows gold's breakout, stop
1.5 x half of silver's range, target 1R; MT5 real ticks 12 months: 189 trades, 56.1% win, +20.5R.
Pure maths. Bar times are the bot's UTC times; `server_offset` (seconds) turns them back into
MT5 server time (the client subtracted exactly this offset).
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BreakoutSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    range_start: int = Field(default=1, ge=0, le=23)
    range_end: int = Field(default=9, ge=1, le=24)
    entry_until: int = Field(default=17, ge=1, le=24)
    exit_hour: int = Field(default=23, ge=1, le=24)
    exit_early_min: int = Field(default=15, ge=0, le=120)
    stop_mode: Literal["middle", "opposite"] = "middle"
    target_r: float = Field(default=0, ge=0)          # 0 = no target, exit at the day end
    trade_dir: Literal["Long & Short", "Long only", "Short only"] = "Long & Short"
    min_range_bars: int = Field(default=8, ge=1)
    # Gold-led mode: the LEADER's (e.g. "OANDA:XAUUSD") first breakout gives the signal; this
    # symbol is traded in that direction with stop = stop_range_mult x half of ITS OWN range.
    leader: str | None = Field(default=None, min_length=3, max_length=64)
    stop_range_mult: float = Field(default=0, ge=0)   # 0 = stop at this symbol's range middle / side


@dataclass(frozen=True)
class BreakoutState:
    day: int                 # server-time day number of the newest closed candle
    close: float
    high: float | None       # Asian range (None until the range is complete)
    low: float | None
    entry: str | None        # "LONG" / "SHORT" on the first breakout candle of the day
    stop: float | None
    exit_now: bool           # this candle is the last one to hold a trade today


def breakout_state(bars: list[dict], seconds: int, server_offset: int,
                   cfg: BreakoutSettings | None = None) -> BreakoutState | None:
    """Evaluate the newest CLOSED candle. `bars` oldest first, `seconds` = candle length."""
    cfg = cfg or BreakoutSettings()
    if not bars:
        return None
    srv = [b["time"] + server_offset for b in bars]
    day = int(srv[-1] // 86400)
    today = [k for k in range(len(bars)) if int(srv[k] // 86400) == day]
    hour = lambda k: int((srv[k] % 86400) // 3600)  # noqa: E731
    last = bars[-1]
    close_sec = srv[-1] % 86400 + seconds
    exit_at = cfg.exit_hour * 3600 - cfg.exit_early_min * 60
    exit_now = close_sec >= exit_at
    rng = [k for k in today if cfg.range_start <= hour(k) < cfg.range_end]
    if len(rng) < cfg.min_range_bars or hour(today[-1]) < cfg.range_end:
        return BreakoutState(day, last["close"], None, None, None, None, exit_now)
    hi = max(bars[k]["high"] for k in rng)
    lo = min(bars[k]["low"] for k in rng)
    entry = stop = None
    window = [k for k in today if cfg.range_end <= hour(k) < cfg.entry_until]
    if window and window[-1] == len(bars) - 1 and not exit_now:
        earlier = [k for k in window[:-1] if bars[k]["close"] > hi or bars[k]["close"] < lo]
        c = last["close"]
        side = "LONG" if c > hi else "SHORT" if c < lo else None
        allowed = side and not (side == "LONG" and cfg.trade_dir == "Short only") and \
            not (side == "SHORT" and cfg.trade_dir == "Long only")
        if side and not earlier and allowed:
            entry = side
            stop = (hi + lo) / 2 if cfg.stop_mode == "middle" else (lo if side == "LONG" else hi)
    return BreakoutState(day, last["close"], hi, lo, entry, stop, exit_now)
