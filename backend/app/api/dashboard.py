"""Dashboard API for the Next.js frontend (served to Vercel through Tailscale Funnel).

Security layers, in order:
1. X-Dash-Proxy-Secret: only the Vercel server knows it; without it every route is 404.
2. MT5 login: account number, server and master password must match .env (one role, full
   access). Global lockout after repeated failures.
3. Opaque session token (only its SHA-256 is stored), expiring after DASH_SESSION_HOURS.
4. Every state-changing action requires an audit note.
The API never calls MT5; the worker publishes snapshots and executes close requests.
"""

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import control
from app.signals.ut_engine import load_streams

router = APIRouter(prefix="/api/v1/dash")
LOCKOUT_FAILURES, LOCKOUT_SECONDS = 5, 900
ACTOR = "dashboard"


# ---------------------------------------------------------------- security
def proxy_guard(request: Request):
    expected = request.app.state.settings.dash_proxy_secret.get_secret_value()
    if not expected:
        raise HTTPException(404, "not_found")  # Dashboard disabled until configured.
    actual = request.headers.get("x-dash-proxy-secret", "")
    if not hmac.compare_digest(actual.encode(), expected.encode()):
        raise HTTPException(404, "not_found")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
    found = request.app.state.db.session(_hash(token), time.time()) if token else None
    if not found:
        raise HTTPException(401, "session_expired")
    return found


admin = session  # Single role: every signed-in session has full access.


class LoginBody(BaseModel):
    login: int = Field(gt=0)
    password: str = Field(min_length=1, max_length=128)
    server: str = Field(min_length=1, max_length=128)


class NoteBody(BaseModel):
    note: str = Field(min_length=control.MIN_NOTE, max_length=500)


class CloseBody(NoteBody):
    instance: str = Field(min_length=1, max_length=128)
    trade_id: str = Field(min_length=1, max_length=512)


class ModeBody(NoteBody):
    instance: str = Field(min_length=1, max_length=64)
    tv_symbol: str = Field(min_length=1, max_length=64)
    mode: Literal["off", "watch", "trade"]


def _matches(supplied: str, secret) -> bool:
    expected = secret.get_secret_value()
    # Always compare (constant time) so timing does not reveal which password is configured.
    return bool(hmac.compare_digest(supplied.encode(), (expected or secrets.token_hex(16)).encode()) and expected)


@router.post("/login", dependencies=[Depends(proxy_guard)])
def login(body: LoginBody, request: Request):
    settings, db = request.app.state.settings, request.app.state.db
    now = time.time()
    failures = [t for t in db.get_state("dash_login_failures", []) if now - t < LOCKOUT_SECONDS]
    if len(failures) >= LOCKOUT_FAILURES:
        raise HTTPException(429, "too_many_attempts_try_again_later")
    account_ok = body.login == settings.mt5_login and body.server.strip() == settings.mt5_server
    role = "admin" if _matches(body.password, settings.mt5_password) and account_ok else None
    if role is None:
        db.set_state("dash_login_failures", failures + [now])
        db.audit("dashboard_login_failed", {"login_matches": account_ok}, now)
        raise HTTPException(401, "invalid_mt5_credentials")
    db.set_state("dash_login_failures", [])
    token = secrets.token_urlsafe(32)
    expires = now + settings.dash_session_hours * 3600
    db.add_session(_hash(token), role, now, expires)
    db.audit("dashboard_login", {"role": role}, now)
    return {"token": token, "role": role, "expires_at": expires}


@router.post("/logout", dependencies=[Depends(proxy_guard)])
def logout(request: Request, current: dict = Depends(session)):
    request.app.state.db.revoke_session(current["token_hash"])
    return {"ok": True}


@router.get("/me", dependencies=[Depends(proxy_guard)])
def me(current: dict = Depends(session)):
    return {"role": current["role"], "expires_at": current["expires_at"]}


# ---------------------------------------------------------------- read models
def _streams(request):
    try:
        return load_streams(request.app.state.settings.engine_config_path)
    except FileNotFoundError:
        return []


def _instance_of(event_id: str) -> str | None:
    parts = event_id.split(":")
    return parts[2] if len(parts) > 2 else None


def _groups(request) -> dict:
    """instance -> dashboard section ("intraday" for 15-minute strategies, else "swing")."""
    return {s.instance: s.group for s in _streams(request)}


def _tf_group(timeframe) -> str:
    return "intraday" if str(timeframe) in ("1", "5", "15", "30") else "swing"


