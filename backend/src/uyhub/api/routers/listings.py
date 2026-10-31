"""`GET /v1/listings` and `GET /v1/listings/{id}` (SPEC 9.2)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.api import cursor as cursor_codec
from uyhub.api.deps import CurrentUser, RedisDep, SessionDep, SettingsDep, enforce_rate_limit
from uyhub.api.feed import (
    PAGE_SIZE_DEFAULT,
    PAGE_SIZE_MAX,
    FeedFilters,
    Sort,
    count_query,
    cursor_for,
    page_query,
    visible,
)
from uyhub.api.present import to_card, to_detail
from uyhub.api.schemas import ListingCard, ListingDetail, Page
from uyhub.core.logging import get_logger
from uyhub.models.enums import DealType, District, PropertyType
from uyhub.models.listing import Listing, ListingPhoto, ListingSource, PriceHistory
from uyhub.models.telegram import Source

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["listings"], dependencies=[Depends(enforce_rate_limit)])

TOTAL_CACHE_SECONDS = 60
"""How long a filter set's match count is reused.

Counting is the most expensive part of the request at 200k rows, and the
number only has to be good enough to render "1 240 results" (DECISIONS 4.3)."""


@router.get("/listings", response_model=Page[ListingCard])
async def list_listings(
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    _user: CurrentUser,
    deal_type: DealType | None = None,
    property_type: PropertyType | None = None,
    district: Annotated[list[District] | None, Query()] = None,
    rooms_min: Annotated[int | None, Query(ge=0, le=50)] = None,
    rooms_max: Annotated[int | None, Query(ge=0, le=50)] = None,
    price_min: Annotated[Decimal | None, Query(ge=0)] = None,
    price_max: Annotated[Decimal | None, Query(ge=0)] = None,
    area_min: Annotated[Decimal | None, Query(ge=0)] = None,
    area_max: Annotated[Decimal | None, Query(ge=0)] = None,
    has_photos: bool = False,
    q: Annotated[str | None, Query(max_length=120)] = None,
    sort: Sort = Sort.NEW,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = PAGE_SIZE_DEFAULT,
) -> Page[ListingCard]:
    """One page of the feed, newest first unless asked otherwise."""
    filters = FeedFilters(
        deal_type=deal_type,
        property_type=property_type,
        districts=tuple(district or ()),
        rooms_min=rooms_min,
        rooms_max=rooms_max,
        price_min=price_min,
        price_max=price_max,
        area_min=area_min,
        area_max=area_max,
        has_photos=has_photos,
        q=q,
        sort=sort,
    )
    fingerprint = filters.fingerprint()

    decoded = None
    if cursor is not None:
        try:
            decoded = cursor_codec.decode(cursor, sort=sort.value, fingerprint=fingerprint)
        except cursor_codec.CursorError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.reason) from exc

    rows = list((await session.execute(page_query(filters, decoded, limit))).scalars())
    has_more = len(rows) > limit
    listings = rows[:limit]

    photos = await _photo_summary(session, [listing.id for listing in listings])
    items = [
        to_card(
            listing,
            thumb_key=photos[listing.id][0],
            photo_count=photos[listing.id][1],
            settings=settings,
        )
        for listing in listings
    ]

    next_cursor = (
        cursor_codec.encode(cursor_for(listings[-1], filters)) if has_more and listings else None
    )
    total = await _total(session, redis, filters, fingerprint)
    return Page[ListingCard](items=items, next_cursor=next_cursor, total=total)


@router.get("/listings/{listing_id}", response_model=ListingDetail)
async def get_listing(
    listing_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    _user: CurrentUser,
) -> ListingDetail:
    """Everything about one listing except the seller's phone number.

    There is no endpoint that returns the phone: it is stored only as an HMAC
    hash (docs/DECISIONS.md P.2). `sources` links to the original posts, which
    is both the attribution SPEC 13 requires and where the number actually is.
    """
    listing = (
        await session.execute(select(Listing).where(Listing.id == listing_id, *visible()))
    ).scalar_one_or_none()
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="listing_not_found")

    photos = list(
        (
            await session.execute(
                select(ListingPhoto)
                .where(ListingPhoto.listing_id == listing.id)
                .order_by(ListingPhoto.position)
            )
        ).scalars()
    )
    sources = [
        (title, link, seen_at)
        for title, link, seen_at in (
            await session.execute(
                select(Source.title, ListingSource.tg_link, ListingSource.seen_at)
                .join(Source, Source.id == ListingSource.source_id)
                .where(ListingSource.listing_id == listing.id)
                .order_by(ListingSource.seen_at)
            )
        ).all()
    ]
    history = list(
        (
            await session.execute(
                select(PriceHistory)
                .where(PriceHistory.listing_id == listing.id)
                .order_by(PriceHistory.observed_at)
            )
        ).scalars()
    )

    return to_detail(
        listing,
        photos=photos,
        sources=sources,
        price_history=history,
        settings=settings,
    )


async def _photo_summary(
    session: AsyncSession, listing_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str | None, int]]:
    """Cover thumbnail and photo count for a page of listings.

    One extra query for the whole page rather than one per card: twenty round
    trips per request is the classic way to miss a 200 ms budget.
    """
    summary: dict[uuid.UUID, tuple[str | None, int]] = defaultdict(lambda: (None, 0))
    if not listing_ids:
        return summary

    rows = (
        await session.execute(
            select(ListingPhoto.listing_id, ListingPhoto.s3_key_thumb, ListingPhoto.position)
            .where(ListingPhoto.listing_id.in_(listing_ids))
            .order_by(ListingPhoto.listing_id, ListingPhoto.position)
        )
    ).all()

    counts: dict[uuid.UUID, int] = defaultdict(int)
    covers: dict[uuid.UUID, str | None] = {}
    for listing_id, thumb_key, _position in rows:
        counts[listing_id] += 1
        # Rows arrive in position order, so the first one seen is the cover.
        if listing_id not in covers:
            covers[listing_id] = thumb_key

    for listing_id in listing_ids:
        summary[listing_id] = (covers.get(listing_id), counts[listing_id])
    return summary


async def _total(
    session: AsyncSession,
    redis: Redis,
    filters: FeedFilters,
    fingerprint: str,
) -> int | None:
    """How many listings match, cached per filter set.

    Returns ``None`` if counting fails, which the client renders as "no count"
    rather than as zero — an empty-looking feed full of results would be worse
    than an honest blank.
    """
    key = f"feed:total:{fingerprint}"
    try:
        cached = await redis.get(key)
        if cached is not None:
            return int(cached)
    except (RedisError, ValueError):
        log.warning("api.total_cache_unavailable", exc_info=True)

    total = (await session.execute(count_query(filters))).scalar_one()
    try:
        await redis.set(key, total, ex=TOTAL_CACHE_SECONDS)
    except RedisError:
        log.warning("api.total_cache_write_failed", exc_info=True)
    return total
