from app.trading.errors import Retryable, SafetyError


class PositionManager:
    def __init__(self, settings, db, broker):
        self.settings, self.db, self.broker = settings, db, broker

    def locate(self, record, positions=None):
        values = self.broker.positions() if positions is None else positions
        matches = [p for p in values if p.identifier == record["identifier"]]
        if len(matches) > 1:
            raise SafetyError("ambiguous_position_identifier")
        return matches[0] if matches else None

    def assert_owned(self, record, position):
        if (
            position.magic != self.settings.magic_number
            or position.symbol != record["symbol"]
            or position.identifier != record["identifier"]
            or position.side != record["side"]
        ):
            raise SafetyError("position_identity_changed")
        symbol = self.broker.symbol(position.symbol)
        if abs(position.volume - record["volume"]) > symbol.volume_step * 1e-6:
            raise SafetyError("position_volume_changed_outside_executor")
        if abs(position.price_open - record["entry_price"]) > symbol.tick_size * 0.5:
            raise SafetyError("position_entry_changed_outside_executor")
        deals = self.broker.position_deals(position.identifier)
        trading_deals = [d for d in deals if d["type"] in (0, 1)]
        if not trading_deals:
            raise Retryable("ownership_history_not_yet_available")
        if any(d["magic"] != self.settings.magic_number for d in trading_deals):
            raise SafetyError("manual_or_other_ea_deal_in_position")

    def refresh(self, record, position):
        updated = {**record, "ticket": position.ticket, "sl": position.sl, "tp": position.tp}
        self.db.save_position(updated)
        return updated
