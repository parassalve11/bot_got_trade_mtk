from collections import namedtuple
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.cli import mt5_preflight
from app.trading.errors import Retryable
from app.trading.mt5_client import MT5Client
from app.trading.risk_manager import RiskManager


@pytest.mark.parametrize("offset", [0, 10800, -18000])
def test_broker_clock_normalization_preserves_quote_freshness_checks(env, offset):
    env.settings.mt5_server_utc_offset_seconds = offset
    client = MT5Client(env.settings)
    raw = SimpleNamespace(bid=1.1, ask=1.10002, time_msc=int((env.clock() + offset) * 1000))
    client.mt5 = SimpleNamespace(symbol_info_tick=lambda name: raw)
    risk = RiskManager(env.settings, env.db, client)
    assert risk.tick("EURUSD", env.clock()).time == pytest.approx(env.clock(), abs=0.001)
    raw.time_msc -= 60000
    with pytest.raises(Retryable, match="stale_quote"):
        risk.tick("EURUSD", env.clock())
    raw.time_msc += 120000
    with pytest.raises(Retryable, match="stale_quote"):
        risk.tick("EURUSD", env.clock())


@pytest.mark.parametrize("offset", [0, 10800, -18000])
@pytest.mark.parametrize("query_clock", ["utc", "server"])
def test_history_window_recovers_recent_fill_in_both_clock_conventions(env, monkeypatch, offset, query_clock):
    env.settings.mt5_server_utc_offset_seconds = offset
    monkeypatch.setattr("app.trading.mt5_client.time.time", env.clock)
    client = MT5Client(env.settings)
    deal_type = namedtuple("Deal", "time time_msc ticket")
    raw = deal_type(int(env.clock()) + offset, int(env.clock() * 1000) + offset * 1000, 789)

    def history(*bounds, **kwargs):
        if kwargs:
            assert kwargs == {"position": 123}
            return (raw,)
        start, end = bounds
        encoded_time = env.clock() + (offset if query_clock == "server" else 0)
        return (raw,) if start.timestamp() <= encoded_time <= end.timestamp() else ()

    client.mt5 = SimpleNamespace(history_deals_get=history)
    expected = [{"time": int(env.clock()), "time_msc": int(env.clock() * 1000), "ticket": 789}]
    assert client.deals(env.clock() - 60) == expected
    assert client.position_deals(123) == expected
    assert raw.time == int(env.clock()) + offset


def test_preflight_reports_trading_disabled_and_bad_clock_without_sending(env, monkeypatch):
    monkeypatch.setattr("app.cli.time.time", env.clock)
    env.broker.account_value = replace(env.broker.account_value, trade_allowed=False)
    original_tick = env.broker.tick
    monkeypatch.setattr(env.broker, "tick", lambda name: replace(original_tick(name), time=env.clock() + 10800))
    report = mt5_preflight(env.settings, env.db, env.broker, env.mapper)
    assert not report["preflight_passed"]
    assert "terminal_or_account_trading_disabled" in report["blockers"]
    assert "OANDA:EURUSD:stale_quote" in report["blockers"]
    assert not env.broker.sent


def test_preflight_accepts_fresh_quotes_without_enabling_or_sending_trades(env, monkeypatch):
    monkeypatch.setattr("app.cli.time.time", env.clock)
    env.settings.trading_enabled = False
    report = mt5_preflight(env.settings, env.db, env.broker, env.mapper)
    assert report["preflight_passed"]
    assert not env.settings.trading_enabled
    assert not env.broker.sent
