"""Finding the listing a new post belongs to (SPEC 7.1).

Four rules, tried in order, first strong match wins. They get progressively
fuzzier and progressively more expensive, which is also the order of how much
they can get wrong — so each one is narrowed by cheap equality checks before
any distance is computed.

The asymmetry to keep in mind: a missed match shows the user the same flat
twice, which is annoying. A wrong match merges two different flats into one
listing, which shows the user a price that is not real. The rules are tuned
toward missing rather than merging.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.core.clock import now_utc
from uyhub.core.config import Settings
from uyhub.core.logging import get_logger
from uyhub.dedup.fingerprint import from_signed_64, hamming_distance
from uyhub.models.enums import DealType, District, ListingStatus, PropertyType
from uyhub.models.listing import Listing
from uyhub.models.telegram import RawMessage

log = get_logger(__name__)

CANDIDATE_LIMIT = 200
"""Most rows a fuzzy rule will pull back before comparing distances.

Both fuzzy rules are already narrowed to one deal type, one room count and a
lookback window, so this is a safety net against a pathological source rather
than an expected cap. It is logged when hit."""


class MatchRule(StrEnum):
    """Which rule produced a match. Recorded so merges can be audited."""

    SAME_MESSAGE = "same_message"
    DEDUP_KEY = "dedup_key"
    PHONE_AND_TEXT = "phone_and_text"
    COVER_PHOTO = "cover_photo"


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """What we know about the incoming post, in the shape matching needs."""

    raw_message_id: int
    deal_type: DealType | None
    property_type: PropertyType | None
    rooms: int | None
    district: District | None
    price_usd: Decimal | None
    phone_hashes: list[str]
    dedup_key: str | None
    text_simhash: int | None
    cover_phash: int | None


@dataclass(frozen=True, slots=True)
class Match:
    listing: Listing
    rule: MatchRule


async def find_match(
    session: AsyncSession, candidate: MatchCandidate, settings: Settings
) -> Match | None:
    """The listing this post belongs to, or ``None`` to create a new one."""
    for finder in (_same_message, _by_dedup_key, _by_phone_and_text, _by_cover_photo):
        match = await finder(session, candidate, settings)
        if match is not None:
            log.info(
                "dedup.matched",
                raw_message_id=candidate.raw_message_id,
                listing_id=str(match.listing.id),
                rule=match.rule.value,
            )
            return match
    return None


async def _same_message(
    session: AsyncSession, candidate: MatchCandidate, _settings: Settings
) -> Match | None:
    """Rule 1 — this exact message already produced a listing.

    This is what makes the whole pipeline idempotent: a redelivered or
    reparsed message updates its own listing instead of creating a second one.
    """
    listing_id = (
        await session.execute(
            select(RawMessage.listing_id).where(RawMessage.id == candidate.raw_message_id)
        )
    ).scalar_one_or_none()
    if listing_id is None:
        return None

    listing = (
        await session.execute(select(Listing).where(Listing.id == listing_id))
    ).scalar_one_or_none()
    return Match(listing=listing, rule=MatchRule.SAME_MESSAGE) if listing else None


def _window(settings: Settings):  # type: ignore[no-untyped-def]
    """Only listings seen recently are candidates (SPEC 7.1 rule 2)."""
    return now_utc() - timedelta(days=settings.dedup_lookback_days)


async def _by_dedup_key(
    session: AsyncSession, candidate: MatchCandidate, settings: Settings
) -> Match | None:
    """Rule 2 — the exact key. Cheap, indexed, and the common case."""
    if candidate.dedup_key is None:
        return None

    listing = (
        await session.execute(
            select(Listing)
            .where(
                Listing.dedup_key == candidate.dedup_key,
                Listing.status == ListingStatus.ACTIVE,
                Listing.last_seen_at >= _window(settings),
            )
            .order_by(Listing.last_seen_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return Match(listing=listing, rule=MatchRule.DEDUP_KEY) if listing else None


async def _by_phone_and_text(
    session: AsyncSession, candidate: MatchCandidate, settings: Settings
) -> Match | None:
    """Rule 3 — same seller, same shape, similar text.

    The phone overlap is what keeps this narrow: a realtor's three different
    flats share a phone but differ in rooms or price, and both are checked
    before the text is even looked at.
    """
    if not candidate.phone_hashes or candidate.text_simhash is None:
        return None
    if candidate.deal_type is None or candidate.rooms is None:
        return None

    rows = await _candidates(
        session,
        select(Listing).where(
            Listing.phone_hashes.overlap(candidate.phone_hashes),
            Listing.deal_type == candidate.deal_type,
            Listing.rooms == candidate.rooms,
            Listing.status == ListingStatus.ACTIVE,
            Listing.last_seen_at >= _window(settings),
            Listing.text_simhash.is_not(None),
        ),
        rule="phone_and_text",
    )

    for listing in rows:
        if not _price_within_tolerance(candidate.price_usd, listing.price_usd, settings):
            continue
        assert listing.text_simhash is not None
        distance = hamming_distance(
            from_signed_64(candidate.text_simhash), from_signed_64(listing.text_simhash)
        )
        if distance <= settings.dedup_simhash_max_distance:
            return Match(listing=listing, rule=MatchRule.PHONE_AND_TEXT)
    return None


async def _by_cover_photo(
    session: AsyncSession, candidate: MatchCandidate, settings: Settings
) -> Match | None:
    """Rule 4 — the same photograph, whoever posted it.

    This is the one that catches a realtor republishing someone else's listing
    under their own number, which no phone-based rule can see.
    """
    if candidate.cover_phash is None:
        return None
    if candidate.deal_type is None or candidate.rooms is None:
        return None

    rows = await _candidates(
        session,
        select(Listing).where(
            Listing.deal_type == candidate.deal_type,
            Listing.rooms == candidate.rooms,
            Listing.status == ListingStatus.ACTIVE,
            Listing.last_seen_at >= _window(settings),
            Listing.cover_phash.is_not(None),
        ),
        rule="cover_photo",
    )

    for listing in rows:
        assert listing.cover_phash is not None
        distance = hamming_distance(
            from_signed_64(candidate.cover_phash), from_signed_64(listing.cover_phash)
        )
        if distance <= settings.dedup_phash_max_distance:
            return Match(listing=listing, rule=MatchRule.COVER_PHOTO)
    return None


async def _candidates(session: AsyncSession, statement, rule: str) -> list[Listing]:  # type: ignore[no-untyped-def]
    rows = list(
        (
            await session.execute(
                statement.order_by(Listing.last_seen_at.desc()).limit(CANDIDATE_LIMIT)
            )
        ).scalars()
    )
    if len(rows) == CANDIDATE_LIMIT:
        log.warning("dedup.candidate_limit_hit", rule=rule, limit=CANDIDATE_LIMIT)
    return rows


def _price_within_tolerance(
    left: Decimal | None, right: Decimal | None, settings: Settings
) -> bool:
    """Prices agree, or neither is known.

    One price present and the other missing is treated as agreement: a repost
    that dropped the price line is still the same flat, and the price itself is
    merged in separately.
    """
    if left is None or right is None:
        return True
    if left == 0 or right == 0:
        return left == right

    difference = abs(left - right) / max(left, right) * 100
    return difference <= Decimal(str(settings.dedup_price_tolerance_pct))