def _open_positions(db, groups=None):
    groups = groups or {}
    snapshot = db.get_state("account_snapshot") or {}
    live = {p["identifier"]: p for p in snapshot.get("positions", [])}
    rows = []
    for record in db.open_positions():
        pos = live.get(record["identifier"], {})
        rows.append({
            "instance": record["instance"], "trade_id": record["trade_id"], "symbol": record["symbol"],
            "tv_symbol": record["tv_symbol"], "side": record["side"], "volume": record["volume"],
            "entry_price": record["entry_price"], "sl": pos.get("sl", record["sl"]), "tp": pos.get("tp", record["tp"]),
            "profit": pos.get("profit"), "opened_at": record["opened_at"], "ticket": record["ticket"],
            "risk_budget": record["risk_budget"], "group": groups.get(record["instance"], "swing"),
        })
    return rows, snapshot


def _closed_positions(db, limit=500, groups=None):
    groups = groups or {}
    history = db.get_state("deal_history") or {}
    rows = []
    for record in db.positions_history(limit):
        if record["status"] != "CLOSED":
            continue
        deal = history.get(str(record["identifier"]), {})
        rows.append({
            "instance": record["instance"], "trade_id": record["trade_id"], "symbol": record["symbol"],
            "side": record["side"], "volume": record["volume"], "entry_price": record["entry_price"],
            "exit_price": deal.get("close_price"), "sl": record["sl"], "tp": record["tp"],
            "opened_at": record["opened_at"], "closed_at": deal.get("closed_at") or record["closed_at"],
            "profit": deal.get("profit"), "risk_budget": record["risk_budget"],
            "group": groups.get(record["instance"], "swing"),
        })
    return rows


def _summary(rows):
    profits = [r["profit"] for r in rows if r.get("profit") is not None]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]
    return {
        "trades": len(profits), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(profits) if profits else None,
        "gross_profit": sum(wins), "gross_loss": sum(losses), "net": sum(profits),
    }


def _signals(db, limit):
    items = []
    for event in db.events(limit):
        try:
            payload = json.loads(event["payload_json"])["context"]
        except (ValueError, KeyError):
            payload = {}
        items.append({
            "at": event["received_at"], "source": payload.get("source", "tradingview"),
            "instance": event["instance"], "symbol": event["symbol"], "broker_symbol": event["broker_symbol"],
            "timeframe": payload.get("timeframe"), "event": event["event_type"], "side": payload.get("side"),
            "price": payload.get("reference_price"), "status": event["status"], "reason": event["error"],
            "group": _tf_group(payload.get("timeframe")),
        })
    for row in db.audit_rows(limit, ["engine_signal_watch_only"]):
        d = row["details"]
        items.append({
            "at": row["at"], "source": "mt5_engine", "instance": _instance_of(d.get("event_id", "")),
            "symbol": d.get("symbol"), "broker_symbol": None, "timeframe": d.get("timeframe"),
            "event": d.get("event"), "side": d.get("side"), "price": d.get("reference_price"),
            "status": "WATCH_ONLY", "reason": "recorded_only", "group": _tf_group(d.get("timeframe")),
        })
    items.sort(key=lambda x: x["at"] or 0, reverse=True)
    return items[:limit]


@router.get("/overview", dependencies=[Depends(proxy_guard), Depends(session)])
def overview(request: Request):
    settings, db = request.app.state.settings, request.app.state.db
    now = time.time()
    beat = db.get_state("worker", {})
    fresh = now - beat.get("at", 0) < settings.worker_health_seconds
    groups = _groups(request)
    positions, snapshot = _open_positions(db, groups)
    status = db.status()
    daily = status["daily_risk"] or {}
    start = daily.get("starting_equity")
    equity = snapshot.get("equity")
    capital = _capital(settings, db, equity)
    return {
        "now": now,
        "health": {"api": True, "worker": fresh, "mt5": bool(fresh and beat.get("connected")),
                   "ready": bool(fresh and beat.get("ready")), "reason": beat.get("reason"),
                   "trading_mode": settings.trading_mode, "engine_mode": settings.engine_mode},
        "entries": {"bot_running": control.bot_running(db),
                    "paused": bool(db.get_state("operator_pause", False)), "safety_hold": db.get_state("safety_hold"),
                    "trading_enabled": settings.trading_enabled, "uncertain_operations": status["uncertain_operations"]},
        "account": {"login": "***" + str(settings.mt5_login)[-3:], "server": settings.mt5_server,
                    "currency": snapshot.get("currency", "USD"), "balance": snapshot.get("balance"),
                    "equity": equity, "margin_free": snapshot.get("margin_free"),
                    "floating": snapshot.get("floating"), "snapshot_at": snapshot.get("at"),
                    "capital": capital, "capital_start": settings.risk_capital},
        "daily": {"starting_equity": start, "today_pl": (equity - start) if equity and start else None,
                  "loss_limit_percent": settings.max_daily_loss_percent,
                  "loss_used_percent": max(0.0, (start - equity) / capital * 100) if equity and start and capital else 0.0,
                  "entries": daily.get("entry_attempts", 0), "max_entries": settings.max_daily_entries,
                  "paused_by_loss": bool(daily.get("paused"))},
        "limits": {"max_open_positions": settings.max_open_positions, "max_risk_percent": settings.max_risk_percent,
                   "max_total_risk_percent": settings.max_total_risk_percent},
        "positions": positions,
        "signals": _signals(db, 8),
        "summary": _summary(_closed_positions(db, groups=groups)),
    }


