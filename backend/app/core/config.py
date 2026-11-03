"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_KEY = "dev-only-change-me-6f1d0c1e9a7b4e2f8c3d5a1b7e9f0a2c"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ConnectHub"
    environment: str = "development"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+psycopg://connecthub:connecthub_dev_password@localhost:5442/connecthub"
    redis_url: str = "redis://localhost:6392/0"

    secret_key: str = _INSECURE_DEFAULT_KEY
    field_encryption_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    public_base_url: str = "http://localhost:8130"
    cors_origins: str = "http://localhost:4230,http://localhost:4200"

    max_payload_bytes: int = 256 * 1024
    signature_tolerance_seconds: int = 300

    ssrf_allowed_hosts: str = ""

    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 300.0
    default_max_attempts: int = 5
    outbox_relay_interval_seconds: float = 2.0
    outbox_batch_size: int = 200
    stuck_delivery_grace_seconds: int = 60
    delivery_lock_margin_seconds: int = 30
    response_body_excerpt_bytes: int = 2048

    demo_user_email: str = "demo@example.com"
    demo_user_password: str = "Demo@12345"

    @model_validator(mode="after")
    def _check_production_secrets(self) -> Settings:
        if self.environment == "production" and (
            self.secret_key == _INSECURE_DEFAULT_KEY or len(self.secret_key) < 32
        ):
            raise ValueError("SECRET_KEY must be set to a strong value in production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ssrf_allowed_host_set(self) -> set[str]:
        return {h.strip().lower() for h in self.ssrf_allowed_hosts.split(",") if h.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
