from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import dashboard, health, webhook
from app.config import Settings, get_settings
from app.database import Database
from app.logging_config import configure_logging
from app.security.webhook_auth import IntakeLimiter
from app.trading.symbol_mapper import SymbolMapper


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        configure_logging(settings, "api")
        app.state.db.initialize()
        yield

    app = FastAPI(
        title="BYTEFX Auto Trader",
        version="1.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.state.settings = settings
    app.state.db = Database(settings.database_path)
    app.state.symbols = SymbolMapper(settings.symbols_path)
    app.state.limiter = IntakeLimiter()
    app.include_router(webhook.router)
    app.include_router(health.router)
    app.include_router(dashboard.router)
    return app
