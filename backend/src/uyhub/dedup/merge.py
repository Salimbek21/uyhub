"""Folding a new sighting into an existing listing (SPEC 7.2).

The governing rule is that a merge may only ever add information. A repost
that omitted the floor must not erase the floor we already knew; a repost that
mentions it for the first time should fill it in. So every field is filled only
where the listing is currently null.

The price is the exception, and deliberately so: a changed price is the point
of watching a listing at all, so it overwrites, records history and bumps the
version.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.core.clock import now_utc
from uyhub.core.logging import get_logger
from uyhub.models.listing import Listing, ListingPhoto, ListingSource, PriceHistory
from uyhub.parser.schema import Extraction

log = get_logger(__name__)

FILLABLE_FIELDS = (
    "deal_type",
    "property_type",
    "rooms",
    "area_m2",
    "land_sotix",
    "floor",
    "floors_total",
    "district",
    "landmark",
    "address_text",
    "price_period",
)
"""Fields a later sighting may fill in, but never overwrite."""

UNKNOWN_ENUM_FIELDS = ("building_type", "renovation")
"""These are not null when unknown — they hold an explicit `unknown` member, so
"is it missing" is a different question for them."""


@dataclass(frozen=True, slots=True)
class MergeOutcome:
    """What a merge actually changed, so the caller knows which event to emit."""

    changed: bool
    price_changed: bool
    fields_filled: list[str]
    photos_added: int


async def add_source(
    session: AsyncSession,
    listing: Listing,
    *,
    raw_message_id: int,
    source_id: int,
    tg_link: str | None,
) -> bool:
    """Record where this listing was seen. Returns False if already recorded."""
    existing = (
        await session.execute(
            select(ListingSource.id).where(
                ListingSource.listing_id == listing.id,
                ListingSource.raw_message_id == raw_message_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    session.add(
        ListingSource(
            listing_id=listing.id,
            raw_message_id=raw_message_id,
            source_id=source_id,
            tg_link=tg_link,
        )
    )
    return True


def merge_fields(listing: Listing, extraction: Extraction) -> list[str]:
    """Fill the listing's empty fields from a new sighting. Returns what changed."""
    filled: list[str] = []

    for name in FILLABLE_FIELDS:
        if getattr(listing, name) is not None:
            continue
        incoming = getattr(extraction, name)
        if incoming is not None:
            setattr(listing, name, incoming)
            filled.append(name)

    for name in UNKNOWN_ENUM_FIELDS:
        current = getattr(listing, name)
        incoming = getattr(extraction, name)
        if current.value == "unknown" and incoming.value != "unknown":
            setattr(listing, name, incoming)
            filled.append(name)

    # A longer description is a more complete one. SPEC 7.2 asks for "the most
    # complete text" without defining it, and length is the only measure that
    # does not require trusting one source over another (DECISIONS 3.4).
    if extraction.description and len(extraction.description) > len(listing.description or ""):
        listing.description = extraction.description
        filled.append("description")

    # Phone hashes accumulate: a realtor may add a second number later, and
    # dedup matches on overlap, so more of them only makes matching stronger.
    new_hashes = [h for h in extraction.phone_hashes if h not in listing.phone_hashes]
    if new_hashes:
        listing.phone_hashes = [*listing.phone_hashes, *new_hashes]
        filled.append("phone_hashes")

    if extraction.negotiable and not listing.negotiable:
        listing.negotiable = True
        filled.append("negotiable")

    if extraction.quality_score > listing.quality_score:
        listing.quality_score = extraction.quality_score
        filled.append("quality_score")

    return filled


async def apply_price(session: AsyncSession, listing: Listing, extraction: Extraction) -> bool:
    """Record a price change. Returns True when the price actually moved.

    Unlike every other field the price overwrites, because a price drop is the
    thing a watching user most wants to be told about. ``price_usd`` itself is
    frozen at first sight for a given posted price — it is only recomputed when
    the seller posts a different number, never when the exchange rate moves
    (DECISIONS 3.1).
    """
    incoming = extraction.price_amount
    if incoming is None:
        return False
    if listing.price_amount == incoming and listing.price_currency == extraction.price_currency:
        return False

    listing.price_amount = incoming
    listing.price_currency = extraction.price_currency
    listing.price_usd = extraction.price_usd

    session.add(
        PriceHistory(
            listing_id=listing.id,
            price_usd=extraction.price_usd,
            price_amount=incoming,
            price_currency=extraction.price_currency,
        )
    )
    return True


async def photo_exists(session: AsyncSession, listing: Listing, sha256: str) -> bool:
    """Whether this exact file is already attached to the listing."""
    found = (
        await session.execute(
            select(ListingPhoto.id).where(
                ListingPhoto.listing_id == listing.id, ListingPhoto.sha256 == sha256
            )
        )
    ).scalar_one_or_none()
    return found is not None


async def photo_count(session: AsyncSession, listing: Listing) -> int:
    rows = (
        await session.execute(select(ListingPhoto.id).where(ListingPhoto.listing_id == listing.id))
    ).scalars()
    return len(list(rows))


async def next_position(session: AsyncSession, listing: Listing) -> int:
    return await photo_count(session, listing)


def touch(listing: Listing, *, changed: bool) -> None:
    """Mark the listing as seen, and bump its version if anything changed."""
    listing.last_seen_at = now_utc()
    if changed:
        listing.version += 1


def price_difference_pct(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    """How far apart two prices are, for logging a drop."""
    if left is None or right is None or left == 0:
        return None
    return (right - left) / left * 100
