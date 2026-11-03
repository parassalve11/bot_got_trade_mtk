import time

from fastapi import APIRouter, Depends, Request

from app.security.webhook_auth import authenticate_admin

router = APIRouter()


@router.get("/health")
def health(request: Request):
    state = request.app.state.db.get_state("worker", {})
    fresh = time.time() - state.get("at", 0) < request.app.state.settings.worker_health_seconds
    return {
        "status": "ok" if fresh and state.get("ready") else "degraded",
        "api": True,
        "worker": fresh,
        "mt5": bool(fresh and state.get("connected")),
        "trading_mode": request.app.state.settings.trading_mode,
    }


@router.get("/health/mt5", dependencies=[Depends(authenticate_admin)])
def mt5_health(request: Request):
    state = request.app.state.db.get_state("worker", {})
    fresh = time.time() - state.get("at", 0) < request.app.state.settings.worker_health_seconds
    return {**state, "fresh": fresh, "connected": bool(fresh and state.get("connected"))}


@router.get("/api/v1/status", dependencies=[Depends(authenticate_admin)])
def status(request: Request):
    db = request.app.state.db
    return {
        **db.status(),
        "worker": db.get_state("worker", {}),
        "operator_pause": db.get_state("operator_pause", False),
        "safety_hold": db.get_state("safety_hold", None),
    }