@router.get("/positions", dependencies=[Depends(proxy_guard), Depends(session)])
def positions(request: Request):
    db = request.app.state.db
    groups = _groups(request)
    open_rows, _ = _open_positions(db, groups)
    closed = _closed_positions(db, groups=groups)
    return {"open": open_rows, "closed": closed, "summary": _summary(closed),
            "close_requests": db.close_requests(25)}


@router.get("/signals", dependencies=[Depends(proxy_guard), Depends(session)])
def signals(request: Request, limit: int = 100):
    return {"signals": _signals(request.app.state.db, max(1, min(limit, 500)))}


def _pattern_text(s) -> str:
    p = s.patterns
    side = {"Short only": "SELL only", "Long only": "BUY only"}.get(p.trade_dir, "BUY + SELL")
    return (f"Classic Chart Patterns · {side} · swing {p.piv_len}/{p.piv_r} · stop at pattern swing + {p.sl_buf}× ATR · "
            f"target {p.tp_mult}× pattern height · exit after {p.max_hold} bars · "
            f"{'reverse' if p.rev_on_opp else 'ignore'} on opposite signal · Risk {s.risk_percent}%")


def _meanrev_text(s) -> str:
    m = s.meanrev
    side = {"Short only": "SELL only", "Long only": "BUY only"}.get(m.trade_dir, "BUY + SELL")
    return (f"RSI(2) mean reversion · {side} · BUY when RSI(2) < {m.rsi_level:g} above SMA{m.trend_len} · "
            f"stop {m.stop_atr:g}× ATR · exit on a close back across SMA{m.exit_len} or after {m.max_hold} candles · "
            f"Risk {s.risk_percent}%")


def _breakout_text(s) -> str:
    b = s.breakout
    side = {"Short only": "SELL only", "Long only": "BUY only"}.get(b.trade_dir, "BUY + SELL")
    target = f"target {b.target_r:g}× risk" if b.target_r else "no target"
    return (f"Asian range breakout · {side} · range {b.range_start:02d}:00-{b.range_end:02d}:00 server time · "
            f"first close beyond it until {b.entry_until:02d}:00 · stop at the range {b.stop_mode} · {target} · "
            f"closed before {b.exit_hour:02d}:00 · Risk {s.risk_percent}%")


def _capital(settings, db, equity):
    """Bot capital as the worker computes it (read-only here)."""
    base = db.get_state("risk_capital_base") or {}
    if not settings.risk_capital or equity is None or base.get("capital") != settings.risk_capital:
        return settings.risk_capital or equity
    return min(equity, settings.risk_capital + equity - base["equity"])


