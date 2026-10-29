"""Turning a parsed message into a listing (SPEC 7).

This is where the pipeline stops being about messages and starts being about
properties. One post either joins a listing that already exists or becomes a
new one, its photos become something a browser can render, and the result is
announced on ``stream:listings``.

Two things here are load-bearing and easy to miss:

*Idempotency* comes from match rule 1. ``raw_messages.listing_id`` records
which listing a message produced, so reprocessing the same message updates
that listing rather than creating a second one. Reparsing after a parser change
is therefore safe to run over the whole archive.

*Concurrency* comes from a transaction-scoped advisory lock on the seller's
phone hash. Two parser replicas handling two reposts of the same flat would
otherwise both find no match and both create a listing — the gap in SPEC's
per-message idempotency that OPEN_QUESTIONS C5 describes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.core.clock import now_utc
from uyhub.core.config import Settings
from uyhub.core.logging import get_logger
from uyhub.core.streams import STREAM_LISTINGS, publish
from uyhub.dedup import merge as merge_ops
from uyhub.dedup.fingerprint import dedup_key, simhash, to_signed_64
from uyhub.dedup.matcher import MatchCandidate, MatchRule, find_match
from uyhub.media.process import (
    MAX_PHOTOS_PER_LISTING,
    ProcessedImage,
    fetch_and_process,
    store_derivatives,
)
from uyhub.models.enums import ListingStatus, PropertyType
from uyhub.models.listing import Listing, ListingPhoto
from uyhub.models.ops import SuppressedPhone
from uyhub.models.telegram import RawMessage
from uyhub.parser.schema import Extraction

log = get_logger(__name__)

EVENT_CREATED = "created"
EVENT_UPDATED = "updated"


@dataclass(frozen=True, slots=True)
class AssembleResult:
    """What became of one parsed message."""

    listing_id: str | None
    event: str | None
    rule: MatchRule | None = None
    suppressed: bool = False

    @property
    def created(self) -> bool:
        return self.event == EVENT_CREATED


async def assemble(
    session: AsyncSession,
    redis: Redis,
    *,
    raw_message_id: int,
    source_id: int,
    tg_link: str | None,
    extraction: Extraction,
    media: list[dict[str, Any]],
    settings: Settings,
) -> AssembleResult:
    """Fold one parsed message into the listing table."""
    if not extraction.is_listing:
        return AssembleResult(listing_id=None, event=None)

    if await _is_suppressed(session, extraction.phone_hashes):
        # SPEC 8: a listing whose seller asked to be removed is never created.
        log.info("dedup.suppressed", raw_message_id=raw_message_id)
        return AssembleResult(listing_id=None, event=None, suppressed=True)

    await _lock_seller(session, extraction.phone_hashes)

    cover = await _cover_image(media, settings)
    candidate = _candidate(raw_message_id, extraction, cover)

    match = await find_match(session, candidate, settings)
    if match is None:
        listing = await _create(session, extraction, candidate)
        event, rule = EVENT_CREATED, None
    else:
        listing = match.listing
        event, rule = EVENT_UPDATED, match.rule

    changed = await _apply(
        session,
        listing,
        extraction=extraction,
        candidate=candidate,
        raw_message_id=raw_message_id,
        source_id=source_id,
        tg_link=tg_link,
        cover=cover,
        media=media,
        settings=settings,
    )

    merge_ops.touch(listing, changed=changed or event == EVENT_CREATED)
    await session.execute(
        update(RawMessage).where(RawMessage.id == raw_message_id).values(listing_id=listing.id)
    )
    await session.flush()

    if event == EVENT_CREATED or changed:
        await publish(
            redis,
            STREAM_LISTINGS,
            {"listing_id": str(listing.id), "event": event, "version": listing.version},
        )
    return AssembleResult(listing_id=str(listing.id), event=event, rule=rule)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


async def _is_suppressed(session: AsyncSession, phone_hashes: list[str]) -> bool:
    if not phone_hashes:
        return False
    found = (
        await session.execute(
            select(SuppressedPhone.id).where(SuppressedPhone.phone_hash.in_(phone_hashes))
        )
    ).scalar_one_or_none()
    return found is not None


async def _lock_seller(session: AsyncSession, phone_hashes: list[str]) -> None:
    """Serialise assembly per seller, for the duration of this transaction.

    Keyed on the first phone hash so two workers handling the same flat queue
    behind each other, while work on unrelated listings runs in parallel. A
    post with no phone takes no lock: there is nothing to collide on, and rule
    2 already declines to match it.
    """
    if not phone_hashes:
        return
    key = to_signed_64(int(sorted(phone_hashes)[0][:16], 16))
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def _cover_image(media: list[dict[str, Any]], settings: Settings) -> ProcessedImage | None:
    """Process the first photo, because dedup rule 4 needs its hash."""
    for item in media:
        if item.get("kind") == "photo" and item.get("s3_key"):
            return await fetch_and_process(str(item["s3_key"]), settings=settings)
    return None


def _candidate(
    raw_message_id: int, extraction: Extraction, cover: ProcessedImage | None
) -> MatchCandidate:
    return MatchCandidate(
        raw_message_id=raw_message_id,
        deal_type=extraction.deal_type,
        property_type=extraction.property_type,
        rooms=extraction.rooms,
        district=extraction.district,
        price_usd=extraction.price_usd,
        phone_hashes=extraction.phone_hashes,
        dedup_key=dedup_key(
            phone_hashes=extraction.phone_hashes,
            deal_type=extraction.deal_type,
            property_type=extraction.property_type,
            rooms=extraction.rooms,
            district=extraction.district,
            price_usd=extraction.price_usd,
        ),
        text_simhash=to_signed_64(simhash(extraction.description or extraction.title)),
        cover_phash=cover.phash if cover else None,
    )


async def _create(
    session: AsyncSession, extraction: Extraction, candidate: MatchCandidate
) -> Listing:
    listing = Listing(
        deal_type=extraction.deal_type,
        property_type=extraction.property_type or PropertyType.OTHER,
        rooms=extraction.rooms,
        area_m2=extraction.area_m2,
        land_sotix=extraction.land_sotix,
        floor=extraction.floor,
        floors_total=extraction.floors_total,
        building_type=extraction.building_type,
        renovation=extraction.renovation,
        price_amount=extraction.price_amount,
        price_currency=extraction.price_currency,
        price_usd=extraction.price_usd,
        price_period=extraction.price_period,
        negotiable=extraction.negotiable,
        district=extraction.district,
        landmark=extraction.landmark,
        address_text=extraction.address_text,
        title=extraction.title,
        description=extraction.description,
        phone_hashes=list(extraction.phone_hashes),
        status=ListingStatus.ACTIVE,
        quality_score=extraction.quality_score,
        confidence=extraction.confidence,
        needs_review=extraction.needs_review,
        dedup_key=candidate.dedup_key,
        text_simhash=candidate.text_simhash,
        cover_phash=candidate.cover_phash,
    )
    session.add(listing)
    await session.flush()
    log.info("dedup.listing_created", listing_id=str(listing.id), title=listing.title)
    return listing


async def _apply(
    session: AsyncSession,
    listing: Listing,
    *,
    extraction: Extraction,
    candidate: MatchCandidate,
    raw_message_id: int,
    source_id: int,
    tg_link: str | None,
    cover: ProcessedImage | None,
    media: list[dict[str, Any]],
    settings: Settings,
) -> bool:
    """Merge this sighting in. Returns whether anything material changed."""
    added_source = await merge_ops.add_source(
        session, listing, raw_message_id=raw_message_id, source_id=source_id, tg_link=tg_link
    )
    filled = merge_ops.merge_fields(listing, extraction)
    price_moved = await merge_ops.apply_price(session, listing, extraction)
    photos_added = await _attach_photos(session, listing, cover, media, settings)

    # A fingerprint only appears once the data behind it does.
    if listing.dedup_key is None and candidate.dedup_key is not None:
        listing.dedup_key = candidate.dedup_key
    if listing.cover_phash is None and candidate.cover_phash is not None:
        listing.cover_phash = candidate.cover_phash

    if price_moved:
        log.info(
            "dedup.price_changed",
            listing_id=str(listing.id),
            price_usd=str(listing.price_usd),
        )

    return bool(filled or price_moved or photos_added or added_source)


async def _attach_photos(
    session: AsyncSession,
    listing: Listing,
    cover: ProcessedImage | None,
    media: list[dict[str, Any]],
    settings: Settings,
) -> int:
    """Store and attach any photos this listing does not already have.

    Deduplicated by sha256, so the same file arriving from five groups is
    stored once. Capped at :data:`MAX_PHOTOS_PER_LISTING`.
    """
    listing_id = str(listing.id)
    position = await merge_ops.next_position(session, listing)
    added = 0

    photos = [item for item in media if item.get("kind") == "photo" and item.get("s3_key")]
    for index, item in enumerate(photos):
        if position >= MAX_PHOTOS_PER_LISTING:
            break

        # The first photo was already decoded to get the cover hash.
        processed = cover if index == 0 and cover is not None else None
        if processed is None:
            processed = await fetch_and_process(str(item["s3_key"]), settings=settings)
        if processed is None:
            continue

        if await merge_ops.photo_exists(session, listing, processed.sha256):
            continue

        stored = await store_derivatives(
            processed, listing_id=listing_id, position=position, settings=settings
        )
        session.add(
            ListingPhoto(
                listing_id=listing.id,
                position=position,
                s3_key_original=str(item["s3_key"]),
                s3_key_large=stored.s3_key_large,
                s3_key_thumb=stored.s3_key_thumb,
                width=stored.width,
                height=stored.height,
                phash=stored.phash,
                sha256=stored.sha256,
            )
        )
        await session.flush()
        position += 1
        added += 1

    return added


def seen_just_now(listing: Listing) -> bool:
    """Whether this listing was touched in the current pass. Used by tests."""
    return listing.last_seen_at >= now_utc().replace(microsecond=0)
