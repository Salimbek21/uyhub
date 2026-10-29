"""The five scenarios SPEC's Phase 3 Definition of Done names, end to end.

Each runs the real pipeline — parse, match, merge, store photos, emit events —
against real Postgres, Redis and object storage. They are written as stories
rather than unit assertions because that is how the behaviour was specified:
"the same flat in five groups produces one listing" is the requirement.

The second scenario is the one to watch. Merging too eagerly is worse than not
merging at all: a missed duplicate is untidy, while a wrong merge shows a user
a price that belongs to a different flat.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from PIL import Image, ImageDraw
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uyhub.core.clock import now_utc
from uyhub.core.config import Settings, get_settings
from uyhub.core.phones import hash_phone
from uyhub.core.s3 import s3_client
from uyhub.core.streams import STREAM_LISTINGS
from uyhub.dedup.assemble import assemble
from uyhub.dedup.matcher import MatchRule
from uyhub.lifecycle import mark_sold_if_announced, says_sold
from uyhub.models.enums import DealType, District, ListingStatus, PropertyType
from uyhub.models.listing import Listing, ListingPhoto, ListingSource, PriceHistory
from uyhub.models.ops import SuppressedPhone
from uyhub.models.telegram import RawMessage, Source
from uyhub.parser.schema import Extraction

pytestmark = pytest.mark.integration

SELLER = "+998901234567"
OTHER_SELLER = "+998931112233"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("PHONE_HASH_KEY", "dedup-scenario-key")
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def sources(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[list[Source]]:
    """Five groups, as a flat gets cross-posted to."""
    async with session_factory() as session:
        rows = [
            Source(tg_chat_id=-100_000 - index, username=f"group_{index}") for index in range(5)
        ]
        session.add_all(rows)
        await session.commit()
        for row in rows:
            await session.refresh(row)
        yield rows


@pytest.fixture
async def photo_key(settings: Settings) -> AsyncIterator[str]:
    """One real JPEG in the raw bucket, so the media path is exercised."""
    image = Image.new("RGB", (900, 700), (60, 80, 120))
    draw = ImageDraw.Draw(image)
    draw.rectangle([120, 180, 500, 560], fill=(210, 200, 180))
    draw.ellipse([560, 120, 760, 320], fill=(245, 235, 120))
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=88)

    key = "raw/test/1/0.jpg"
    async with s3_client(settings) as client:
        await client.put_object(Bucket=settings.s3_bucket_raw, Key=key, Body=buffer.getvalue())
    yield key
    async with s3_client(settings) as client:
        await client.delete_object(Bucket=settings.s3_bucket_raw, Key=key)


def extraction(
    settings: Settings,
    *,
    phone: str = SELLER,
    rooms: int = 3,
    price: Decimal = Decimal(65_000),
    deal: DealType = DealType.SALE,
    district: District = District.CHILONZOR,
    description: str = "3 xonali kvartira Chilonzor tumani 75 m2 yevro remont holati zo'r",
) -> Extraction:
    return Extraction(
        parser_version=1,
        is_listing=True,
        deal_type=deal,
        property_type=PropertyType.APARTMENT,
        rooms=rooms,
        area_m2=Decimal(75),
        floor=5,
        floors_total=9,
        price_amount=price,
        price_currency="USD",
        price_usd=price,
        district=district,
        title=f"{rooms} xonali kvartira, Chilonzor, 75 m²",
        description=description,
        phone_hashes=[hash_phone(phone, settings)],
        quality_score=80,
        confidence=0.9,
    )


async def store_message(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    *,
    tg_message_id: int,
    text: str = "post",
    photo_key: str | None = None,
) -> tuple[int, list[dict[str, object]]]:
    media: list[dict[str, object]] = (
        [{"kind": "photo", "index": 0, "s3_key": photo_key}] if photo_key else []
    )
    async with session_factory() as session:
        row = RawMessage(
            source_id=source.id,
            tg_message_id=tg_message_id,
            posted_at=now_utc(),
            text=text,
            media=media,
        )
        session.add(row)
        await session.commit()
        return row.id, media


async def events(redis: Redis) -> list[dict[str, str]]:
    entries = await redis.xrange(STREAM_LISTINGS)
    return [fields for _entry_id, fields in entries]


async def count_listings(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return len(list((await session.execute(select(Listing.id))).scalars()))


# ---------------------------------------------------------------------------
# Scenario 1 — the same flat posted to five groups
# ---------------------------------------------------------------------------


async def test_the_same_flat_in_five_groups_is_one_listing(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    for index, source in enumerate(sources):
        raw_id, media = await store_message(session_factory, source, tg_message_id=100 + index)
        async with session_factory() as session:
            await assemble(
                session,
                redis_client,
                raw_message_id=raw_id,
                source_id=source.id,
                tg_link=f"https://t.me/group_{index}/{100 + index}",
                extraction=extraction(settings),
                media=media,
                settings=settings,
            )
            await session.commit()

    assert await count_listings(session_factory) == 1

    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
        attributions = list(
            (
                await session.execute(
                    select(ListingSource).where(ListingSource.listing_id == listing.id)
                )
            ).scalars()
        )

    assert len(attributions) == 5, "every group it appeared in must be credited"
    assert {a.source_id for a in attributions} == {s.id for s in sources}

    published = await events(redis_client)
    assert published[0]["event"] == "created"
    assert [entry["event"] for entry in published[1:]] == ["updated"] * 4


# ---------------------------------------------------------------------------
# Scenario 2 — one realtor, three different flats
# ---------------------------------------------------------------------------


async def test_one_realtor_with_three_flats_stays_three_listings(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    """The negative case SPEC 7.1 calls out, and the one that matters most.

    Same phone number throughout. Only the room count and price differ — which
    is exactly what a realtor's portfolio looks like.
    """
    flats = [
        extraction(settings, rooms=1, price=Decimal(35_000), description="1 xonali studiya"),
        extraction(settings, rooms=2, price=Decimal(48_000), description="2 xonali kvartira"),
        extraction(settings, rooms=4, price=Decimal(95_000), description="4 xonali katta uy"),
    ]

    for index, flat in enumerate(flats):
        raw_id, media = await store_message(session_factory, sources[0], tg_message_id=200 + index)
        async with session_factory() as session:
            await assemble(
                session,
                redis_client,
                raw_message_id=raw_id,
                source_id=sources[0].id,
                tg_link=None,
                extraction=flat,
                media=media,
                settings=settings,
            )
            await session.commit()

    assert await count_listings(session_factory) == 3

    async with session_factory() as session:
        rooms = sorted(
            (await session.execute(select(Listing.rooms))).scalars()  # type: ignore[arg-type]
        )
    assert rooms == [1, 2, 4]


async def test_the_same_seller_and_rooms_but_a_far_price_does_not_merge(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    """Two three-room flats from one realtor, priced 40% apart."""
    for index, price in enumerate((Decimal(65_000), Decimal(95_000))):
        raw_id, media = await store_message(session_factory, sources[0], tg_message_id=210 + index)
        async with session_factory() as session:
            await assemble(
                session,
                redis_client,
                raw_message_id=raw_id,
                source_id=sources[0].id,
                tg_link=None,
                extraction=extraction(
                    settings, price=price, description=f"3 xonali kvartira variant {index}"
                ),
                media=media,
                settings=settings,
            )
            await session.commit()

    assert await count_listings(session_factory) == 2


# ---------------------------------------------------------------------------
# Scenario 3 — a repost with a lower price
# ---------------------------------------------------------------------------


async def test_a_price_drop_updates_the_listing_and_records_history(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    first_id, media = await store_message(session_factory, sources[0], tg_message_id=300)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=first_id,
            source_id=sources[0].id,
            tg_link=None,
            extraction=extraction(settings, price=Decimal(65_000)),
            media=media,
            settings=settings,
        )
        await session.commit()

    async with session_factory() as session:
        before = (await session.execute(select(Listing))).scalar_one()
        version_before = before.version

    # The same flat reposted elsewhere, cheaper. Within the dedup key's
    # rounding this is still the same property.
    second_id, media = await store_message(session_factory, sources[1], tg_message_id=301)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=second_id,
            source_id=sources[1].id,
            tg_link=None,
            extraction=extraction(settings, price=Decimal(64_500)),
            media=media,
            settings=settings,
        )
        await session.commit()

    assert await count_listings(session_factory) == 1

    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
        history = list(
            (
                await session.execute(
                    select(PriceHistory)
                    .where(PriceHistory.listing_id == listing.id)
                    .order_by(PriceHistory.observed_at)
                )
            ).scalars()
        )

    assert listing.price_usd == Decimal("64500.00")
    assert listing.version > version_before
    assert [row.price_usd for row in history] == [Decimal("64500.00")]

    published = await events(redis_client)
    assert published[-1]["event"] == "updated"


# ---------------------------------------------------------------------------
# Scenario 4 — an edit announcing the sale
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["SOTILDI", "sotildi, rahmat", "ПРОДАНО", "квартира сдана", "Band qilindi"],
)
def test_sold_announcements_are_recognised(text: str) -> None:
    assert says_sold(text)


@pytest.mark.parametrize("text", ["3 xonali kvartira sotiladi", "продается квартира", "", None])
def test_an_ordinary_listing_is_not_sold(text: str | None) -> None:
    assert not says_sold(text)


async def test_an_edit_saying_sold_retires_the_listing(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    raw_id, media = await store_message(session_factory, sources[0], tg_message_id=400)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=raw_id,
            source_id=sources[0].id,
            tg_link=None,
            extraction=extraction(settings),
            media=media,
            settings=settings,
        )
        await session.commit()

    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
        changed = await mark_sold_if_announced(
            session, redis_client, listing, "SOTILDI! Rahmat hammaga"
        )
        await session.commit()

    assert changed
    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
    assert listing.status is ListingStatus.SOLD
    assert listing.status_changed_at is not None

    published = await events(redis_client)
    assert published[-1]["event"] == "status_changed"
    assert published[-1]["status"] == "sold"


# ---------------------------------------------------------------------------
# Scenario 5 — deleted and reposted
# ---------------------------------------------------------------------------


async def test_a_deletion_does_not_retire_a_fresh_listing(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    """Deleting and reposting is how these groups bump a listing (SPEC 8)."""
    from uyhub.lifecycle import expire_fully_deleted

    raw_id, media = await store_message(session_factory, sources[0], tg_message_id=500)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=raw_id,
            source_id=sources[0].id,
            tg_link=None,
            extraction=extraction(settings),
            media=media,
            settings=settings,
        )
        await session.commit()

    async with session_factory() as session:
        row = (
            await session.execute(select(RawMessage).where(RawMessage.id == raw_id))
        ).scalar_one()
        row.deleted_at = now_utc()
        await session.commit()

    async with session_factory() as session:
        retired = await expire_fully_deleted(session, redis_client)
        await session.commit()

    assert retired == 0, "a listing deleted today is probably about to be reposted"


async def test_an_old_listing_whose_posts_are_all_gone_expires(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    from uyhub.lifecycle import DELETED_GRACE_DAYS, expire_fully_deleted

    raw_id, media = await store_message(session_factory, sources[0], tg_message_id=510)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=raw_id,
            source_id=sources[0].id,
            tg_link=None,
            extraction=extraction(settings),
            media=media,
            settings=settings,
        )
        await session.commit()

    old = now_utc() - timedelta(days=DELETED_GRACE_DAYS + 1)
    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
        listing.first_seen_at = old
        message = (
            await session.execute(select(RawMessage).where(RawMessage.id == raw_id))
        ).scalar_one()
        message.deleted_at = now_utc()
        await session.commit()

    async with session_factory() as session:
        retired = await expire_fully_deleted(session, redis_client)
        await session.commit()

    assert retired == 1
    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
    assert listing.status is ListingStatus.EXPIRED


async def test_a_repost_revives_an_expired_listing(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    from uyhub.lifecycle import reactivate

    raw_id, media = await store_message(session_factory, sources[0], tg_message_id=520)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=raw_id,
            source_id=sources[0].id,
            tg_link=None,
            extraction=extraction(settings),
            media=media,
            settings=settings,
        )
        await session.commit()

    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
        listing.status = ListingStatus.EXPIRED
        await session.commit()

    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
        revived = await reactivate(session, redis_client, listing)
        await session.commit()

    assert revived
    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
    assert listing.status is ListingStatus.ACTIVE


# ---------------------------------------------------------------------------
# Media, idempotency, suppression
# ---------------------------------------------------------------------------


async def test_photos_become_publicly_readable_webp(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
    photo_key: str,
) -> None:
    """The step that makes a collected original into something a browser shows."""
    raw_id, media = await store_message(
        session_factory, sources[0], tg_message_id=600, photo_key=photo_key
    )
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=raw_id,
            source_id=sources[0].id,
            tg_link=None,
            extraction=extraction(settings),
            media=media,
            settings=settings,
        )
        await session.commit()

    async with session_factory() as session:
        photos = list((await session.execute(select(ListingPhoto))).scalars())
        listing = (await session.execute(select(Listing))).scalar_one()

    assert len(photos) == 1
    photo = photos[0]
    assert photo.s3_key_large and photo.s3_key_thumb
    assert photo.sha256 and photo.phash is not None
    assert listing.cover_phash == photo.phash

    async with s3_client(settings) as client:
        for key in (photo.s3_key_large, photo.s3_key_thumb):
            head = await client.head_object(Bucket=settings.s3_bucket_media, Key=key)
            assert head["ContentType"] == "image/webp"
            assert head["ContentLength"] > 0


async def test_the_same_photo_from_five_groups_is_stored_once(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
    photo_key: str,
) -> None:
    for index, source in enumerate(sources):
        raw_id, media = await store_message(
            session_factory, source, tg_message_id=610 + index, photo_key=photo_key
        )
        async with session_factory() as session:
            await assemble(
                session,
                redis_client,
                raw_message_id=raw_id,
                source_id=source.id,
                tg_link=None,
                extraction=extraction(settings),
                media=media,
                settings=settings,
            )
            await session.commit()

    async with session_factory() as session:
        photos = list((await session.execute(select(ListingPhoto))).scalars())
    assert len(photos) == 1, "deduplicated by sha256"


async def test_reprocessing_the_same_message_updates_rather_than_duplicates(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    """What makes `uyhub reparse` safe to run over the whole archive."""
    raw_id, media = await store_message(session_factory, sources[0], tg_message_id=700)

    for _ in range(3):
        async with session_factory() as session:
            result = await assemble(
                session,
                redis_client,
                raw_message_id=raw_id,
                source_id=sources[0].id,
                tg_link=None,
                extraction=extraction(settings),
                media=media,
                settings=settings,
            )
            await session.commit()

    assert await count_listings(session_factory) == 1
    assert result.rule is MatchRule.SAME_MESSAGE

    async with session_factory() as session:
        attributions = list((await session.execute(select(ListingSource))).scalars())
    assert len(attributions) == 1


async def test_a_suppressed_seller_never_gets_a_listing(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    """SPEC 13: a removal request is honoured before anything is published."""
    async with session_factory() as session:
        session.add(
            SuppressedPhone(phone_hash=hash_phone(SELLER, settings), reason="seller_request")
        )
        await session.commit()

    raw_id, media = await store_message(session_factory, sources[0], tg_message_id=800)
    async with session_factory() as session:
        result = await assemble(
            session,
            redis_client,
            raw_message_id=raw_id,
            source_id=sources[0].id,
            tg_link=None,
            extraction=extraction(settings),
            media=media,
            settings=settings,
        )
        await session.commit()

    assert result.suppressed
    assert result.listing_id is None
    assert await count_listings(session_factory) == 0


async def test_the_title_follows_the_fields_a_merge_fills_in(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    """Found on real data: listings read "3 xonali obyekt" in the feed long
    after a later sighting had established they were flats in Chilonzor.

    The title is derived, so it has to be rebuilt when its inputs are.
    """
    vague = extraction(settings).model_copy(
        update={"property_type": None, "district": None, "area_m2": None}
    )
    vague = vague.model_copy(update={"title": "3 xonali obyekt"})

    first_id, media = await store_message(session_factory, sources[0], tg_message_id=1000)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=first_id,
            source_id=sources[0].id,
            tg_link=None,
            extraction=vague,
            media=media,
            settings=settings,
        )
        await session.commit()

    async with session_factory() as session:
        assert (await session.execute(select(Listing))).scalar_one().title == "3 xonali obyekt"

    second_id, media = await store_message(session_factory, sources[1], tg_message_id=1001)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=second_id,
            source_id=sources[1].id,
            tg_link=None,
            extraction=extraction(settings),
            media=media,
            settings=settings,
        )
        await session.commit()

    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()

    assert listing.property_type is PropertyType.APARTMENT
    assert listing.district is District.CHILONZOR
    assert listing.title == "3 xonali kvartira, Chilonzor, 75 m²"


async def test_an_unnamed_property_type_is_stored_as_unknown_not_guessed(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    """The column is not nullable and used to default to ``apartment``, so a
    post that never said what it was became a flat in the filters — a guess
    stored as a fact, and the reason the title said "obyekt" while the column
    said "kvartira"."""
    vague = extraction(settings).model_copy(update={"property_type": None})

    raw_id, media = await store_message(session_factory, sources[0], tg_message_id=1100)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=raw_id,
            source_id=sources[0].id,
            tg_link=None,
            extraction=vague,
            media=media,
            settings=settings,
        )
        await session.commit()

    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()

    assert listing.property_type is PropertyType.OTHER


async def test_a_merge_never_overwrites_a_known_field_with_nothing(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sources: list[Source],
    settings: Settings,
) -> None:
    """SPEC 7.2. A terser repost must not erase what the first post told us."""
    full = extraction(settings)
    first_id, media = await store_message(session_factory, sources[0], tg_message_id=900)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=first_id,
            source_id=sources[0].id,
            tg_link=None,
            extraction=full,
            media=media,
            settings=settings,
        )
        await session.commit()

    terse = full.model_copy(update={"area_m2": None, "floor": None, "floors_total": None})
    second_id, media = await store_message(session_factory, sources[1], tg_message_id=901)
    async with session_factory() as session:
        await assemble(
            session,
            redis_client,
            raw_message_id=second_id,
            source_id=sources[1].id,
            tg_link=None,
            extraction=terse,
            media=media,
            settings=settings,
        )
        await session.commit()

    async with session_factory() as session:
        listing = (await session.execute(select(Listing))).scalar_one()

    assert listing.area_m2 == Decimal(75)
    assert (listing.floor, listing.floors_total) == (5, 9)
