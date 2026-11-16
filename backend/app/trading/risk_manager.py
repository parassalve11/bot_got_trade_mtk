import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.trading.broker import BUY, DEAL, FOK, GTC, IOC, SELL, Account, Symbol
from app.trading.errors import Reject, Retryable, SafetyError


def round_step(value: float, step: float, *, up=False) -> float:
    if not math.isfinite(value) or not math.isfinite(step) or step <= 0:
        raise Reject("invalid_number_or_step")
    return float(
        (Decimal(str(value)) / Decimal(str(step))).to_integral_value(
            rounding=ROUND_CEILING if up else ROUND_FLOOR
        )
        * Decimal(str(step))
    )


def filling_policy(symbol: Symbol) -> int:
    # SYMBOL_FILLING flags are bit masks; ORDER_FILLING values are a different enum.
    if symbol.execution_mode in (0, 1) or symbol.filling_mode & 1:
        return FOK
    if symbol.filling_mode & 2:
        return IOC
    # RETURN may leave residual working orders; this executor deliberately excludes it.
    raise Reject("broker_requires_unsupported_filling_policy")


def protective_levels(side, entry, distance, target_distance, symbol):
    long = side == "LONG"
    sl = round_step(entry - distance if long else entry + distance, symbol.tick_size, up=not long)
    tp = (
        0.0
        if target_distance is None
        else round_step(
            entry + target_distance if long else entry - target_distance, symbol.tick_size, up=long
        )
    )
    if sl <= 0 or (target_distance is not None and tp <= 0):
        raise Reject("nonpositive_protective_price")
    return sl, tp


def validate_stops(side, sl, tp, tick, symbol, *, modifying=False):
    level = max(symbol.stops_level, symbol.freeze_level if modifying else 0) * symbol.point
    # Stops trigger against bid for buys and ask for sells; spread matters here.
    ref = tick.bid if side == "LONG" else tick.ask
    gap_sl = ref - sl if side == "LONG" else sl - ref
    gap_tp = tp - ref if side == "LONG" else ref - tp
    if gap_sl <= 0 or gap_sl + symbol.tick_size * 1e-6 < level:
        raise Reject("broker_minimum_stop_violation")
    if tp and (gap_tp <= 0 or gap_tp + symbol.tick_size * 1e-6 < level):
        raise Reject("broker_minimum_target_violation")


def bot_capital(db, settings, equity: float) -> float:
    """Capital the risk rules use. With RISK_CAPITAL set: that amount plus everything the account
    gained or lost since it was set (never more than the real equity). Otherwise the real equity."""
    cap = settings.risk_capital
    if not cap:
        return equity
    base = db.get_state("risk_capital_base")
    if not base or base.get("capital") != cap:
        base = {"capital": cap, "equity": equity}
        db.set_state("risk_capital_base", base)
        db.audit("risk_capital_set", base)
    return min(equity, cap + equity - base["equity"])


@dataclass(frozen=True)
class EntryPlan:
    request: dict
    stop_distance: float
    target_distance: float | None
    risk_budget: float


