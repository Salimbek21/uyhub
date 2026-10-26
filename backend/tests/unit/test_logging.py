"""Logging is JSON, carries ``service``, and never leaks personal data.

CLAUDE.md: "Never log phone numbers, session strings, tokens, API keys or full post
text at INFO level or above." These tests are what makes that rule real.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from uyhub.core.logging import (
    REDACTED,
    TEXT_PREVIEW_CHARS,
    configure_logging,
    get_logger,
    redact_sensitive,
)

pytestmark = pytest.mark.unit


def _emit(capsys: pytest.CaptureFixture[str], **fields: Any) -> dict[str, Any]:
    """Log one event as JSON and return it parsed."""
    configure_logging("test-service", level="INFO", log_format="json")
    get_logger("tests.logging").info("event.happened", **fields)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    parsed: dict[str, Any] = json.loads(line)
    return parsed


def test_output_is_json_with_service_and_timestamp(capsys: pytest.CaptureFixture[str]) -> None:
    record = _emit(capsys)
    assert record["event"] == "event.happened"
    assert record["service"] == "test-service"
    assert record["level"] == "info"
    assert record["timestamp"].endswith("Z")


def test_phone_number_in_a_field_is_masked(capsys: pytest.CaptureFixture[str]) -> None:
    record = _emit(capsys, phone="+998901234567")
    assert record["phone"] == REDACTED


@pytest.mark.parametrize(
    "written",
    [
        "+998901234567",
        "998901234567",
        "+998 90 123 45 67",
        "+998-90-123-45-67",
        "+998(90)1234567",
    ],
)
def test_phone_number_inside_free_text_is_masked(
    capsys: pytest.CaptureFixture[str], written: str
) -> None:
    """Phones leak through message bodies, not just through a `phone` field."""
    record = _emit(capsys, landmark=f"call {written} for a viewing")
    assert written not in record["landmark"]
    assert "901234567" not in record["landmark"]


@pytest.mark.parametrize(
    "key",
    [
        "token",
        "bot_token",
        "api_key",
        "anthropic_api_key",
        "api_hash",
        "session_string",
        "password",
        "authorization",
        "init_data",
        "phone_hash_key",
        "backup_passphrase",
    ],
)
def test_sensitive_keys_are_replaced(capsys: pytest.CaptureFixture[str], key: str) -> None:
    record = _emit(capsys, **{key: "the-actual-secret"})
    assert record[key] == REDACTED


def test_sensitive_key_is_matched_case_insensitively(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = _emit(capsys, BOT_TOKEN="the-actual-secret")
    assert record["BOT_TOKEN"] == REDACTED


def test_post_text_is_truncated(capsys: pytest.CaptureFixture[str]) -> None:
    """Full post text is personal data; a short preview is enough to debug."""
    record = _emit(capsys, text="x" * 500)
    assert len(record["text"]) == TEXT_PREVIEW_CHARS + 1  # plus the ellipsis
    assert record["text"].endswith("…")


def test_short_text_is_not_truncated(capsys: pytest.CaptureFixture[str]) -> None:
    record = _emit(capsys, text="3 xonali kvartira")
    assert record["text"] == "3 xonali kvartira"


def test_nested_structures_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    record = _emit(
        capsys,
        payload={"user": {"token": "abc", "note": "ring +998901234567"}, "ok": True},
    )
    assert record["payload"]["user"]["token"] == REDACTED
    assert "901234567" not in record["payload"]["user"]["note"]
    assert record["payload"]["ok"] is True


def test_a_sensitive_key_hides_the_whole_list(capsys: pytest.CaptureFixture[str]) -> None:
    record = _emit(capsys, phones=["+998901234567", "+998909876543"])
    assert record["phones"] == REDACTED


def test_phones_in_an_unlisted_key_are_masked_per_item(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A key nobody thought to add to SENSITIVE_KEYS still must not leak a number."""
    record = _emit(capsys, contacts=["+998901234567", "call +998909876543"])
    assert "901234567" not in str(record["contacts"])
    assert "909876543" not in str(record["contacts"])


def test_deep_nesting_is_bounded() -> None:
    """Redaction must not recurse without limit on a hostile payload."""
    deep: dict[str, Any] = {"token": "leaf"}
    for _ in range(50):
        deep = {"next": deep}
    result = redact_sensitive(None, "info", {"event": "x", "data": deep})
    assert result["event"] == "x"  # did not raise


def test_non_string_values_survive(capsys: pytest.CaptureFixture[str]) -> None:
    record = _emit(capsys, count=42, ratio=0.5, flag=False, missing=None)
    assert record["count"] == 42
    assert record["ratio"] == 0.5
    assert record["flag"] is False
    assert record["missing"] is None


def test_stdlib_logging_is_routed_through_structlog(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Third-party libraries log through stdlib; their output must be JSON too."""
    configure_logging("test-service", level="INFO", log_format="json")
    logging.getLogger("some.vendor.lib").warning("vendor said %s", "+998901234567")
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["service"] == "test-service"
    assert record["level"] == "warning"
    assert "901234567" not in record["event"]


def test_console_format_does_not_crash(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("test-service", level="INFO", log_format="console")
    get_logger("tests.logging").info("human.readable", phone="+998901234567")
    out = capsys.readouterr().out
    assert "human.readable" in out
    assert "901234567" not in out
