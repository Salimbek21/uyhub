"""Finding phone numbers without mistaking them for prices (SPEC 5.2).

This is the test file that matters most for privacy: a number missed here is a
listing that cannot be deduplicated, and a price caught here is a price deleted
from the description.
"""

from __future__ import annotations

import pytest

from uyhub.core.config import Settings, get_settings
from uyhub.core.errors import ConfigError
from uyhub.core.phones import find_phones, hash_phone, hash_phones, normalize_phone, strip_phones

pytestmark = pytest.mark.unit

KEY = "test-phone-hash-key"


@pytest.fixture
def settings_with_key(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("PHONE_HASH_KEY", KEY)
    get_settings.cache_clear()
    return get_settings()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Tel: +998 90 123 45 67", ["+998901234567"]),
        ("998901234567", ["+998901234567"]),
        ("8998901234567", ["+998901234567"]),
        ("8 998 90 123 45 67", ["+998901234567"]),
        ("90 123 45 67", ["+998901234567"]),
        ("901234567", ["+998901234567"]),
        ("+998(93)111-22-33", ["+998931112233"]),
        ("Tel: +998-94-555-66-77", ["+998945556677"]),
        ("aloqa 97.777.88.99", ["+998977778899"]),
    ],
)
def test_every_written_form_normalises_to_e164(text: str, expected: list[str]) -> None:
    assert find_phones(text) == expected


def test_several_numbers_are_all_found_in_order() -> None:
    text = "Birinchi: 90 123 45 67, ikkinchi: 93 111 22 33"
    assert find_phones(text) == ["+998901234567", "+998931112233"]


def test_the_same_number_written_twice_appears_once() -> None:
    assert find_phones("901234567 va +998 90 123 45 67") == ["+998901234567"]


@pytest.mark.parametrize(
    "text",
    [
        "Narxi 650 000 000 so'm",
        "Narxi 930 000 000 so'm",
        "Narxi 930000000 sum",
        "Narxi 930000000 som",
        "цена 780 000 000 сум",
        "65 000 у.е.",
    ],
)
def test_a_price_is_never_read_as_a_phone(text: str) -> None:
    """Nine-digit so'm prices and nine-digit mobile numbers look identical."""
    assert find_phones(text) == []


def test_landline_codes_are_not_matched_without_a_country_prefix() -> None:
    """`71` collides with far too many prices to be worth the recall."""
    assert find_phones("71 200 30 40") == []
    assert find_phones("+998 71 200 30 40") == ["+998712003040"]


def test_a_number_of_the_wrong_length_is_not_a_phone() -> None:
    assert find_phones("930 123 45 67") == []
    assert find_phones("90 123 45 6") == []


def test_normalize_phone_returns_the_first_or_none() -> None:
    assert normalize_phone(" 90 123 45 67 ") == "+998901234567"
    assert normalize_phone("not a number") is None


class TestStripping:
    def test_phones_are_removed_and_prices_kept(self) -> None:
        text = "Narxi 650 000 000 so'm. Tel: +998 90 123 45 67 yoki 93 111 22 33"
        stripped = strip_phones(text)
        assert "650 000 000" in stripped
        assert "90" not in stripped.replace("650 000 000", "")

    def test_text_without_phones_is_unchanged(self) -> None:
        text = "3 xonali kvartira, 75 m2"
        assert strip_phones(text) == text


class TestHashing:
    def test_the_hash_is_stable_and_hex(self, settings_with_key: Settings) -> None:
        first = hash_phone("+998901234567", settings_with_key)
        second = hash_phone("+998901234567", settings_with_key)
        assert first == second
        assert len(first) == 64
        assert int(first, 16) >= 0

    def test_different_numbers_hash_differently(self, settings_with_key: Settings) -> None:
        assert hash_phone("+998901234567", settings_with_key) != hash_phone(
            "+998931112233", settings_with_key
        )

    def test_the_key_changes_the_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Which is why rotating PHONE_HASH_KEY orphans suppressed_phones."""
        monkeypatch.setenv("PHONE_HASH_KEY", "key-one")
        get_settings.cache_clear()
        first = hash_phone("+998901234567")

        monkeypatch.setenv("PHONE_HASH_KEY", "key-two")
        get_settings.cache_clear()
        assert hash_phone("+998901234567") != first

    def test_hashing_without_a_key_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unkeyed hash of a nine-digit number is reversible in minutes."""
        monkeypatch.setenv("PHONE_HASH_KEY", "")
        get_settings.cache_clear()
        with pytest.raises(ConfigError, match="PHONE_HASH_KEY"):
            hash_phone("+998901234567")

    def test_hash_phones_preserves_order_and_drops_duplicates(
        self, settings_with_key: Settings
    ) -> None:
        hashes = hash_phones(["+998901234567", "+998931112233", "+998901234567"], settings_with_key)
        assert len(hashes) == 2
        assert hashes[0] == hash_phone("+998901234567", settings_with_key)

    def test_no_plaintext_number_survives_hashing(self, settings_with_key: Settings) -> None:
        digest = hash_phone("+998901234567", settings_with_key)
        assert "901234567" not in digest
