"""`GET /v1/meta` — everything the filter sheet needs to render (SPEC 9.2).

The Mini App could hardcode the enums, and then every new district or
renovation grade would need a front-end release to become filterable. Serving
them means the two halves cannot disagree about what values exist.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.api.deps import CurrentUser, RedisDep, SessionDep, SettingsDep, enforce_rate_limit
from uyhub.api.feed import Sort, visible
from uyhub.api.schemas import DistrictOption, Meta, PriceRange
from uyhub.core.logging import get_logger
from uyhub.i18n import DISTRICT_NAMES_RU, DISTRICT_NAMES_UZ
from uyhub.models.enums import (
    BuildingType,
    DealType,
    District,
    PropertyType,
    Renovation,
)
from uyhub.models.listing import Listing

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["meta"], dependencies=[Depends(enforce_rate_limit)])

CACHE_KEY = "meta:v1"
CACHE_SECONDS = 600
"""Only the price ranges move, and a slider whose end is ten minutes stale is
indistinguishable from one that is current."""


@router.get("/meta", response_model=Meta)
async def get_meta(
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    _user: CurrentUser,
) -> Meta:
    """Enums, district names in both languages, and slider bounds."""
    try:
        cached = await redis.get(CACHE_KEY)
        if cached is not None:
            return Meta.model_validate(json.loads(cached))
    except (RedisError, ValueError):
        log.warning("api.meta_cache_unavailable", exc_info=True)

    meta = Meta(
        deal_types=list(DealType),
        property_types=list(PropertyType),
        districts=[
            DistrictOption(
                id=district,
                name_uz=DISTRICT_NAMES_UZ[district],
                name_ru=DISTRICT_NAMES_RU[district],
            )
            for district in District
        ],
        building_types=list(BuildingType),
        renovations=list(Renovation),
        sorts=[sort.value for sort in Sort],
        price_ranges=await _price_ranges(session),
    )

    try:
        await redis.set(CACHE_KEY, meta.model_dump_json(), ex=CACHE_SECONDS)
    except RedisError:
        log.warning("api.meta_cache_write_failed", exc_info=True)
    return meta


async def _price_ranges(session: AsyncSession) -> list[PriceRange]:
    """Observed price bounds per deal type, for the filter sheet's slider.

    Taken from the visible listings rather than from a constant, so a slider
    never has a range with nothing in it. Both ends are ``None`` when nothing
    is listed yet, which the client reads as "no slider".
    """
    rows = (
        await session.execute(
            select(
                Listing.deal_type,
                func.min(Listing.price_usd),
                func.max(Listing.price_usd),
            )
            .where(*visible(), Listing.price_usd.is_not(None))
            .group_by(Listing.deal_type)
        )
    ).all()

    observed = {deal_type: (low, high) for deal_type, low, high in rows}
    return [
        PriceRange(
            deal_type=deal_type,
            min_usd=observed.get(deal_type, (None, None))[0],
            max_usd=observed.get(deal_type, (None, None))[1],
        )
        for deal_type in DealType
    ]
