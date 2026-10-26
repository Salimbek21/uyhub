"""Settings load from the environment and reject nonsense early."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from uyhub.core.config import Settings, get_settings

pytestmark = pytest.mark.unit


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
