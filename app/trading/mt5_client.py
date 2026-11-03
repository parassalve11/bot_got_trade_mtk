"""Only the worker imports/calls MetaTrader5; API processes never touch the terminal."""

import importlib
import math
import time
from datetime import datetime, timezone

from app.trading.broker import Account, Position, Symbol, Tick
from app.trading.errors import Reject, Retryable

TIMEFRAMES = {
    "1": "TIMEFRAME_M1",
    "5": "TIMEFRAME_M5",
    "15": "TIMEFRAME_M15",
    "30": "TIMEFRAME_M30",
    "60": "TIMEFRAME_H1",
    "240": "TIMEFRAME_H4",
}


class MT5Client:
    def __init__(self, settings):
        self.settings = settings
        self.mt5 = None

    def connect(self):
        if self.mt5 is None:
            try:
                self.mt5 = importlib.import_module("MetaTrader5")
            except ImportError:
                raise Retryable("mt5_package_not_installed") from None
        terminal = self.mt5.terminal_info()
        if terminal and terminal.connected:
            return
        options = dict(
            login=self.settings.mt5_login,
            server=self.settings.mt5_server,
            timeout=self.settings.mt5_timeout_ms,
        )
        password = self.settings.mt5_password.get_secret_value()
        if password:
            options["password"] = password
        if not self.mt5.initialize(self.settings.mt5_path, **options):
            raise Retryable("mt5_initialize_failed")

    def shutdown(self):
        if self.mt5:
            self.mt5.shutdown()

    def account(self):
        account = self.mt5.account_info()
        terminal = self.mt5.terminal_info()
        if account is None or terminal is None or not terminal.connected:
            raise Retryable("mt5_disconnected")
        allowed = bool(
            account.trade_allowed
            and account.trade_expert
            and terminal.trade_allowed
            and not terminal.tradeapi_disabled
        )
        return Account(
            account.login,
            account.server,
            account.equity,
            account.margin_free,
            account.trade_mode,
            allowed,
            account.currency,
        )

    def symbol(self, name):
        info = self.mt5.symbol_info(name)
        if info is None:
            raise Reject("broker_symbol_missing")
        if not info.visible and not self.mt5.symbol_select(name, True):
            raise Retryable("symbol_select_failed")
        return Symbol(
            name,
            info.point,
            info.trade_tick_size,
            info.digits,
            info.volume_min,
            info.volume_max,
            info.volume_step,
            info.trade_stops_level,
            info.trade_freeze_level,
            info.filling_mode,
            info.trade_exemode,
            info.trade_mode,
        )

    def tick(self, name):
        value = self.mt5.symbol_info_tick(name)
        if value is None:
            raise Retryable("tick_unavailable")
        # Some terminals expose server wall-clock epochs instead of UTC.
        # Use an explicitly verified offset; never infer it from a possibly stale tick.
        return Tick(
            value.bid, value.ask,
            value.time_msc / 1000 - self.settings.mt5_server_utc_offset_seconds,
        )

    def positions(self):
        values = self.mt5.positions_get()
        if values is None:
            raise Retryable("positions_unavailable")
        return [
            Position(
                p.ticket,
                p.identifier,
                p.symbol,
                "LONG" if p.type == 0 else "SHORT",
                p.volume,
                p.price_open,
                p.sl,
                p.tp,
                p.magic,
                p.comment,
            )
            for p in values
        ]

    def orders(self):
        values = self.mt5.orders_get()
        if values is None:
            raise Retryable("orders_unavailable")
        return [dict(value._asdict()) for value in values]

    def deals(self, since):
        offset = self.settings.mt5_server_utc_offset_seconds
        # Cover both UTC and server-clock query conventions. Matching an operation
        # still requires its unique comment/order/deal identity in Executor.
        values = self.mt5.history_deals_get(
            datetime.fromtimestamp(since + min(0, offset), timezone.utc),
            datetime.fromtimestamp(time.time() + 60 + max(0, offset), timezone.utc),
        )
        if values is None:
            raise Retryable("deal_history_unavailable")
        return [self._deal_utc(value) for value in values]

    def position_deals(self, identifier):
        values = self.mt5.history_deals_get(position=identifier)
        if values is None:
            raise Retryable("position_history_unavailable")
        return [self._deal_utc(value) for value in values]

    def _deal_utc(self, value):
        result = dict(value._asdict())
        offset = self.settings.mt5_server_utc_offset_seconds
        result["time"] -= offset
        result["time_msc"] -= offset * 1000
        return result

    def profit(self, side, symbol, volume, entry, exit):
        value = self.mt5.order_calc_profit(0 if side == "LONG" else 1, symbol, volume, entry, exit)
        if value is None or not math.isfinite(value):
            raise Retryable("profit_calculation_unavailable")
        return float(value)

    def margin(self, side, symbol, volume, price):
        value = self.mt5.order_calc_margin(0 if side == "LONG" else 1, symbol, volume, price)
        if value is None or not math.isfinite(value):
            raise Retryable("margin_calculation_unavailable")
        return float(value)

    def rates(self, name, timeframe, count):
        """Candles oldest-first with bar OPEN time in UTC; the last one may still be forming."""
        values = self.mt5.copy_rates_from_pos(name, getattr(self.mt5, TIMEFRAMES[timeframe]), 0, count)
        if values is None or len(values) == 0:
            raise Retryable("rates_unavailable")
        offset = self.settings.mt5_server_utc_offset_seconds
        return [
            dict(
                time=float(v["time"]) - offset,
                open=float(v["open"]),
                high=float(v["high"]),
                low=float(v["low"]),
                close=float(v["close"]),
            )
            for v in values
        ]

    def check(self, request):
        value = self.mt5.order_check(request)
        if value is None:
            raise Retryable("order_check_unavailable")
        return {key: getattr(value, key) for key in ("retcode", "comment", "margin", "margin_free")}

    def send(self, request):
        value = self.mt5.order_send(request)
        if value is None:
            return None
        # Do not persist the returned request object or terminal/account credentials.
        return {
            key: getattr(value, key)
            for key in ("retcode", "deal", "order", "volume", "price", "comment", "request_id")
        }
