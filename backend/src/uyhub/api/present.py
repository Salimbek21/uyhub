"""Turning ORM rows into response models.

Separate from the routers so the one rule that really matters here — that a
phone number has no path into a response — is enforced in one readable place
rather than in every handler.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from uyhub.api.media import public_url
from uyhub.api.schemas import (
    ListingCard,
    ListingDetail,
    ListingPhoto,
    ListingSourceLink,
    PriceObservation,
)
from uyhub.core.config import Settings
from uyhub.models.listing import Listing, PriceHistory
from uyhub.models.listing import ListingPhoto as PhotoRow

CENTS = Decimal("0.01")


def price_per_m2(listing: Listing) -> Decimal | None:
    """What a buyer actually compares flats on. ``None`` without an area."""
    if listing.price_usd is None or not listing.area_m2:
        return None
    return (listing.price_usd / listing.area_m2).quantize(CENTS, rounding=ROUND_HALF_UP)


def to_card(
    listing: Listing,
    *,
    thumb_key: str | None,
    photo_count: int,
    settings: Settings,
) -> ListingCard:
    return ListingCard(
        id=str(listing.id),
        title=listing.title,
        deal_type=listing.deal_type,
        property_type=listing.property_type,
        price_amount=listing.price_amount,
        price_currency=listing.price_currency,
        price_usd=listing.price_usd,
        price_period=listing.price_period,
        price_per_m2=price_per_m2(listing),
        district=listing.district,
        rooms=listing.rooms,
        area_m2=listing.area_m2,
        land_sotix=listing.land_sotix,
        floor=listing.floor,
        floors_total=listing.floors_total,
        thumb_url=public_url(thumb_key, settings=settings),
        photo_count=photo_count,
        first_seen_at=listing.first_seen_at,
    )


def to_detail(
    listing: Listing,
    *,
    photos: list[PhotoRow],
    sources: list[tuple[str, str | None, datetime]],
    price_history: list[PriceHistory],
    settings: Settings,
) -> ListingDetail:
    """The full record, minus everything personal.

    ``sources`` carries the attribution SPEC 13 requires and, because phones
    are never served, is also how a user reaches the seller: the link goes to
    the original post, where the number is.
    """
    cover = photos[0].s3_key_thumb if photos else None
    card = to_card(listing, thumb_key=cover, photo_count=len(photos), settings=settings)

    return ListingDetail(
        **card.model_dump(),
        description=listing.description,
        landmark=listing.landmark,
        address_text=listing.address_text,
        building_type=listing.building_type,
        renovation=listing.renovation,
        negotiable=listing.negotiable,
        status=listing.status,
        last_seen_at=listing.last_seen_at,
        photos=[
            ListingPhoto(
                large_url=public_url(photo.s3_key_large, settings=settings),
                thumb_url=public_url(photo.s3_key_thumb, settings=settings),
                width=photo.width,
                height=photo.height,
            )
            for photo in photos
        ],
        sources=[
            ListingSourceLink(title=title, tg_link=link, seen_at=seen_at)
            for title, link, seen_at in sources
        ],
        price_history=[
            PriceObservation(price_usd=row.price_usd, observed_at=row.observed_at)
            for row in price_history
        ],
    )
