"""Response shapes for ``/v1`` (SPEC 9.2).

These mirror ``miniapp/src/types.ts`` field for field. That file was written
first, against the spec, and is what every Mini App screen is already built
around — so it is the contract. Nothing enforces the correspondence
automatically (DECISIONS 4.6), which means a field renamed on one side has to
be renamed on the other by hand.

Nothing here exposes a phone number or an original photo key. There is no
contact endpoint at all: phones are stored only as HMAC hashes, so there is
nothing to reveal (docs/DECISIONS.md P.2). The detail response links to the
original posts instead, which is also the attribution SPEC 13 requires.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

from uyhub.models.enums import (
    BuildingType,
    Currency,
    DealType,
    District,
    ListingStatus,
    PricePeriod,
    PropertyType,
    Renovation,
)

Number = Annotated[
    Decimal,
    PlainSerializer(float, return_type=float, when_used="json"),
]
"""A decimal that goes over the wire as a JSON number, not a string.

Pydantic serialises ``Decimal`` as a string by default, which is right for
money in general but wrong here: ``miniapp/src/types.ts`` declares these fields
as ``number``, and JavaScript has no decimal type to receive a string into
anyway. Every value involved — prices in dollars, areas in square metres — is
far inside the range a float64 represents exactly enough to display.

Storage and arithmetic stay on ``Decimal``; only the JSON encoding changes."""


class ListingCard(BaseModel):
    """One card in the feed — ``GET /v1/listings``."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    deal_type: DealType
    property_type: PropertyType
    price_amount: Number | None
    price_currency: Currency | None
    price_usd: Number | None
    price_period: PricePeriod | None
    price_per_m2: Number | None
    district: District | None
    rooms: int | None
    area_m2: Number | None
    land_sotix: Number | None
    floor: int | None
    floors_total: int | None
    thumb_url: str | None
    photo_count: int
    first_seen_at: datetime
    is_favorite: bool = False
    """Always false for now: favourites live in the Mini App's local storage
    until the write path is built, and the client overlays its own set."""


class ListingPhoto(BaseModel):
    large_url: str | None
    thumb_url: str | None
    width: int | None
    height: int | None


class ListingSourceLink(BaseModel):
    """Where a listing was seen. The attribution SPEC 13 requires, and — since
    we never serve phones — the way a user reaches the seller."""

    title: str
    tg_link: str | None
    seen_at: datetime


class PriceObservation(BaseModel):
    price_usd: Number | None
    observed_at: datetime


class ListingDetail(ListingCard):
    """Full detail — ``GET /v1/listings/{id}``. Never includes phones."""

    description: str | None
    landmark: str | None
    address_text: str | None
    building_type: BuildingType
    renovation: Renovation
    negotiable: bool
    status: ListingStatus
    last_seen_at: datetime
    photos: list[ListingPhoto]
    sources: list[ListingSourceLink]
    price_history: list[PriceObservation]


class Page[T](BaseModel):
    """Cursor-paginated result (SPEC 9.2)."""

    items: list[T]
    next_cursor: str | None
    total: int | None
    """Counted on the first page and carried in the cursor's cache afterwards,
    so the number does not jump between pages. ``None`` when the count was not
    computed (DECISIONS 4.3)."""


class DistrictOption(BaseModel):
    """A district with the names the Mini App shows (SPEC 9.2 ``/meta``)."""

    id: District
    name_uz: str
    name_ru: str


class PriceRange(BaseModel):
    """Slider bounds for one deal type, in USD."""

    deal_type: DealType
    min_usd: Number | None
    max_usd: Number | None


class Meta(BaseModel):
    """``GET /v1/meta`` — everything the filter sheet needs to render."""

    deal_types: list[DealType]
    property_types: list[PropertyType]
    districts: list[DistrictOption]
    building_types: list[BuildingType]
    renovations: list[Renovation]
    sorts: list[str]
    price_ranges: list[PriceRange]