class RiskManager:
    def __init__(self, settings, db, broker):
        self.settings, self.db, self.broker = settings, db, broker

    def account_guard(self) -> Account:
        account = self.broker.account()
        settings = self.settings
        if account.login != settings.mt5_login or account.server != settings.mt5_server:
            raise SafetyError("unexpected_mt5_account")
        if settings.trading_mode == "DISABLED":
            raise Reject("trading_mode_disabled")
        expected_mode = 0 if settings.trading_mode == "DEMO" else 2
        if account.trade_mode != expected_mode or (
            account.trade_mode == 2 and not settings.allow_live_trading
        ):
            raise SafetyError("account_demo_live_mode_mismatch")
        self.db.bind_account(account.login, account.server, settings.magic_number)
        if not math.isfinite(account.equity) or account.equity <= 0 or not math.isfinite(account.margin_free):
            raise Reject("invalid_account_equity_or_margin")
        return account

    def tick(self, symbol, now):
        tick = self.broker.tick(symbol)
        if (
            not all(math.isfinite(v) for v in (tick.bid, tick.ask, tick.time))
            or tick.bid <= 0
            or tick.ask < tick.bid
        ):
            raise Retryable("invalid_quote")
        if (
            now - tick.time > self.settings.max_tick_age_seconds
            or tick.time - now > self.settings.max_future_skew_seconds
        ):
            raise Retryable("stale_quote")
        return tick

    def capital(self, account) -> float:
        return bot_capital(self.db, self.settings, account.equity)

    def daily(self, account, now):
        # Daily loss limit is a % of capital; expressed as a % of real equity for the journal.
        limit = self.settings.max_daily_loss_percent * self.capital(account) / account.equity
        return self.db.observe_equity(account.equity, limit, now)

    def entry_guard(self, account, now):
        if not self.settings.trading_enabled or self.db.get_state("operator_pause", False):
            raise Reject("entries_paused")
        if not self.db.get_state("bot_running", True):
            raise Reject("bot_stopped")
        if self.db.get_state("safety_hold") or self.db.operations(["UNKNOWN", "SENDING"]):
            raise Reject("safety_review_required")
        if not account.trade_allowed:
            raise Retryable("terminal_or_account_trading_disabled")
        daily = self.daily(account, now)
        if daily["paused"]:
            raise Reject("daily_equity_loss_limit")
        if daily["entry_attempts"] >= self.settings.max_daily_entries:
            raise Reject("daily_entry_limit")

    def symbol_slot(self, account, symbol_name, instance, rule, *, replacing_identifier=None, reason=None):
        """Can `instance` open a new bot position on this symbol?

        Default (max_bot_positions=1): only when the symbol is completely flat. With a higher limit
        (split targets), other strategy instances may each hold one journaled bot position, on a
        hedging account only. Manual/unknown positions and working orders always block.
        """
        conflict = reason or "symbol_position_or_order_conflict"
        if any(o["symbol"] == symbol_name for o in self.broker.orders()):
            raise Reject(conflict)
        held = [p for p in self.broker.positions() if p.symbol == symbol_name and p.identifier != replacing_identifier]
        if not held:
            return
        journal = {r["identifier"]: r for r in self.db.open_positions()}
        if rule.max_bot_positions <= 1:
            raise Reject(conflict)
        if any(p.magic != self.settings.magic_number or p.identifier not in journal for p in held):
            raise Reject(conflict)
        if any(journal[p.identifier]["instance"] == instance for p in held):
            raise Reject(conflict)
        if len(held) >= rule.max_bot_positions:
            raise Reject("symbol_position_limit")
        if account.margin_mode != 2:
            raise Reject("netting_account_cannot_share_symbol")

    def plan(self, sig, rule, now, *, replacing_identifier=None):
        account = self.account_guard()
        self.entry_guard(account, now)
        if sig.risk_percent > self.settings.max_risk_percent:
            raise Reject("requested_risk_above_server_limit")
        symbol = self.broker.symbol(rule.broker_symbol)
        if not all(
            math.isfinite(v) and v > 0
            for v in (
                symbol.point,
                symbol.tick_size,
                symbol.volume_min,
                symbol.volume_max,
                symbol.volume_step,
            )
        ):
            raise Reject("invalid_broker_symbol_metadata")
        if (
            symbol.trade_mode in (0, 3)
            or (symbol.trade_mode == 1 and sig.side != "LONG")
            or (symbol.trade_mode == 2 and sig.side != "SHORT")
        ):
            raise Reject("broker_direction_not_allowed")
        tick = self.tick(symbol.name, now)
        if (tick.ask - tick.bid) / symbol.point > rule.max_spread_points + 1e-8:
            raise Reject("spread_limit")
        entry = tick.ask if sig.side == "LONG" else tick.bid
        ref = sig.reference_price * rule.price_multiplier
        if abs(entry - ref) / ref * 100 > rule.max_price_drift_percent:
            raise Reject("price_drift_limit")
        positions = self.broker.positions()
        orders = self.broker.orders()
        others = [p for p in positions if p.identifier != replacing_identifier]
        self.symbol_slot(account, symbol.name, sig.instance, rule, replacing_identifier=replacing_identifier)
        if len(others) + len(orders) >= self.settings.max_open_positions:
            raise Reject("account_position_limit")
        distance = sig.stop_ticks * sig.tick_size * rule.price_multiplier
        target = (
            None if sig.target_ticks is None else sig.target_ticks * sig.tick_size * rule.price_multiplier
        )
        if not math.isfinite(distance) or distance <= 0 or (target is not None and not math.isfinite(target)):
            raise Reject("invalid_stop_distance")
        sl, tp = protective_levels(sig.side, entry, distance, target, symbol)
        validate_stops(sig.side, sl, tp, tick, symbol)
        capital = self.capital(account)
        if capital <= 0:
            raise Reject("risk_capital_exhausted")
        risk_budget = capital * sig.risk_percent / 100
        spendable = risk_budget * (1 - self.settings.risk_cost_buffer_percent / 100)
        # Market-execution brokers may ignore deviation. Include it in pre-trade sizing
        # and verify actual risk/slippage after execution as well.
        worst_entry = (
            entry + (1 if sig.side == "LONG" else -1) * self.settings.max_deviation_points * symbol.point
        )
        if worst_entry <= 0:
            raise Reject("invalid_adverse_entry")
        reference_volume = symbol.volume_min
        loss = -self.broker.profit(sig.side, symbol.name, reference_volume, worst_entry, sl)
        if loss <= 0:
            raise Reject("invalid_broker_loss_calculation")
        lot = round_step(
            min(
                spendable / (loss / reference_volume), symbol.volume_max, rule.max_lot, self.settings.max_lot
            ),
            symbol.volume_step,
        )
        allowed = spendable
        if lot < symbol.volume_min or lot <= 0:
            # Small account: the minimum lot, only if its risk stays within the configured cap.
            min_cap = capital * self.settings.min_lot_max_risk_percent / 100
            if 0 < loss <= min_cap + 1e-6 and symbol.volume_min <= min(rule.max_lot, self.settings.max_lot):
                lot, allowed = symbol.volume_min, min_cap
            else:
                raise Reject("risk_budget_below_minimum_lot")
        planned_risk = -self.broker.profit(sig.side, symbol.name, lot, worst_entry, sl)
        if planned_risk > allowed + 1e-6:
            raise Reject("normalized_lot_exceeds_risk")
        risk_budget = max(risk_budget, planned_risk)
        free_margin = account.margin_free
        if self.settings.risk_capital:
            used = max(0.0, account.equity - account.margin_free)
            free_margin = min(free_margin, capital - used)
        if self.broker.margin(sig.side, symbol.name, lot, worst_entry) > free_margin * self.settings.max_margin_fraction:
            raise Reject("insufficient_free_margin")
        open_risk = 0.0
        for pos in others:
            if pos.magic != self.settings.magic_number:
                continue
            if pos.sl <= 0:
                raise SafetyError("managed_position_without_stop")
            live = self.tick(pos.symbol, now)
            mark = live.bid if pos.side == "LONG" else live.ask
            open_risk += max(0, -self.broker.profit(pos.side, pos.symbol, pos.volume, mark, pos.sl))
        if open_risk + risk_budget > capital * self.settings.max_total_risk_percent / 100 + 1e-6:
            raise Reject("portfolio_risk_limit")
        request = dict(
            action=DEAL,
            symbol=symbol.name,
            volume=lot,
            type=BUY if sig.side == "LONG" else SELL,
            price=entry,
            sl=sl,
            tp=tp,
            deviation=self.settings.max_deviation_points,
            magic=self.settings.magic_number,
            type_time=GTC,
            type_filling=filling_policy(symbol),
        )
        return EntryPlan(request, distance, target, risk_budget)
