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
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="CORS_ALLOW_ORIGINS"
    )
    """Exact origins allowed to call the API — the Mini App's, and nothing else.

    ``NoDecode`` stops pydantic-settings from trying to JSON-parse the value
    before validation, which is what lets the comma-separated spelling below
    reach the validator at all.

    SPEC 9.3 asks for strict CORS. Empty means no browser origin is allowed,
    which is the right default: a missing variable must not silently open the
    API to every site."""

    media_public_base_url: str = Field(
        default="http://localhost:19000/uyhub-media",
        alias="MEDIA_PUBLIC_BASE_URL",
    )
    """Where the public bucket is reachable from a browser. Derivatives only —
    originals stay private and are never addressed through this."""

    api_rate_limit_per_minute: int = Field(
        default=120, ge=1, le=10_000, alias="API_RATE_LIMIT_PER_MINUTE"
    )
    api_rate_limit_burst: int = Field(default=40, ge=1, le=10_000, alias="API_RATE_LIMIT_BURST")

    api_allow_insecure_auth: bool = Field(default=False, alias="API_ALLOW_INSECURE_AUTH")
    """Accept requests with no ``initData`` and treat them as a fixed test user.

    This exists so the feed can be opened in a plain browser before a
    ``BOT_TOKEN`` is issued. It disables the only check that proves a caller
    came from Telegram, so startup refuses it in production outright rather
    than trusting that nobody set it (DECISIONS 4.5)."""

    # -- Bot -----------------------------------------------------------------
    bot_token: SecretStr = Field(default=SecretStr(""), alias="BOT_TOKEN")
    """From @BotFather. The API needs it only to verify ``initData``
    signatures; the bot itself arrives in a later phase."""

    # -- Collector (Telethon userbot) ----------------------------------------
    # The pair identifies the application, not the account; logging in is a
    # separate, human-run step (SPEC 4.1).
    tg_api_id: int = Field(default=0, ge=0, alias="TG_API_ID")
    tg_api_hash: SecretStr = Field(default=SecretStr(""), alias="TG_API_HASH")
    tg_session_path: Path = Field(
        default=Path("/data/sessions/uyhub.session"), alias="TG_SESSION_PATH"
    )
    collector_max_joins_per_day: int = Field(
        default=5, ge=0, le=50, alias="COLLECTOR_MAX_JOINS_PER_DAY"
    )
    collector_backfill_days: int = Field(default=7, ge=0, le=365, alias="COLLECTOR_BACKFILL_DAYS")

    # -- Parser --------------------------------------------------------------
    parser_version: int = Field(default=1, ge=1, alias="PARSER_VERSION")
    """Bumped whenever extraction rules change, so `parser reparse
    --version-below N` can find everything parsed by the older logic."""

    llm_enabled: bool = Field(default=False, alias="LLM_ENABLED")
    """Off until ANTHROPIC_API_KEY exists; the regex extractor runs alone
    (docs/DECISIONS.md P.4)."""

    phone_hash_key: SecretStr = Field(default=SecretStr(""), alias="PHONE_HASH_KEY")
    """HMAC key for phone hashes. Changing it orphans every `suppressed_phones`
    row and un-suppresses listings whose owners asked for removal."""

    cbu_api_url: str = Field(
        default="https://cbu.uz/uz/arkhiv-kursov-valyut/json/",
        alias="CBU_API_URL",
    )

    # -- Dedup and lifecycle -------------------------------------------------
    dedup_lookback_days: int = Field(default=60, ge=1, le=365, alias="DEDUP_LOOKBACK_DAYS")
    """How far back a repost can match an existing listing (SPEC 7.1)."""

    dedup_simhash_max_distance: int = Field(
        default=12, ge=0, le=64, alias="DEDUP_SIMHASH_MAX_DISTANCE"
    )
    """SPEC 7.1 suggests 6. Measured on real posts, a repost of the same flat
    with the usual small edits lands at 9 bits while a different flat is 26, so
    6 would never fire. SPEC calls these config values; see DECISIONS 3.7."""
    dedup_phash_max_distance: int = Field(default=6, ge=0, le=64, alias="DEDUP_PHASH_MAX_DISTANCE")
    dedup_price_tolerance_pct: float = Field(
        default=5.0, ge=0.0, le=100.0, alias="DEDUP_PRICE_TOLERANCE_PCT"
    )

    listing_ttl_days_sale: int = Field(default=30, ge=1, le=365, alias="LISTING_TTL_DAYS_SALE")
    listing_ttl_days_rent: int = Field(default=14, ge=1, le=365, alias="LISTING_TTL_DAYS_RENT")

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

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept `a,b` as well as a JSON list — env files are written by hand."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _refuse_insecure_auth_in_production(self) -> Settings:
        if self.api_allow_insecure_auth and self.is_production:
            msg = (
                "API_ALLOW_INSECURE_AUTH is a development-only escape hatch and "
                "cannot be enabled when APP_ENV=production: it accepts any caller "
                "as a signed-in user"
            )
            raise ValueError(msg)
        return self

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

    @property
    def has_telegram_credentials(self) -> bool:
        """True when ``TG_API_ID``/``TG_API_HASH`` are both set.

        The collector refuses to start without them; everything else (tests, the
        API, migrations) runs fine with the empty defaults.
        """
        return self.tg_api_id > 0 and bool(self.tg_api_hash.get_secret_value())

    @property
    def has_bot_token(self) -> bool:
        """True when ``initData`` signatures can actually be verified."""
        return bool(self.bot_token.get_secret_value())


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
