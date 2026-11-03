import asyncio
import json
import logging
import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.schemas import ENTRY_EVENTS, AlertEnvelope
from app.security.webhook_auth import authenticate_webhook
from app.trading.errors import Reject

router = APIRouter()
log = logging.getLogger(__name__)


def check_freshness(alert, settings, now):
    age = now - alert.sent_at.timestamp()
    if age > settings.max_event_age_seconds or age < -settings.max_future_skew_seconds:
        raise Reject("stale_or_future_event")
    if alert.context.event in ENTRY_EVENTS:
        signal_age = now - alert.context.signal_time_ms / 1000
        if signal_age > settings.max_signal_age_seconds or signal_age < -settings.max_future_skew_seconds:
            raise Reject("stale_or_future_entry_signal")


@router.post("/api/v1/webhooks/tradingview/{token}")
async def webhook(request: Request, token: str):
    settings, db = request.app.state.settings, request.app.state.db
    authenticate_webhook(request, token, settings)
    if not request.app.state.limiter.allow():
        raise HTTPException(429, "rate_limited")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "application_json_required")
    body = bytearray()
    try:
        async with asyncio.timeout(1):
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > settings.max_body_bytes:
                    raise HTTPException(413, "payload_too_large")
    except TimeoutError:
        raise HTTPException(408, "body_timeout") from None
    try:

        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate_json_key")
                result[key] = value
            return result

        decoded = json.loads(body, object_pairs_hook=unique_keys)
        alert = AlertEnvelope.model_validate(decoded)
    except (ValidationError, ValueError, UnicodeError):
        # Do not echo the body back into proxy logs or clients.
        raise HTTPException(422, "invalid_alert_contract") from None
    sig = alert.context
    if (
        sig.strategy not in settings.allowed_strategies
        or sig.version not in settings.allowed_versions
        or sig.instance not in settings.allowed_instances
        or sig.timeframe not in settings.allowed_timeframes
    ):
        raise HTTPException(403, "strategy_version_instance_or_timeframe_not_allowed")
    try:
        previous = await asyncio.to_thread(db.duplicate, alert)
        if previous:
            return {
                "accepted": True,
                "duplicate": True,
                "event_id": sig.event_id,
                "status": previous["status"],
            }
        now = time.time()
        check_freshness(alert, settings, now)
        # Disabled symbol rules may still receive closes for existing positions.
        rule = request.app.state.symbols.resolve(sig.symbol, require_enabled=sig.event in ENTRY_EVENTS)
        if sig.event in ENTRY_EVENTS and sig.exit_owner != "broker_fixed":
            raise Reject("enable_broker_fixed_execution_in_pine")
        row, duplicate = await asyncio.to_thread(
            db.enqueue, alert, rule.broker_symbol, now, settings.max_queue_size
        )
    except Reject as exc:
        reason = str(exc)
        raise HTTPException(
            503 if reason == "queue_full" else 409 if reason == "event_id_payload_conflict" else 422, reason
        ) from None
    except sqlite3.OperationalError:
        raise HTTPException(503, "queue_temporarily_unavailable") from None
    log.info(
        "webhook_committed", extra={"event_pk": row["id"], "event_id": sig.event_id, "status": row["status"]}
    )
    return {"accepted": True, "duplicate": duplicate, "event_id": sig.event_id, "status": row["status"]}
