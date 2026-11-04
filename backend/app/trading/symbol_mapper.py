import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.trading.errors import Reject


class SymbolRule(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    broker_symbol: str = Field(min_length=1, max_length=64)
    enabled: bool = False
    price_multiplier: float = Field(default=1, gt=0)
    max_spread_points: float = Field(gt=0)
    max_price_drift_percent: float = Field(default=0.25, gt=0, le=5)
    max_lot: float = Field(gt=0)
    # >1 lets different strategies (e.g. split small/big targets) each hold one bot position
    # on this symbol. Requires a hedging account. Default 1 = one position per symbol.
    max_bot_positions: int = Field(default=1, ge=1, le=4)


class SymbolMapper:
    def __init__(self, path: Path):
        self.rules = TypeAdapter(dict[str, SymbolRule]).validate_python(json.loads(path.read_text("utf-8")))
        if not self.rules or any(":" not in name for name in self.rules):
            raise ValueError("Use explicit exchange-qualified TradingView symbols")

    def resolve(self, symbol: str, *, require_enabled: bool = True) -> SymbolRule:
        rule = self.rules.get(symbol)
        if rule is None or (require_enabled and not rule.enabled):
            raise Reject("symbol_not_enabled")
        return rule
