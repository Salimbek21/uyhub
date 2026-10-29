"""What happens to a listing after it is created (SPEC section 8).

Four states and the transitions between them. The one that needs explaining is
why a deleted post does not immediately retire a listing: people in these
groups routinely delete and repost within minutes to push their listing back to
the top. Retiring on the first deletion would churn the feed and lose
inventory, so a listing only expires once *every* source has dropped it and it
is more than three days old.

Every transition bumps ``version`` and emits ``status_changed``, so the bot and
the channel poster can react without polling.
"""

from __future__ import annotations

import re
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.core.clock import now_utc
from uyhub.core.config import Settings
from uyhub.core.logging import get_logger
from uyhub.core.streams import STREAM_LISTINGS, publish
from uyhub.models.enums import DealType, ListingStatus
from uyhub.models.listing import Listing, ListingSource
from uyhub.models.ops import SuppressedPhone
from uyhub.models.telegram import RawMessage, Source

log = get_logger(__name__)

EVENT_STATUS_CHANGED = "status_changed"

DELETED_GRACE_DAYS = 3
"""How old a listing must be before a deletion is believed (SPEC 8)."""

TRUST_MIN_MESSAGES = 20
"""Below this a source has no history worth scoring."""

TRUST_FLOOR = 0.3
"""A source is never scored to zero: even a noisy group posts real listings,
and the score multiplies into quality, which gates channel posting."""

_SOLD_RE = re.compile(
    r"\b(?:sotildi|sotilgan|sotib\s*yuborildi|ijaraga\s*berildi|berildi|band)\b"
    r"|\b(?:сотилди|сотилган)\b"
    r"|\b(?:продано|продана|продан|сдано|сдана|сдан|занято|снято)\b",
    re.IGNORECASE,
)


def says_sold(text: str | None) -> bool:
    """Whether an edit announces the property is gone (SPEC 8)."""
    return bool(text) and _SOLD_RE.search(text or "") is not None


async def set_status(
    session: AsyncSession,
    redis: Redis,
    listing: Listing,
    status: ListingStatus,
    *,
    reason: str,
) -> bool:
    """Move a listing to a new state. Returns False if it was already there.

    ``removed`` is terminal: SPEC 8 says a listing taken down at the seller's
    request never comes back automatically, so nothing here moves it out.
    """
    if listing.status == status:
        return False
    if listing.status is ListingStatus.REMOVED:
        return False

    previous = listing.status
    listing.status = status
    listing.status_changed_at = now_utc()
    listing.version += 1
    await session.flush()

    await publish(
        redis,
        STREAM_LISTINGS,
        {
            "listing_id": str(listing.id),
            "event": EVENT_STATUS_CHANGED,
            "version": listing.version,
            "status": status.value,
        },
    )
    log.info(
        "lifecycle.status_changed",
        listing_id=str(listing.id),
        was=previous.value,
        now=status.value,
        reason=reason,
    )
    return True


async def mark_sold_if_announced(
    session: AsyncSession, redis: Redis, listing: Listing, text: str | None
) -> bool:
    """React to an edit that says the property is gone."""
    if not says_sold(text):
        return False
    return await set_status(session, redis, listing, ListingStatus.SOLD, reason="announced")


async def reactivate(session: AsyncSession, redis: Redis, listing: Listing) -> bool:
    """A repost brings an expired listing back (SPEC 8)."""
    if listing.status is not ListingStatus.EXPIRED:
        return False
    return await set_status(session, redis, listing, ListingStatus.ACTIVE, reason="reposted")


