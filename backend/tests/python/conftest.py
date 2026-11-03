import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.database import Database
from app.schemas import AlertEnvelope
from app.trading.symbol_mapper import SymbolMapper
from app.trading.worker import Worker
from tests.python.fake_broker import FakeBroker


@pytest.fixture
def env(tmp_path):
    now = [time.time()]

    def clock():
        return now[0]

    symbols = tmp_path / "symbols.json"
    symbols.write_text(
        json.dumps(
            {
                "OANDA:EURUSD": dict(
                    broker_symbol="EURUSD",
                    enabled=True,
                    price_multiplier=1,
                    max_spread_points=30,
                    max_price_drift_percent=0.25,
                    max_lot=1,
                ),
                "OANDA:GBPUSD": dict(
                    broker_symbol="GBPUSD",
                    enabled=True,
                    price_multiplier=1,
                    max_spread_points=40,
                    max_price_drift_percent=0.25,
                    max_lot=1,
                ),
            }
        )
    )
    settings = Settings(
        _env_file=None,
        webhook_token="w" * 40,
        admin_token="a" * 40,
        trading_mode="DEMO",
        trading_enabled=True,
        mt5_login=123456,
        mt5_server="Test-Demo",
        mt5_path="test-terminal.exe",
        symbols_path=symbols,
        database_path=tmp_path / "trading.db",
        log_directory=tmp_path / "logs",
    )
    db = Database(settings.database_path)
    db.initialize()
    broker = FakeBroker(clock)
    mapper = SymbolMapper(symbols)
    worker = Worker(settings, db, broker, mapper, clock=clock)
    result = SimpleNamespace(
        now=now,
        clock=clock,
        settings=settings,
        db=db,
        broker=broker,
        mapper=mapper,
        worker=worker,
        tmp_path=tmp_path,
    )

    def alert(event="entry", side="LONG", trade_id="trade-1", previous=None, **changes):
        sig = dict(
            source="tradingview",
            strategy="bytefx_ut_multi_asset",
            version="1.1.0",
            instance="main",
            event_id=trade_id + ":" + event,
            trade_id=trade_id,
            event=event,
            side=side,
            symbol="OANDA:EURUSD",
            timeframe="15",
            signal_time_ms=int(now[0] * 1000),
            reference_price=1.1,
            stop_ticks=100,
            target_ticks=150,
            tick_size=0.00001,
            stop_loss=None,
            take_profit=None,
            risk_percent=0.5,
            previous_trade_id=previous,
            exit_owner="broker_fixed",
        )
        sig.update(changes)
        entry = event in ("entry", "reverse")
        return dict(
            context=sig,
            fill_price=1.10002,
            action="buy" if (side == "LONG") == entry else "sell",
            contracts=100,
            position=("long" if side == "LONG" else "short") if entry else "flat",
            position_size=100 if entry else 0,
            previous_position=("short" if side == "LONG" else "long")
            if event == "reverse"
            else "flat"
            if entry
            else ("long" if side == "LONG" else "short"),
            sent_at=datetime.fromtimestamp(now[0], timezone.utc).isoformat(),
        )

    def enqueue(**kwargs):
        value = AlertEnvelope.model_validate(alert(**kwargs))
        rule = mapper.resolve(value.context.symbol, require_enabled=False)
        return db.enqueue(value, rule.broker_symbol, now[0], 10000)[0]

    result.alert, result.enqueue = alert, enqueue
    return result
