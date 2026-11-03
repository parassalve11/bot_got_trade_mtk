import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(env):
    with TestClient(create_app(env.settings), client=("127.0.0.1", 1234)) as value:
        yield value


def url(env):
    return "/api/v1/webhooks/tradingview/" + env.settings.webhook_token.get_secret_value()


def test_webhook_commits_without_calling_broker(env, client):
    env.broker.offline = True
    response = client.post(url(env), json=env.alert())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "QUEUED"
    assert env.db.event(1)
    assert not env.broker.sent


def test_api_to_worker_full_flow(env, client):
    response = client.post(url(env), json=env.alert())
    assert response.status_code == 200
    env.worker.tick()
    assert env.db.event(1)["status"] == "EXECUTED"
    assert len(env.broker.live) == 1


def test_duplicates_and_conflicting_payload(env, client):
    body = env.alert()
    assert client.post(url(env), json=body).status_code == 200
    assert client.post(url(env), json=body).json()["duplicate"]
    body["context"]["risk_percent"] = 0.3
    assert client.post(url(env), json=body).status_code == 409
    assert env.db.event(2) is None


def test_auth_and_forwarded_ip_spoofing(env, client):
    assert client.post(url(env) + "bad", json=env.alert()).status_code == 401
    app = create_app(env.settings)
    with TestClient(app, client=("8.8.8.8", 10)) as external:
        response = external.post(url(env), json=env.alert(), headers={"X-Forwarded-For": "127.0.0.1"})
        assert response.status_code == 403


@pytest.mark.parametrize(
    "field,value",
    [
        ("risk_percent", -1),
        ("risk_percent", "0.5"),
        ("stop_ticks", 0),
        ("tick_size", True),
        ("source", "other"),
        ("unexpected", 1),
    ],
)
def test_invalid_contracts_are_rejected_without_echo(env, client, field, value):
    body = env.alert()
    body["context"][field] = value
    response = client.post(url(env), json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_alert_contract"
    assert env.db.event(1) is None


def test_nonfinite_duplicate_keys_oversized_and_wrong_content_type(env, client):
    assert (
        client.post(
            url(env), content='{"a":1,"a":2}', headers={"content-type": "application/json"}
        ).status_code
        == 422
    )
    body = client.post(url(env), content='{"risk_percent":NaN}', headers={"content-type": "application/json"})
    assert body.status_code == 422
    assert (
        client.post(url(env), content="x" * 20000, headers={"content-type": "application/json"}).status_code
        == 413
    )
    assert client.post(url(env), content="{}", headers={"content-type": "text/plain"}).status_code == 415


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "UNKNOWN:X"),
        ("exit_owner", "pine_simulation"),
        ("version", "1.0.0"),
        ("instance", "not-allowed"),
        ("timeframe", "1"),
    ],
)
def test_allowlists_and_execution_mode(env, client, field, value):
    body = env.alert()
    body["context"][field] = value
    assert client.post(url(env), json=body).status_code in (403, 422)


def test_stale_future_and_naive_timestamps(env, client):
    for offset in (-500, 500):
        body = env.alert()
        body["sent_at"] = datetime.fromtimestamp(env.clock() + offset, timezone.utc).isoformat()
        assert client.post(url(env), json=body).status_code == 422
    body["sent_at"] = "2026-01-01T12:00:00"
    assert client.post(url(env), json=body).status_code == 422


def test_health_redaction_and_admin_auth(env, client):
    env.worker.maintain()
    public = client.get("/health")
    assert public.status_code == 200
    assert "equity" not in public.text and "123456" not in public.text
    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/health/mt5").status_code == 401
    auth = {"Authorization": "Bearer " + env.settings.admin_token.get_secret_value()}
    assert client.get("/api/v1/status", headers=auth).status_code == 200
    assert "123456" not in client.get("/health/mt5", headers=auth).text
    assert client.get("/docs").status_code == 404


def render_template(env, event="entry", side="LONG", trade_id="trade-1", previous=None, **fills):
    # Substitute placeholders exactly as TradingView does for "Order fills only" alerts.
    text = (Path(__file__).parents[2] / "examples" / "order-fill-alert.json.txt").read_text().strip()
    body = env.alert(event=event, side=side, trade_id=trade_id, previous=previous)
    values = {
        "strategy.order.alert_message": json.dumps(body["context"], separators=(",", ":")),
        "strategy.order.price": "1.10002",
        "strategy.order.action": body["action"],
        "strategy.order.contracts": "100" if event != "reverse" else "200",
        "strategy.market_position": body["position"],
        "strategy.market_position_size": str(body["position_size"]),
        "strategy.prev_market_position": body["previous_position"],
        "timenow": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    values.update(fills)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    assert "{{" not in text
    return text


def test_rendered_tradingview_template_round_trip(env, client):
    headers = {"Content-Type": "application/json"}
    steps = [
        render_template(env, trade_id="t1"),
        render_template(env, event="reverse", side="SHORT", trade_id="t2", previous="t1"),
        render_template(env, event="opposite_signal", side="SHORT", trade_id="t2"),
    ]
    for text in steps:
        response = client.post(url(env), content=text, headers=headers)
        assert response.status_code == 200, response.text
        env.worker.tick()
    statuses = [env.db.event(i)["status"] for i in (1, 2, 3)]
    assert statuses == ["EXECUTED", "EXECUTED", "EXECUTED"]
    assert not env.broker.live
