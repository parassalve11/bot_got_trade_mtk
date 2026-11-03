from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

TextID = Annotated[str, StringConstraints(min_length=1, max_length=512, pattern=r"^[^\x00-\x1f\x7f]+$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\x00-\x1f\x7f]+$")]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
EventType = Literal[
    "entry", "reverse", "stop_loss", "take_profit", "opposite_signal", "daily_loss", "date_end"
]
ENTRY_EVENTS = {"entry", "reverse"}
AUDIT_EVENTS = {"stop_loss", "take_profit"}
CLOSE_EVENTS = {"opposite_signal", "daily_loss", "date_end"}


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    source: Literal["tradingview"]
    strategy: ShortText
    version: ShortText
    instance: ShortText
    event_id: TextID
    trade_id: TextID
    event: EventType
    side: Literal["LONG", "SHORT"]
    symbol: ShortText
    timeframe: ShortText
    signal_time_ms: Annotated[StrictInt, Field(gt=0)]
    reference_price: Positive
    stop_ticks: Positive
    target_ticks: Positive | None
    tick_size: Positive
    stop_loss: Positive | None
    take_profit: Positive | None
    risk_percent: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False, strict=True)]
    previous_trade_id: TextID | None = None
    exit_owner: Literal["broker_fixed", "pine_simulation"]

    @model_validator(mode="after")
    def validate_event(self):
        if self.event_id != self.trade_id + ":" + self.event:
            raise ValueError("event_id must be trade_id:event")
        if self.event == "reverse" and (
            not self.previous_trade_id or self.previous_trade_id == self.trade_id
        ):
            raise ValueError("Reversal requires the previous trade ID")
        if self.event == "entry" and self.previous_trade_id is not None:
            raise ValueError("Flat entry cannot name a previous trade")
        return self


class AlertEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: Signal
    fill_price: Positive
    action: Literal["buy", "sell"]
    contracts: Positive
    position: Literal["long", "short", "flat"]
    position_size: Nonnegative
    previous_position: Literal["long", "short", "flat"]
    sent_at: datetime

    @model_validator(mode="after")
    def validate_envelope(self):
        if self.sent_at.tzinfo is None or self.sent_at.utcoffset() is None:
            raise ValueError("sent_at requires a timezone")
        entry = self.context.event in ENTRY_EVENTS
        long_trade = self.context.side == "LONG"
        expected_action = "buy" if long_trade == entry else "sell"
        if self.action != expected_action:
            raise ValueError("Action conflicts with event and trade side")
        if entry:
            if self.position != ("long" if long_trade else "short") or self.position_size <= 0:
                raise ValueError("Entry must report its resulting position")
            if self.context.event == "reverse" and self.previous_position != (
                "short" if long_trade else "long"
            ):
                raise ValueError("Reversal must report an opposite previous position")
            if self.context.event == "entry" and self.previous_position != "flat":
                raise ValueError("Entry must originate from flat")
        elif self.position != "flat" or self.position_size != 0:
            raise ValueError("Exit must report a flat resulting position")
        return self
