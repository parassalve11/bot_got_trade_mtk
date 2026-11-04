from dataclasses import dataclass
from typing import Protocol

# Official MQL5 request/result enumeration values, also used by deterministic tests.
DEAL = 1
SLTP = 6
BUY = 0
SELL = 1
FOK = 0
IOC = 1
GTC = 0
DONE = 10009
DONE_PARTIAL = 10010
UNCERTAIN_CODES = {10008, 10012, 10031}  # placed, timeout, connection


@dataclass(frozen=True)
class Account:
    login: int
    server: str
    equity: float
    margin_free: float
    trade_mode: int  # 0 demo, 1 contest, 2 real
    trade_allowed: bool
    currency: str = "USD"
    balance: float = 0.0
    margin_mode: int = 2  # 0 netting, 1 exchange, 2 hedging (ACCOUNT_MARGIN_MODE_*)


@dataclass(frozen=True)
class Symbol:
    name: str
    point: float
    tick_size: float
    digits: int
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level: int
    freeze_level: int
    filling_mode: int
    execution_mode: int
    trade_mode: int  # 0 disabled, 1 long only, 2 short only, 3 close only, 4 full


@dataclass(frozen=True)
class Tick:
    bid: float
    ask: float
    time: float


@dataclass(frozen=True)
class Position:
    ticket: int
    identifier: int
    symbol: str
    side: str
    volume: float
    price_open: float
    sl: float
    tp: float
    magic: int
    comment: str
    profit: float = 0.0  # floating P/L incl. swap


class Broker(Protocol):
    def connect(self) -> None: ...
    def shutdown(self) -> None: ...
    def account(self) -> Account: ...
    def symbol(self, name: str) -> Symbol: ...
    def tick(self, name: str) -> Tick: ...
    def positions(self) -> list[Position]: ...
    def orders(self) -> list[dict]: ...
    def deals(self, since: float) -> list[dict]: ...
    def position_deals(self, identifier: int) -> list[dict]: ...
    def profit(self, side: str, symbol: str, volume: float, entry: float, exit: float) -> float: ...
    def margin(self, side: str, symbol: str, volume: float, price: float) -> float: ...
    def check(self, request: dict) -> dict: ...
    def rates(self, name: str, timeframe: str, count: int) -> list[dict]: ...
    def send(self, request: dict) -> dict | None: ...
