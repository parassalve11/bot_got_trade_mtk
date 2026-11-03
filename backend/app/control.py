"""Operator controls shared by the CLI and the dashboard API.

Nothing here talks to MT5. Close requests are queued in the journal and executed by the
worker (the only MT5 process) through the normal executor safeguards.
"""

import time

MIN_NOTE = 10
STREAM_MODES = ("off", "watch", "trade")


def require_note(note: str) -> str:
    note = (note or "").strip()
    if len(note) < MIN_NOTE:
        raise ValueError(f"Provide a meaningful note (at least {MIN_NOTE} characters)")
    return note


def set_paused(db, paused: bool, note: str, actor: str = "cli"):
    note = require_note(note)
    if not paused:
        if db.operations(["UNKNOWN", "SENDING"]):
            raise ValueError("Uncertain operations must be reconciled before resuming")
        if db.get_state("safety_hold"):
            raise ValueError("Resolve the cause, then acknowledge the safety hold first")
    db.set_state("operator_pause", paused)
    db.audit("operator_pause" if paused else "operator_resume", {"note": note, "by": actor})


def acknowledge_hold(db, settings, note: str, actor: str = "cli"):
    note = require_note(note)
    if db.operations(["UNKNOWN", "SENDING"]):
        raise ValueError("Uncertain operations must be reconciled before acknowledging")
    beat = db.get_state("worker", {})
    if time.time() - beat.get("at", 0) > settings.worker_health_seconds or not beat.get("reconciled"):
        raise ValueError("A fresh clean worker reconciliation is required")
    previous = db.get_state("safety_hold")
    db.set_state("safety_hold", None)
    db.audit("operator_acknowledge_hold", {"note": note, "by": actor, "hold": previous})


def request_close(db, instance: str, trade_id: str, note: str, actor: str):
    note = require_note(note)
    db.add_close_request(instance, trade_id, note, actor, time.time())
    db.audit("operator_close_requested", {"instance": instance, "trade_id": trade_id, "note": note, "by": actor})


def request_close_all(db, note: str, actor: str) -> int:
    note = require_note(note)
    count = 0
    for record in db.open_positions():
        try:
            db.add_close_request(record["instance"], record["trade_id"], note, actor, time.time())
            count += 1
        except ValueError:
            pass  # Already pending.
    db.audit("operator_close_all_requested", {"count": count, "note": note, "by": actor})
    return count


def stream_mode_key(instance: str, tv_symbol: str) -> str:
    return f"stream_mode:{instance}:{tv_symbol}"


def set_stream_mode(db, settings, symbols, stream, mode: str, note: str, actor: str):
    """Runtime override for one engine stream; the worker reads it on every poll."""
    note = require_note(note)
    if mode not in STREAM_MODES:
        raise ValueError("Mode must be off, watch or trade")
    if settings.engine_mode == "off":
        raise ValueError("The signal engine is off (ENGINE_MODE=off); enable it in backend .env first")
    if mode == "trade":
        rule = symbols.rules.get(stream.tv_symbol)
        if rule is None or not rule.enabled:
            raise ValueError(
                f"{stream.tv_symbol} is disabled in config/symbols.json; enable it there and restart first"
            )
        if stream.risk_percent > settings.max_risk_percent:
            raise ValueError("Stream risk_percent exceeds MAX_RISK_PERCENT")
    db.set_state(stream_mode_key(stream.instance, stream.tv_symbol), mode)
    db.audit("operator_stream_mode", {"instance": stream.instance, "symbol": stream.tv_symbol, "mode": mode,
                                      "note": note, "by": actor})


def effective_stream_mode(db, stream, default_mode: str) -> str:
    """Dashboard override wins; otherwise config: disabled -> off, watch_only -> watch, else ENGINE_MODE."""
    override = db.get_state(stream_mode_key(stream.instance, stream.tv_symbol))
    if override in STREAM_MODES:
        return override
    if not stream.enabled:
        return "off"
    if stream.watch_only:
        return "watch"
    return "trade" if default_mode == "trade" else "watch"
