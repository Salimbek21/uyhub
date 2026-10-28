"""Reading structure out of a post.

One interface, two implementations over time. :class:`RegexExtractor` is what
ships now; an LLM extractor goes behind the same protocol when
``ANTHROPIC_API_KEY`` arrives, and the pipeline, the storage format and the
eval harness do not change when it does (docs/DECISIONS.md P.4).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from uyhub.core.phones import find_phones
from uyhub.models.enums import Currency, DealType, PricePeriod, PropertyType
from uyhub.parser import regex_extract as rx
from uyhub.parser.districts import DistrictMatch, detect_district
from uyhub.parser.schema import RawExtraction

MULTI_LISTING_ROOM_COUNTS = 2
MULTI_LISTING_ITEMS = 2
MULTI_LISTING_PRICES = 2
"""Thresholds for deciding a post describes several properties (SPEC 6.6).

The signal is the **room count**, not the phone or price count. Measured against
the first 47 real posts: half of them list two phone numbers and two prices and
are a single flat — the Tashkent realtor format is `TEL. x / y` for two contact
numbers and `Narx: 1400$ _ 1200$ Ga Oberladi` for an asking price and the floor
they will accept. Keying on those rejected 49% of real inventory.

Two *different room counts* is what actually distinguishes two properties, and a
numbered list is the other giveaway."""

LANDMARK_MAX_LENGTH = 120

SALE_PRICE_FLOOR_USD = Decimal(5_000)
SALE_PRICE_FLOOR_UZS = Decimal(50_000_000)
"""Where a sale price starts, matching SPEC 6.3's sanity bands.

Plenty of real posts name no verb at all — the Tashkent realtor format is a
labelled list ending in `Narx: 650$`. The price still decides it, in both
directions: nobody sells a flat for six hundred dollars and nobody rents one
for sixty thousand. Measured on the first 47 real posts, keying only on the
upper band left 44 of 46 listings with no deal type."""


class Extractor(Protocol):
    """Turns post text into a structured reading of it."""

    @property
    def name(self) -> str:
        """Identifies the extractor in logs and in the eval report."""
        ...

    def extract(self, text: str, *, has_photos: bool = False) -> RawExtraction: ...


class RegexExtractor:
    """Everything SPEC 5.2 says regular expressions can read.

    Deliberately conservative: a field it cannot read stays null rather than
    being guessed, because a null is merely unfilterable while a wrong value is
    visible to the user.
    """

    name = "regex"

    def extract(self, text: str, *, has_photos: bool = False) -> RawExtraction:
        phones = find_phones(text)
        prices = rx.find_prices(text)

        if self._looks_like_several_listings(text, prices):
            return RawExtraction(
                is_listing=False,
                reject_reason="multi_listing",
                phones=phones,
                confidence=0.0,
            )

        rooms_floors = rx.find_rooms_and_floors(text)
        price = rx.best_price(text)
        district_match = detect_district(text)
        deal_type = self._deal_type(text, price)
        property_type = rx.find_property_type(text)
        land_sotix = rx.find_land_sotix(text)

        extraction = RawExtraction(
            deal_type=deal_type,
            property_type=self._property_type(property_type, land_sotix),
            rooms=rooms_floors.rooms,
            area_m2=rx.find_area_m2(text),
            land_sotix=land_sotix,
            floor=rooms_floors.floor,
            floors_total=rooms_floors.floors_total,
            building_type=rx.find_building_type(text),
            renovation=rx.find_renovation(text),
            price_amount=price.amount if price else None,
            price_currency=price.currency if price else None,
            price_period=self._period(text, deal_type),
            negotiable=rx.is_negotiable(text),
            district=district_match.district if district_match else None,
            landmark=self._landmark(district_match),
            phones=phones,
        )
        return extraction.model_copy(update={"confidence": self._confidence(extraction)})

    @staticmethod
    def _looks_like_several_listings(text: str, prices: list[rx.PriceCandidate]) -> bool:
        """SPEC 6.6, without an LLM to ask.

        A post describing two flats states two different room counts. Two
        prices alone do not qualify — an asking price and a negotiable floor
        are two numbers for one property — and neither do two phone numbers.
        """
        if len(rx.find_all_room_counts(text)) >= MULTI_LISTING_ROOM_COUNTS:
            return True

        distinct_prices = {(p.amount, p.currency) for p in prices}
        return (
            rx.count_list_items(text) >= MULTI_LISTING_ITEMS
            and len(distinct_prices) >= MULTI_LISTING_PRICES
        )

    @staticmethod
    def _deal_type(text: str, price: rx.PriceCandidate | None) -> DealType | None:
        """Sale or rent, falling back to the price when the post names neither.

        Plenty of real posts are a bare list — district, rooms, metres, price,
        phone — with no verb at all. The price still gives it away: nobody
        rents a flat for sixty thousand dollars a month, and nobody sells one
        for four hundred.
        """
        stated = rx.find_deal_type(text)
        if stated is not None:
            return stated
        if price is None:
            return None
        if rx.find_period(text) is not None:
            return DealType.RENT

        floor = SALE_PRICE_FLOOR_USD if price.currency is Currency.USD else SALE_PRICE_FLOOR_UZS
        return DealType.SALE if price.amount >= floor else DealType.RENT

    @staticmethod
    def _property_type(
        found: PropertyType | None, land_sotix: Decimal | None
    ) -> PropertyType | None:
        """A plot size with no other clue means land."""
        if found is None and land_sotix is not None:
            return PropertyType.LAND
        return found

    @staticmethod
    def _period(text: str, deal_type: DealType | None) -> PricePeriod | None:
        """Rent defaults to a monthly price when the post does not say (SPEC 6.2)."""
        explicit = rx.find_period(text)
        if explicit is not None:
            return explicit
        return PricePeriod.MONTH if deal_type is DealType.RENT else None

    @staticmethod
    def _landmark(match: DistrictMatch | None) -> str | None:
        """Only a landmark-derived district yields a landmark string."""
        if match is not None and match.by_landmark:
            return match.matched[:LANDMARK_MAX_LENGTH]
        return None

    @staticmethod
    def _confidence(extraction: RawExtraction) -> float:
        """How much of the post we managed to read.

        Not a probability — it is the share of the fields that matter, present.
        It feeds ``needs_review`` and the quality score, and OPEN_QUESTIONS C6
        is a warning about trusting a self-reported number too far, so this one
        is at least mechanical and auditable.
        """
        weighted = (
            (extraction.deal_type is not None, 0.25),
            (extraction.price_amount is not None, 0.25),
            (extraction.property_type is not None, 0.15),
            (extraction.rooms is not None or extraction.area_m2 is not None, 0.15),
            (extraction.district is not None, 0.10),
            (bool(extraction.phones), 0.10),
        )
        return round(sum(weight for present, weight in weighted if present), 2)
