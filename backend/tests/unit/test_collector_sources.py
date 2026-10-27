"""Parsing operator input into a source reference (SPEC 4.2)."""

from __future__ import annotations

import pytest

from uyhub.collector.sources import parse_ref

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "username"),
    [
        ("@uyhub_test", "uyhub_test"),
        ("uyhub_test", "uyhub_test"),
        ("t.me/uyhub_test", "uyhub_test"),
        ("https://t.me/uyhub_test", "uyhub_test"),
        ("http://t.me/uyhub_test", "uyhub_test"),
        ("  https://t.me/uyhub_test  ", "uyhub_test"),
    ],
)
def test_public_references_resolve_to_a_username(raw: str, username: str) -> None:
    parsed = parse_ref(raw)
    assert parsed.username == username
    assert parsed.invite_link is None
    assert parsed.as_telegram_ref == f"@{username}"


@pytest.mark.parametrize(
    "raw",
    [
        "https://t.me/+AbCdEf123",
        "t.me/+AbCdEf123",
        "https://t.me/joinchat/AbCdEf123",
    ],
)
def test_invite_links_resolve_to_an_invite(raw: str) -> None:
    parsed = parse_ref(raw)
    assert parsed.invite_link == "https://t.me/+AbCdEf123"
    assert parsed.username is None


def test_invite_links_are_not_mistaken_for_usernames() -> None:
    """``joinchat`` is a valid username shape, so the invite rule must win."""
    parsed = parse_ref("https://t.me/joinchat/XYZ")
    assert parsed.username is None
    assert parsed.invite_link == "https://t.me/+XYZ"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "ab",  # too short for a Telegram username
        "1channel",  # must start with a letter
        "https://example.com/uyhub",
        "not a link at all",
    ],
)
def test_unusable_references_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="not a Telegram username"):
        parse_ref(raw)
