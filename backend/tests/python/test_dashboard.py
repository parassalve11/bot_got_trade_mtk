import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import create_app
from app.signals.ut_engine import StreamConfig

PROXY = "p" * 40
MASTER = "Master-Pass-123"


@pytest.fixture
def dash(env, tmp_path):
    engine = tmp_path / "engine.json"
    engine.write_text('[{"instance": "engine", "tv_symbol": "OANDA:EURUSD", "timeframe": "15"},'
                      ' {"instance": "g", "tv_symbol": "OANDA:GBPUSD", "watch_only": true}]')
    env.settings = env.settings.model_copy(update=dict(
        dash_proxy_secret=SecretStr(PROXY), mt5_password=SecretStr(MASTER),
        engine_mode="watch", engine_config_path=engine,
    ))
    env.worker.settings = env.settings
    with TestClient(create_app(env.settings), client=("127.0.0.1", 1234)) as client:
        yield client


def call(client, method, path, token=None, **kw):
    headers = {"x-dash-proxy-secret": PROXY}
    if token:
        headers["authorization"] = "Bearer " + token
    return client.request(method, "/api/v1/dash" + path, headers=headers, **kw)


def login(client, password, login=123456, server="Test-Demo"):
    return call(client, "POST", "/login", json={"login": login, "password": password, "server": server})


def test_proxy_secret_hides_every_route(dash):
    assert dash.post("/api/v1/dash/login", json={"login": 123456, "password": MASTER, "server": "Test-Demo"}).status_code == 404
    bad = {"x-dash-proxy-secret": "wrong"}
    assert dash.get("/api/v1/dash/overview", headers=bad).status_code == 404
    assert call(dash, "GET", "/overview").status_code == 401  # right proxy secret, no session


def test_dashboard_disabled_without_proxy_secret(env):
    with TestClient(create_app(env.settings), client=("127.0.0.1", 1234)) as client:
        assert login(client, "x").status_code == 404


def test_master_password_signs_in_and_logout_revokes(dash):
    session = login(dash, MASTER).json()
    assert session["role"] == "admin"
    assert call(dash, "GET", "/me", session["token"]).status_code == 200
    assert call(dash, "POST", "/logout", session["token"]).status_code == 200
    assert call(dash, "GET", "/me", session["token"]).status_code == 401


@pytest.mark.parametrize("changes", [dict(password="wrong"), dict(login=999), dict(server="Other-Demo")])
def test_wrong_credentials_rejected(dash, changes):
    body = dict(password=MASTER, login=123456, server="Test-Demo") | changes
    assert login(dash, **body).status_code == 401


def test_lockout_after_repeated_failures(dash):
    for _ in range(5):
        assert login(dash, "wrong").status_code == 401
    assert login(dash, MASTER).status_code == 429  # even the right password, until the window passes


def test_controls_need_session_and_note(dash, env):
    admin = login(dash, MASTER).json()["token"]
    note = {"note": "testing pause control"}
    assert call(dash, "POST", "/control/pause", json=note).status_code == 401
    assert call(dash, "POST", "/control/pause", admin, json={"note": "short"}).status_code == 422
    assert call(dash, "POST", "/control/pause", admin, json=note).status_code == 200
    assert env.db.get_state("operator_pause") is True
    assert call(dash, "POST", "/control/resume", admin, json=note).status_code == 200
    assert env.db.get_state("operator_pause") is False


def test_overview_uses_worker_snapshot_and_hides_login(dash, env):
    env.worker.maintain()
    token = login(dash, MASTER).json()["token"]
    data = call(dash, "GET", "/overview", token).json()
    assert data["health"]["worker"] and data["health"]["mt5"]
    assert data["account"]["equity"] == 10000 and data["account"]["login"] == "***456"
    assert "123456" not in str(data)
    for path in ("/positions", "/signals", "/strategies", "/equity", "/audit", "/config"):
        assert call(dash, "GET", path, token).status_code == 200, path


def test_close_from_dashboard_is_executed_by_worker(dash, env):
    env.enqueue()
    env.worker.tick()
    record = env.db.open_positions()[0]
    admin = login(dash, MASTER).json()["token"]
    body = {"instance": record["instance"], "trade_id": record["trade_id"], "note": "manual close from test"}
    assert call(dash, "POST", "/positions/close", admin, json=body).status_code == 200
    assert call(dash, "POST", "/positions/close", admin, json=body).status_code == 409  # already pending
    assert env.broker.live  # API never touches MT5
    env.worker.maintain()
    assert env.broker.live == [] and env.db.open_positions() == []
    assert env.db.close_requests()[0]["status"] == "CLOSED"
    positions = call(dash, "GET", "/positions", admin).json()
    assert positions["open"] == [] and len(positions["closed"]) == 1


def test_strategy_mode_override(dash, env):
    admin = login(dash, MASTER).json()["token"]
    body = {"instance": "g", "tv_symbol": "OANDA:GBPUSD", "mode": "off", "note": "turn off for testing"}
    assert call(dash, "POST", "/strategies/mode", admin, json=body).status_code == 200
    modes = {s["instance"]: s["mode"] for s in call(dash, "GET", "/strategies", admin).json()["strategies"]}
    assert modes == {"engine": "watch", "g": "off"}
    from app import control

    stream = StreamConfig(instance="g", tv_symbol="OANDA:GBPUSD", watch_only=True)
    assert control.effective_stream_mode(env.db, stream, "trade") == "off"
    # Trade needs an enabled symbol mapping: GBPUSD is enabled in the test mapping, unknown symbols are not.
    bad = {**body, "instance": "nope", "mode": "trade"}
    assert call(dash, "POST", "/strategies/mode", admin, json=bad).status_code == 404


def test_start_stop_switch(dash, env):
    admin = login(dash, MASTER).json()["token"]
    assert call(dash, "POST", "/bot/stop", admin).json()["bot_running"] is False
    assert call(dash, "GET", "/overview", admin).json()["entries"]["bot_running"] is False
    env.enqueue()
    env.worker.tick()
    assert env.db.status()["recent_events"][0]["error"] == "bot_stopped"  # no new entry while stopped
    assert not env.broker.sent
    env.worker.maintain()
    assert env.db.get_state("worker")["ready"] is False
    assert call(dash, "POST", "/bot/start", admin).json()["bot_running"] is True
    env.enqueue(trade_id="trade-after-start")
    env.worker.tick()
    assert env.broker.live  # trades again after Start
    assert call(dash, "POST", "/bot/start").status_code == 401  # needs a session


def test_engine_does_not_poll_while_stopped(env):
    env.db.set_state("bot_running", False)
    calls = []
    env.worker.engine = type("E", (), {"poll": lambda self, now: calls.append(now)})()
    env.worker.tick()
    assert calls == []
    env.db.set_state("bot_running", True)
    env.worker.tick()
    assert len(calls) == 1
