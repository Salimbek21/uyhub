"""The golden set and the scorer that reads it (SPEC 6.4).

`make eval-parser` is only useful if it would notice a regression. A harness
that silently scored nothing — an unreadable fixture, a field nobody asserts —
would print a reassuring number forever, so these tests check the harness as
well as the fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
sys.path.insert(0, str(EVAL_DIR))

from golden import (  # noqa: E402
    SPEC_FIELDS,
    GoldenPost,
    load_golden_set,
    score,
)

from uyhub.core.config import Settings, get_settings  # noqa: E402
from uyhub.models.enums import District  # noqa: E402

pytestmark = pytest.mark.unit

MIN_FIXTURES = 150
"""SPEC 6.4 asks for at least this many."""


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("PHONE_HASH_KEY", "golden-test-key")
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="module")
def posts() -> list[GoldenPost]:
    return load_golden_set()


class TestFixtures:
    def test_there_are_enough_of_them(self, posts: list[GoldenPost]) -> None:
        assert len(posts) >= MIN_FIXTURES

    def test_ids_are_unique(self, posts: list[GoldenPost]) -> None:
        """A duplicate id makes a mistake impossible to look up."""
        ids = [post.id for post in posts]
        assert len(ids) == len(set(ids))

    def test_every_post_has_text_and_an_expectation(self, posts: list[GoldenPost]) -> None:
        for post in posts:
            assert post.text.strip(), post.id
            assert post.expected, post.id

    def test_both_outcomes_are_represented(self, posts: list[GoldenPost]) -> None:
        outcomes = {bool(post.expected.get("is_listing", True)) for post in posts}
        assert outcomes == {True, False}

    def test_all_three_scripts_appear(self, posts: list[GoldenPost]) -> None:
        """Uzbek Latin, Uzbek Cyrillic and Russian are different parsing problems."""
        texts = " ".join(post.text for post in posts)
        assert any(ch in texts for ch in "ўқғҳ"), "no Uzbek Cyrillic"
        assert "Продается" in texts or "продается" in texts, "no Russian"
        assert "sotiladi" in texts.lower(), "no Uzbek Latin"

    def test_districts_named_in_fixtures_are_real(self, posts: list[GoldenPost]) -> None:
        """A typo'd district id would score as a permanent miss."""
        named = {
            post.expected["district"] for post in posts if post.expected.get("district") is not None
        }
        assert named <= {district.value for district in District}

    def test_a_price_always_comes_with_a_currency(self, posts: list[GoldenPost]) -> None:
        """The scorer needs both to derive the expected USD value."""
        for post in posts:
            has_amount = "price_amount" in post.expected
            has_currency = "price_currency" in post.expected
            assert has_amount == has_currency, post.id


class TestScorer:
    def test_every_spec_field_is_actually_exercised(
        self, posts: list[GoldenPost], settings: Settings
    ) -> None:
        """A field with nothing to score would read as 100% forever."""
        report = score(posts, settings)
        for name in SPEC_FIELDS:
            assert report.fields[name].total > 0, name

    def test_the_confusion_matrix_adds_up(
        self, posts: list[GoldenPost], settings: Settings
    ) -> None:
        report = score(posts, settings)
        assert sum(report.listing_confusion.values()) == len(posts)

    def test_a_wrong_expectation_is_counted_as_a_mistake(self, settings: Settings) -> None:
        """The scorer must be able to fail, or it is measuring nothing."""
        wrong = GoldenPost(
            id="synthetic-wrong",
            text="3 xonali kvartira Chilonzorda sotiladi, narxi 65 000 $",
            photos=0,
            expected={"is_listing": True, "district": "sergeli"},
            source_file="synthetic",
        )
        report = score([wrong], settings)

        assert report.fields["district"].correct == 0
        assert report.fields["district"].mistakes[0][0] == "synthetic-wrong"

    def test_a_missed_listing_counts_against_every_stated_field(self, settings: Settings) -> None:
        missed = GoldenPost(
            id="synthetic-missed",
            text="Assalomu alaykum",
            photos=0,
            expected={"is_listing": True, "deal_type": "sale", "rooms": 3},
            source_file="synthetic",
        )
        report = score([missed], settings)

        assert report.fields["deal_type"].correct == 0
        assert report.fields["rooms"].correct == 0
        assert report.listing_confusion["false_negative"] == 1

    def test_unstated_fields_are_not_scored(self, settings: Settings) -> None:
        """A post that names no district must not drag district accuracy down."""
        silent = GoldenPost(
            id="synthetic-silent",
            text="Kvartira sotiladi, 3 xonali, narxi 65 000 $. 90 123 45 67",
            photos=0,
            expected={"is_listing": True, "rooms": 3},
            source_file="synthetic",
        )
        report = score([silent], settings)

        assert report.fields["district"].total == 0
        assert report.fields["rooms"].total == 1

    def test_rejection_precision_is_one_when_nothing_was_rejected(self, settings: Settings) -> None:
        kept = GoldenPost(
            id="synthetic-kept",
            text="3 xonali kvartira sotiladi Chilonzor, narxi 65 000 $",
            photos=0,
            expected={"is_listing": True},
            source_file="synthetic",
        )
        assert score([kept], settings).rejection_precision == 1.0

    def test_a_wrongly_kept_post_lowers_precision(self, settings: Settings) -> None:
        wrongly_kept = GoldenPost(
            id="synthetic-junk",
            text="3 xonali kvartira sotiladi Chilonzor, narxi 65 000 $",
            photos=0,
            expected={"is_listing": False},
            source_file="synthetic",
        )
        report = score([wrongly_kept], settings)
        assert report.listing_confusion["false_positive"] == 1
