"""Normalisation: conversion, sanity rules, cleaning and scoring (SPEC 6.3)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from uyhub.core.config import Settings, get_settings
from uyhub.models.enums import Currency, DealType, District, PropertyType
from uyhub.parser.normalize import (
    build_title,
    clean_description,
    normalize,
    quality_score,
    sanity_check,
    to_usd,
)
from uyhub.parser.schema import RawExtraction

pytestmark = pytest.mark.unit

RATE = Decimal(12_000)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("PHONE_HASH_KEY", "normalize-test-key")
    get_settings.cache_clear()
    return get_settings()


class TestCurrency:
    def test_usd_is_returned_as_is(self) -> None:
        assert to_usd(Decimal(65_000), Currency.USD, uzs_per_usd=RATE) == Decimal("65000.00")

    def test_uzs_is_converted(self) -> None:
        assert to_usd(Decimal(780_000_000), Currency.UZS, uzs_per_usd=RATE) == Decimal("65000.00")

    def test_uzs_without_a_rate_is_none_not_a_guess(self) -> None:
        """The feed sorts on this column; a wrong number is worse than none."""
        assert to_usd(Decimal(780_000_000), Currency.UZS, uzs_per_usd=None) is None

    def test_a_nonsense_rate_is_refused(self) -> None:
        assert to_usd(Decimal(100), Currency.UZS, uzs_per_usd=Decimal(0)) is None

    def test_no_price_is_none(self) -> None:
        assert to_usd(None, Currency.USD, uzs_per_usd=RATE) is None
        assert to_usd(Decimal(1), None, uzs_per_usd=RATE) is None


class TestDescription:
    def test_phones_mentions_and_links_are_removed(self) -> None:
        text = (
            "SOTILADI\n3 xonali kvartira\nTel: +998 90 123 45 67\n"
            "Batafsil: https://t.me/example\nAdmin: @uyhub_admin"
        )
        cleaned = clean_description(text)
        assert "901234567" not in cleaned.replace(" ", "")
        assert "@uyhub_admin" not in cleaned
        assert "t.me" not in cleaned
        assert "3 xonali kvartira" in cleaned

    def test_the_price_survives(self) -> None:
        cleaned = clean_description("Narxi 650 000 000 so'm. Tel 90 123 45 67")
        assert "650 000 000" in cleaned

    def test_line_breaks_are_kept_but_blank_runs_collapse(self) -> None:
        cleaned = clean_description("bir\n\n\n\nikki")
        assert cleaned == "bir\n\nikki"

    def test_emoji_runs_are_removed_and_single_emoji_kept(self) -> None:
        cleaned = clean_description("🔥🔥🔥 SOTILADI 🏠 kvartira")
        assert "🔥" not in cleaned
        assert "SOTILADI" in cleaned


class TestTitle:
    def test_rooms_type_district_and_area(self) -> None:
        extraction = RawExtraction(
            property_type=PropertyType.APARTMENT,
            rooms=3,
            district=District.CHILONZOR,
            area_m2=Decimal(75),
        )
        assert build_title(extraction) == "3 xonali kvartira, Chilonzor, 75 m²"

    def test_a_house_uses_sotix(self) -> None:
        extraction = RawExtraction(
            property_type=PropertyType.HOUSE,
            district=District.SERGELI,
            land_sotix=Decimal(6),
        )
        assert build_title(extraction) == "Hovli, Sergeli, 6 sotix"

    def test_trailing_zeros_are_trimmed(self) -> None:
        extraction = RawExtraction(property_type=PropertyType.APARTMENT, area_m2=Decimal("75.00"))
        assert "75 m²" in build_title(extraction)

    def test_a_fraction_is_kept(self) -> None:
        extraction = RawExtraction(property_type=PropertyType.HOUSE, land_sotix=Decimal("4.5"))
        assert "4.5 sotix" in build_title(extraction)

    def test_an_empty_extraction_still_produces_something(self) -> None:
        assert build_title(RawExtraction()) == "Obyekt"


class TestSanity:
    def test_a_plausible_listing_has_no_reasons(self) -> None:
        extraction = RawExtraction(
            deal_type=DealType.SALE,
            property_type=PropertyType.APARTMENT,
            rooms=3,
            area_m2=Decimal(75),
            floor=5,
            floors_total=9,
            confidence=0.9,
        )
        assert sanity_check(extraction, Decimal(65_000)) == []

    def test_an_impossible_apartment_area_is_flagged(self) -> None:
        extraction = RawExtraction(
            property_type=PropertyType.APARTMENT, area_m2=Decimal(5), confidence=0.9
        )
        assert "area_out_of_range" in sanity_check(extraction, None)

    def test_a_floor_above_the_total_is_flagged(self) -> None:
        extraction = RawExtraction(floor=12, floors_total=9, confidence=0.9)
        assert "floor_above_total" in sanity_check(extraction, None)

    def test_too_many_rooms_is_flagged(self) -> None:
        extraction = RawExtraction(rooms=20, confidence=0.9)
        assert "too_many_rooms" in sanity_check(extraction, None)

    def test_sale_and_rent_have_different_price_ranges(self) -> None:
        """400 dollars is a normal rent and an impossible sale price."""
        sale = RawExtraction(deal_type=DealType.SALE, confidence=0.9)
        rent = RawExtraction(deal_type=DealType.RENT, confidence=0.9)
        assert "price_out_of_range" in sanity_check(sale, Decimal(400))
        assert "price_out_of_range" not in sanity_check(rent, Decimal(400))

    def test_low_confidence_is_itself_a_reason(self) -> None:
        assert "low_confidence" in sanity_check(RawExtraction(confidence=0.1), None)


class TestQualityScore:
    def test_a_complete_listing_scores_high(self) -> None:
        extraction = RawExtraction(
            price_amount=Decimal(65_000),
            district=District.CHILONZOR,
            rooms=3,
            confidence=1.0,
        )
        assert quality_score(extraction, photo_count=5, source_trust=1.0) >= 90

    def test_an_empty_listing_scores_low(self) -> None:
        assert quality_score(RawExtraction(), photo_count=0, source_trust=0.0) == 0

    def test_photos_help_but_are_capped(self) -> None:
        extraction = RawExtraction(confidence=0.0)
        five = quality_score(extraction, photo_count=5, source_trust=0.0)
        fifteen = quality_score(extraction, photo_count=15, source_trust=0.0)
        assert five == fifteen

    def test_the_score_stays_in_range(self) -> None:
        extraction = RawExtraction(
            price_amount=Decimal(1), district=District.CHILONZOR, rooms=3, confidence=1.0
        )
        assert 0 <= quality_score(extraction, photo_count=100, source_trust=5.0) <= 100


class TestNormalize:
    def test_a_rejected_extraction_carries_only_its_reason(self, settings: Settings) -> None:
        raw = RawExtraction(is_listing=False, reject_reason="multi_listing")
        result = normalize(raw, text="irrelevant", settings=settings)
        assert not result.is_listing
        assert result.reject_reason == "multi_listing"
        assert result.title == ""

    def test_phones_become_hashes_and_never_plaintext(self, settings: Settings) -> None:
        raw = RawExtraction(
            deal_type=DealType.SALE,
            property_type=PropertyType.APARTMENT,
            rooms=3,
            phones=["+998901234567"],
            confidence=0.9,
        )
        result = normalize(raw, text="Tel: +998 90 123 45 67", settings=settings)

        assert len(result.phone_hashes) == 1
        serialised = result.as_json()
        assert "phones" not in serialised
        assert "901234567" not in str(serialised)

    def test_review_reasons_set_the_flag(self, settings: Settings) -> None:
        # 15 is inside what the schema accepts and outside what SPEC 6.3 calls
        # plausible, which is the gap `needs_review` exists to cover.
        raw = RawExtraction(rooms=15, confidence=0.9)
        result = normalize(raw, text="15 xonali", settings=settings)
        assert result.needs_review
        assert "too_many_rooms" in result.review_reasons

    def test_json_is_serialisable(self, settings: Settings) -> None:
        import json

        raw = RawExtraction(
            deal_type=DealType.SALE,
            price_amount=Decimal("65000.50"),
            price_currency=Currency.USD,
            area_m2=Decimal("75.5"),
            confidence=0.8,
        )
        result = normalize(raw, text="post", uzs_per_usd=RATE, settings=settings)
        assert json.loads(json.dumps(result.as_json()))["price_usd"] == "65000.50"