@router.get("/strategies", dependencies=[Depends(proxy_guard), Depends(session)])
def strategies(request: Request):
    settings, db = request.app.state.settings, request.app.state.db
    backtests_path = Path(settings.engine_config_path).with_name("backtests.json")
    backtests = json.loads(backtests_path.read_text("utf-8")) if backtests_path.exists() else {}
    closed = _closed_positions(db)
    signal_rows = _signals(db, 500)
    out = []
    for s in _streams(request):
        rule = request.app.state.symbols.rules.get(s.tv_symbol)
        trades = [c for c in closed if c["instance"] == s.instance]
        out.append({
            "instance": s.instance, "tv_symbol": s.tv_symbol, "broker_symbol": rule.broker_symbol if rule else None,
            "symbol_enabled": bool(rule and rule.enabled), "timeframe": s.timeframe, "group": s.group,
            "settings": {"description": _pattern_text(s)} if s.strategy == "patterns" else
                        {"description": _meanrev_text(s)} if s.strategy == "meanrev" else
                        {"description": _breakout_text(s)} if s.strategy == "breakout" else {
                         "sensitivity": s.sensitivity, "atr_length": s.atr_length, "stop_mode": s.stop_mode,
                         "stop_atr": s.stop_atr, "target_mode": s.target_mode, "reward_ratio": s.reward_ratio,
                         "opposite_mode": s.opposite_mode, "direction": s.direction, "htf_filter": s.htf_filter,
                         "risk_percent": s.risk_percent},
            "mode": control.effective_stream_mode(db, s, settings.engine_mode),
            "live": {"signals": sum(1 for x in signal_rows if x["instance"] == s.instance), **_summary(trades)},
            "backtest": backtests.get(s.instance),
        })
    return {"engine_mode": settings.engine_mode, "strategies": out}


@router.get("/equity", dependencies=[Depends(proxy_guard), Depends(session)])
def equity(request: Request, days: int = 30):
    since = time.time() - max(1, min(days, 365)) * 86400
    return {"points": request.app.state.db.equity_history(since)}


@router.get("/audit", dependencies=[Depends(proxy_guard), Depends(session)])
def audit(request: Request, limit: int = 100):
    rows = request.app.state.db.audit_rows(max(1, min(limit, 500)))
    for row in rows:
        row.pop("details_json", None)
    return {"audit": rows}


@router.get("/config", dependencies=[Depends(proxy_guard), Depends(session)])
def config(request: Request):
    s = request.app.state.settings
    return {
        "risk": {"max_risk_percent": s.max_risk_percent, "max_total_risk_percent": s.max_total_risk_percent,
                 "max_daily_loss_percent": s.max_daily_loss_percent, "max_daily_entries": s.max_daily_entries,
                 "max_open_positions": s.max_open_positions, "max_lot": s.max_lot,
                 "max_deviation_points": s.max_deviation_points},
        "symbols": [{"tv_symbol": k, **v.model_dump()} for k, v in request.app.state.symbols.rules.items()],
        "trading_mode": s.trading_mode, "engine_mode": s.engine_mode,
    }


# ---------------------------------------------------------------- admin controls
def _apply(fn):
    try:
        return fn()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/bot/{action}", dependencies=[Depends(proxy_guard), Depends(admin)])
def bot_switch(action: Literal["start", "stop"], request: Request):
    db = request.app.state.db
    _apply(lambda: control.set_bot_running(db, action == "start", ACTOR))
    return {"ok": True, "bot_running": control.bot_running(db)}


@router.post("/control/{action}", dependencies=[Depends(proxy_guard), Depends(admin)])
def control_action(action: Literal["pause", "resume", "acknowledge-hold"], body: NoteBody, request: Request):
    db, settings = request.app.state.db, request.app.state.settings
    if action == "acknowledge-hold":
        _apply(lambda: control.acknowledge_hold(db, settings, body.note, ACTOR))
    else:
        _apply(lambda: control.set_paused(db, action == "pause", body.note, ACTOR))
    return {"ok": True}


@router.post("/positions/close", dependencies=[Depends(proxy_guard), Depends(admin)])
def close_position(body: CloseBody, request: Request):
    _apply(lambda: control.request_close(request.app.state.db, body.instance, body.trade_id, body.note, ACTOR))
    return {"ok": True, "message": "Close requested; the worker executes it within a few seconds."}


@router.post("/positions/close-all", dependencies=[Depends(proxy_guard), Depends(admin)])
def close_all(body: NoteBody, request: Request):
    count = _apply(lambda: control.request_close_all(request.app.state.db, body.note, ACTOR))
    return {"ok": True, "requested": count}


@router.post("/strategies/mode", dependencies=[Depends(proxy_guard), Depends(admin)])
def strategy_mode(body: ModeBody, request: Request):
    stream = next((s for s in _streams(request) if s.instance == body.instance and s.tv_symbol == body.tv_symbol), None)
    if stream is None:
        raise HTTPException(404, "strategy_not_found")
    _apply(lambda: control.set_stream_mode(request.app.state.db, request.app.state.settings, request.app.state.symbols,
                                           stream, body.mode, body.note, ACTOR))
    return {"ok": True, "mode": body.mode}
