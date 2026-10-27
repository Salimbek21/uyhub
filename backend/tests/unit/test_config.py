"""Settings load from the environment and reject nonsense early."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from uyhub.core.config import Settings, get_settings

pytestmark = pytest.mark.unit

FAKE_API_HASH = "replace-with-your-32-char-hash"
"""Deliberately words rather than realistic hex, so the gitleaks hook stays armed."""


def test_defaults_are_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_env == "local"
    assert settings.is_production is False


def test_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_PORT", "9999")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_env == "production"
    assert settings.api_port == 9999
    assert settings.is_production is True


def test_log_level_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert Settings(_env_file=None).log_level == "DEBUG"  # type: ignore[call-arg]


def test_invalid_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "chatty")
    with pytest.raises(ValidationError, match="LOG_LEVEL must be one of"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_sync_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A psycopg2-style URL would silently block the event loop."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://uyhub:pw@localhost:5432/uyhub")
    with pytest.raises(ValidationError, match="asyncpg"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_unknown_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Later-phase variables in .env must not break an earlier-phase service."""
    monkeypatch.setenv("BOT_TOKEN", "not-read-until-phase-6")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "10")
    Settings(_env_file=None)  # type: ignore[call-arg]


def test_api_port_must_be_a_valid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_PORT", "70000")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


class TestCollectorSettings:
    """Phase 1 settings. The defaults must let everything else run without them."""

    def test_absent_credentials_are_not_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TG_API_ID", raising=False)
        monkeypatch.delenv("TG_API_HASH", raising=False)
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.has_telegram_credentials is False

    def test_both_credentials_are_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TG_API_ID", "1234567")
        monkeypatch.delenv("TG_API_HASH", raising=False)
        assert Settings(_env_file=None).has_telegram_credentials is False  # type: ignore[call-arg]

        monkeypatch.setenv("TG_API_HASH", FAKE_API_HASH)
        assert Settings(_env_file=None).has_telegram_credentials is True  # type: ignore[call-arg]

    def test_api_hash_is_a_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """It must not turn up in a traceback or a log line (CLAUDE.md)."""
        monkeypatch.setenv("TG_API_HASH", FAKE_API_HASH)
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert "0123456789abcdef" not in repr(settings)
        assert settings.tg_api_hash.get_secret_value() == FAKE_API_HASH

    def test_join_budget_defaults_are_conservative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COLLECTOR_MAX_JOINS_PER_DAY", raising=False)
        monkeypatch.delenv("COLLECTOR_BACKFILL_DAYS", raising=False)
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.collector_max_joins_per_day == 5
        assert settings.collector_backfill_days == 7

    def test_an_absurd_join_budget_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A typo here is how an account gets banned."""
        monkeypatch.setenv("COLLECTOR_MAX_JOINS_PER_DAY", "500")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_session_path_is_a_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TG_SESSION_PATH", "/data/sessions/uyhub.session")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.tg_session_path.name == "uyhub.session"


class TestSafeUrls:
    """Connection strings must never reach a log with their password intact."""

    def test_database_password_is_masked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+asyncpg://uyhub:sup3rs3cret@db.internal:5432/uyhub"
        )
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert "sup3rs3cret" not in settings.safe_database_url
        assert settings.safe_database_url == (
            "postgresql+asyncpg://uyhub:***@db.internal:5432/uyhub"
        )

    def test_redis_password_is_masked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://default:hunter2@cache.internal:6379/0")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert "hunter2" not in settings.safe_redis_url

    def test_url_without_password_is_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.safe_redis_url == "redis://localhost:6379/0"


def test_s3_secret_is_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_SECRET_KEY", "minio-secret-value")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "minio-secret-value" not in repr(settings)
    assert settings.s3_secret_key.get_secret_value() == "minio-secret-value"


def test_sync_database_url_property(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    assert Settings(_env_file=None).sync_database_url == "postgresql://u:p@h:5432/d"  # type: ignore[call-arg]


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