async def expire_stale(session: AsyncSession, redis: Redis, settings: Settings) -> int:
    """Retire listings nobody has posted about for a while. Returns the count.

    Sale and rent have different lifetimes because the markets move at
    different speeds — a rental that is still up after two weeks has almost
    certainly gone.
    """
    now = now_utc()
    cutoffs = {
        DealType.SALE: now - timedelta(days=settings.listing_ttl_days_sale),
        DealType.RENT: now - timedelta(days=settings.listing_ttl_days_rent),
    }

    expired = 0
    for deal_type, cutoff in cutoffs.items():
        listings = (
            await session.execute(
                select(Listing).where(
                    Listing.status == ListingStatus.ACTIVE,
                    Listing.deal_type == deal_type,
                    Listing.last_seen_at < cutoff,
                )
            )
        ).scalars()
        for listing in listings:
            if await set_status(session, redis, listing, ListingStatus.EXPIRED, reason="stale"):
                expired += 1

    if expired:
        log.info("lifecycle.expired_stale", count=expired)
    return expired


async def expire_fully_deleted(session: AsyncSession, redis: Redis) -> int:
    """Retire listings whose every source post has been deleted (SPEC 8).

    Only once the listing is older than the grace period: deleting and
    reposting is how these groups bump a listing, and acting on the first
    deletion would retire half the feed every evening.
    """
    cutoff = now_utc() - timedelta(days=DELETED_GRACE_DAYS)

    # A listing qualifies when it has sources and none of them is still alive.
    alive = (
        select(ListingSource.listing_id)
        .join(RawMessage, RawMessage.id == ListingSource.raw_message_id)
        .where(RawMessage.deleted_at.is_(None))
    )
    candidates = (
        await session.execute(
            select(Listing)
            .join(ListingSource, ListingSource.listing_id == Listing.id)
            .where(
                Listing.status == ListingStatus.ACTIVE,
                Listing.first_seen_at < cutoff,
                Listing.id.not_in(alive),
            )
            .group_by(Listing.id)
            .having(func.count(ListingSource.id) > 0)
        )
    ).scalars()

    expired = 0
    for listing in candidates:
        if await set_status(
            session, redis, listing, ListingStatus.EXPIRED, reason="sources_deleted"
        ):
            expired += 1

    if expired:
        log.info("lifecycle.expired_deleted", count=expired)
    return expired


async def remove_suppressed(session: AsyncSession, redis: Redis) -> int:
    """Take down listings whose seller asked to be removed (SPEC 13).

    Run as a job as well as checked at creation, because a suppression added
    today must retire listings collected yesterday.
    """
    hashes = list((await session.execute(select(SuppressedPhone.phone_hash))).scalars())
    if not hashes:
        return 0

    listings = (
        await session.execute(
            select(Listing).where(
                Listing.status != ListingStatus.REMOVED,
                Listing.phone_hashes.overlap(hashes),
            )
        )
    ).scalars()

    removed = 0
    for listing in listings:
        if await set_status(session, redis, listing, ListingStatus.REMOVED, reason="suppressed"):
            removed += 1

    if removed:
        log.info("lifecycle.removed_suppressed", count=removed)
    return removed


async def recompute_trust_scores(session: AsyncSession) -> int:
    """Score each source by how much of what it posts turns out to be a listing.

    SPEC 3 stores ``trust_score`` and feeds it into the quality score, but
    nothing ever computed it (OPEN_QUESTIONS B4). The share of a source's
    messages that became listings is the one signal already available, and it
    does separate a property channel from a chat group.

    Floored at 0.3 so a new source with no history is not buried, and only
    applied once there is enough history to mean anything.
    """
    rows = (
        await session.execute(
            select(
                RawMessage.source_id,
                func.count(RawMessage.id).label("total"),
                func.count(RawMessage.listing_id).label("became_listings"),
            )
            .group_by(RawMessage.source_id)
            .having(func.count(RawMessage.id) >= TRUST_MIN_MESSAGES)
        )
    ).all()

    updated = 0
    for source_id, total, became_listings in rows:
        score = max(TRUST_FLOOR, min(1.0, became_listings / total))
        await session.execute(
            update(Source).where(Source.id == source_id).values(trust_score=score)
        )
        updated += 1

    if updated:
        log.info("lifecycle.trust_scores_updated", sources=updated)
    return updated
