from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="forbid")

    webhook_token: SecretStr
    admin_token: SecretStr
    trading_mode: Literal["DISABLED", "DEMO", "LIVE"] = "DISABLED"
    allow_live_trading: bool = False
    trading_enabled: bool = False
    database_path: Path = Path("data/trading.db")
    symbols_path: Path = Path("config/symbols.json")
    log_directory: Path = Path("logs")
    magic_number: int = Field(default=26093001, gt=0, lt=2**31)
    mt5_path: str = ""
    mt5_login: int = Field(default=0, ge=0)
    mt5_password: SecretStr = SecretStr("")
    mt5_server: str = ""
    mt5_timeout_ms: int = Field(default=10000, ge=1000, le=60000)
    mt5_server_utc_offset_seconds: int = Field(default=0, ge=-43200, le=50400)
    max_risk_percent: float = Field(default=0.5, gt=0, le=5, allow_inf_nan=False)
    max_total_risk_percent: float = Field(default=2, gt=0, le=20, allow_inf_nan=False)
    max_daily_loss_percent: float = Field(default=3, gt=0, le=20, allow_inf_nan=False)
    max_daily_entries: int = Field(default=10, ge=1)
    max_open_positions: int = Field(default=5, ge=1, le=100)
    max_lot: float = Field(default=1, gt=0, allow_inf_nan=False)
    max_margin_fraction: float = Field(default=0.8, gt=0, le=0.95, allow_inf_nan=False)
    max_deviation_points: int = Field(default=20, ge=0, le=1000)
    risk_cost_buffer_percent: float = Field(default=10, ge=0, lt=100, allow_inf_nan=False)
    max_event_age_seconds: int = Field(default=120, ge=5, le=3600)
    max_signal_age_seconds: int = Field(default=300, ge=5, le=86400)
    max_future_skew_seconds: int = Field(default=15, ge=0, le=60)
    max_tick_age_seconds: int = Field(default=15, ge=1, le=300)
    max_retries: int = Field(default=5, ge=0, le=20)
    retry_base_seconds: float = Field(default=2, gt=0, le=60)
    worker_poll_seconds: float = Field(default=1, ge=0.1, le=30)
    worker_health_seconds: int = Field(default=30, ge=5)
    max_body_bytes: int = Field(default=16384, ge=1024, le=65536)
    max_queue_size: int = Field(default=10000, ge=1)
    allowed_strategies: list[str] = ["bytefx_ut_multi_asset"]
    allowed_versions: list[str] = ["1.1.0"]
    allowed_instances: list[str] = ["main"]
    allowed_timeframes: list[str] = ["15", "60", "240"]
    webhook_allowed_ips: list[str] = ["127.0.0.1", "::1"]
    enable_docs: bool = False

    @model_validator(mode="after")
    def validate_configuration(self):
        secrets = [self.webhook_token.get_secret_value(), self.admin_token.get_secret_value()]
        if any(len(value) < 32 or "REPLACE" in value or not value.isascii() for value in secrets):
            raise ValueError("Generate distinct ASCII secrets with 'python -m app.cli init-config'")
        if secrets[0] == secrets[1]:
            raise ValueError("Webhook and admin tokens must differ")
        if self.trading_mode == "LIVE" and not self.allow_live_trading:
            raise ValueError("LIVE mode requires ALLOW_LIVE_TRADING=true")
        if self.trading_mode != "DISABLED" and (
            self.mt5_login <= 0 or not self.mt5_server or not self.mt5_path
        ):
            raise ValueError("Set MT5_PATH, MT5_LOGIN and MT5_SERVER before enabling a connection")
        for values in [
            self.allowed_strategies,
            self.allowed_versions,
            self.allowed_instances,
            self.allowed_timeframes,
            self.webhook_allowed_ips,
        ]:
            if not values:
                raise ValueError("All allowlists must be nonempty")
        for value in self.webhook_allowed_ips:
            ip_network(value, strict=False)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
