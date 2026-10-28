"""What the parser produces (SPEC 6.2 and 6.3).

Two models, one per stage, because they answer different questions.
:class:`RawExtraction` is what an extractor claims to have read out of the post;
:class:`Extraction` is that after cross-checking, currency conversion and the
sanity rules, and is what gets stored and what Phase 3 builds listings from.

Keeping them apart means the eval can score an extractor on its own output
without normalization quietly improving the number.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from uyhub.models.enums import (
    BuildingType,
    Currency,
    DealType,
    District,
    PricePeriod,
    PropertyType,
    Renovation,
)

TITLE_MAX_LENGTH = 80
"""SPEC 6.2. The column holds 120, which leaves room without inviting its use."""


class RawExtraction(BaseModel):
    """One extractor's reading of a post, before any cross-checking (SPEC 6.2).

    Every field is optional on purpose: inventing a value is worse than leaving
    it null, because a wrong price or district is visible to users while a
    missing one only makes the listing less filterable.
    """

    model_config = ConfigDict(extra="forbid")

    is_listing: bool = True
    reject_reason: str | None = None

    deal_type: DealType | None = None
    property_type: PropertyType | None = None
    rooms: int | None = Field(default=None, ge=1, le=20)
    area_m2: Decimal | None = Field(default=None, gt=0)
    land_sotix: Decimal | None = Field(default=None, gt=0)
    floor: int | None = Field(default=None, ge=-1, le=100)
    floors_total: int | None = Field(default=None, ge=1, le=100)
    building_type: BuildingType = BuildingType.UNKNOWN
    renovation: Renovation = Renovation.UNKNOWN

    price_amount: Decimal | None = Field(default=None, gt=0)
    price_currency: Currency | None = None
    price_period: PricePeriod | None = None
    negotiable: bool = False

    district: District | None = None
    landmark: str | None = None
    address_text: str | None = None

    phones: list[str] = Field(default_factory=list)
    """E.164, in memory only. Hashed and discarded before anything is stored."""

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Extraction(BaseModel):
    """The normalised result, as stored in ``raw_messages.extracted``.

    No plaintext phone number appears here or anywhere downstream — only
    ``phone_hashes`` (docs/DECISIONS.md P.2).
    """

    model_config = ConfigDict(extra="forbid")

    parser_version: int
    is_listing: bool
    reject_reason: str | None = None

    deal_type: DealType | None = None
    property_type: PropertyType | None = None
    rooms: int | None = None
    area_m2: Decimal | None = None
    land_sotix: Decimal | None = None
    floor: int | None = None
    floors_total: int | None = None
    building_type: BuildingType = BuildingType.UNKNOWN
    renovation: Renovation = Renovation.UNKNOWN

    price_amount: Decimal | None = None
    price_currency: Currency | None = None
    price_usd: Decimal | None = None
    price_period: PricePeriod | None = None
    negotiable: bool = False

    district: District | None = None
    landmark: str | None = None
    address_text: str | None = None

    title: str = ""
    description: str | None = None
    phone_hashes: list[str] = Field(default_factory=list)

    quality_score: int = Field(default=0, ge=0, le=100)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    """Which sanity rule fired, so the admin queue can say why."""

    def as_json(self) -> dict[str, object]:
        """JSON-safe dict for the JSONB column: Decimals become strings."""
        return self.model_dump(mode="json")
