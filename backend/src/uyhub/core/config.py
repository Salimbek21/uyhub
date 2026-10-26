"""Application configuration.

All configuration comes from environment variables through pydantic-settings
(CLAUDE.md "Code rules"). Variable names are flat and match the names used in
docs/SPEC.md so there is exactly one spelling for each value.

Only the variables a phase actually uses are declared here. ``.env.example``
documents every variable the full system will need, grouped by phase; ``extra="ignore"``
means a ``.env`` that already carries later-phase variables will not break startup.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
LogFormat = Literal["json", "console"]


class Settings(BaseSettings):
    """Runtime configuration, read once per process."""

    model_config = SettingsConfigDict(
        # Works whether the process is started from the repository root or backend/.
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application ---------------------------------------------------------
    app_env: Environment = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: LogFormat = Field(default="json", alias="LOG_FORMAT")

    # -- PostgreSQL ----------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://uyhub:uyhub@localhost:5432/uyhub",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=10, ge=1, le=100, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=5, ge=0, le=100, alias="DB_MAX_OVERFLOW")
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    # -- Redis ---------------------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # -- Object storage (MinIO in every environment) -------------------------
    s3_endpoint_url: str = Field(default="http://localhost:9000", alias="S3_ENDPOINT_URL")
    s3_access_key: str = Field(default="uyhub", alias="S3_ACCESS_KEY")
    s3_secret_key: SecretStr = Field(default=SecretStr("uyhub-dev-secret"), alias="S3_SECRET_KEY")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_bucket_raw: str = Field(default="uyhub-raw", alias="S3_BUCKET_RAW")
    s3_bucket_media: str = Field(default="uyhub-media", alias="S3_BUCKET_MEDIA")

    # -- API -----------------------------------------------------------------
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, alias="API_PORT")

    # -- Observability -------------------------------------------------------
    sentry_dsn: SecretStr | None = Field(default=None, alias="SENTRY_DSN")

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        upper = value.upper()
        if upper not in allowed:
            msg = f"LOG_LEVEL must be one of {sorted(allowed)}, got {value!r}"
            raise ValueError(msg)
        return upper

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            msg = (
                "DATABASE_URL must use the asyncpg driver "
                "(postgresql+asyncpg://...); all I/O in this project is async"
            )
            raise ValueError(msg)
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def safe_database_url(self) -> str:
        """``database_url`` with the password replaced, safe to log."""
        return _mask_url_password(self.database_url)

    @property
    def safe_redis_url(self) -> str:
        """``redis_url`` with the password replaced, safe to log."""
        return _mask_url_password(self.redis_url)

    @property
    def sync_database_url(self) -> str:
        """Same database, synchronous driver — some tooling cannot speak asyncpg."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _mask_url_password(url: str) -> str:
    parts = urlsplit(url)
    if parts.password is None:
        return url
    userinfo = f"{parts.username}:***" if parts.username else "***"
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{userinfo}@{parts.hostname or ''}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Tests clear the cache via ``get_settings.cache_clear()`` after patching the
    environment; see ``tests/conftest.py``.
    """
    return Settings()
