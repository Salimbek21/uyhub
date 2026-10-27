"""Ingesting received messages (SPEC 4.3, 4.4, 4.5).

Everything here runs against real Postgres, real Redis and a fake Telegram. The
DoD for Phase 1 names albums, edits, deletions and gap recovery specifically, so
each has its own test, as do the idempotency properties they depend on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fakes import FakeGateway, FakePhotoStore, make_message
from uyhub.collector.backfill import backfill_source
from uyhub.collector.ingest import REASON_BACKFILL, REASON_EDITED, MessageIngestor
from uyhub.collector.media import raw_key
from uyhub.collector.types import DeletedMessages
from uyhub.core.clock import now_utc
from uyhub.core.streams import STREAM_RAW
from uyhub.models.enums import RawMessageStatus, SourceStatus
from uyhub.models.telegram import RawMessage, Source

pytestmark = pytest.mark.integration

CHAT_ID = -1001234567890


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Source]:
    """An active source the collector is allowed to read."""
    async with session_factory() as session:
        row = Source(
            tg_chat_id=CHAT_ID,
            username="uyhub_test",
            title="Test group",
            status=SourceStatus.ACTIVE,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        yield row


@pytest.fixture
def photo_store() -> FakePhotoStore:
    return FakePhotoStore()


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def ingestor(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    gateway: FakeGateway,
    photo_store: FakePhotoStore,
) -> MessageIngestor:
    return MessageIngestor(
        session_factory=session_factory,
        redis=redis_client,
        gateway=gateway,
        photo_store=photo_store,
    )


async def _stream_entries(redis: Redis) -> list[dict[str, str]]:
    entries = await redis.xrange(STREAM_RAW)
    return [fields for _entry_id, fields in entries]


async def _row(session_factory: async_sessionmaker[AsyncSession], raw_id: int) -> RawMessage:
    async with session_factory() as session:
        return (
            await session.execute(select(RawMessage).where(RawMessage.id == raw_id))
        ).scalar_one()


# ---------------------------------------------------------------------------
# New messages
# ---------------------------------------------------------------------------


async def test_new_message_is_stored_and_queued(
    ingestor: MessageIngestor,
    source: Source,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
) -> None:
    message = make_message(chat_id=CHAT_ID, message_id=101, text="2 xonali kvartira, 55 000$")

    raw_id = await ingestor.ingest(source.id, message)

    assert raw_id is not None
    stored = await _row(session_factory, raw_id)
    assert stored.tg_message_id == 101
    assert stored.text == "2 xonali kvartira, 55 000$"
    assert stored.status == RawMessageStatus.PENDING
    assert stored.deleted_at is None

    entries = await _stream_entries(redis_client)
    assert entries == [{"raw_message_id": str(raw_id), "reason": "new"}]


async def test_source_high_water_mark_advances(
    ingestor: MessageIngestor,
    source: Source,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Gap recovery reads ``last_message_id``, so ingestion must maintain it."""
    await ingestor.ingest(source.id, make_message(chat_id=CHAT_ID, message_id=10))
    await ingestor.ingest(source.id, make_message(chat_id=CHAT_ID, message_id=20))

    async with session_factory() as session:
        refreshed = (
            await session.execute(select(Source).where(Source.id == source.id))
        ).scalar_one()
        assert refreshed.last_message_id == 20
        assert refreshed.messages_total == 2


async def test_high_water_mark_never_moves_backwards(
    ingestor: MessageIngestor,
    source: Source,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A backfill arriving after live traffic must not rewind the mark."""
    await ingestor.ingest(source.id, make_message(chat_id=CHAT_ID, message_id=50))
    await ingestor.ingest(
        source.id, make_message(chat_id=CHAT_ID, message_id=20), reason=REASON_BACKFILL
    )

    async with session_factory() as session:
        refreshed = (
            await session.execute(select(Source).where(Source.id == source.id))
        ).scalar_one()
        assert refreshed.last_message_id == 50


async def test_empty_and_own_messages_are_ignored(
    ingestor: MessageIngestor, source: Source, redis_client: Redis
) -> None:
    assert await ingestor.ingest(source.id, make_message(chat_id=CHAT_ID, text="   ")) is None
    assert (
        await ingestor.ingest(
            source.id, make_message(chat_id=CHAT_ID, message_id=2, from_self=True)
        )
        is None
    )
    assert await _stream_entries(redis_client) == []


# ---------------------------------------------------------------------------
# Albums and media (SPEC 4.5)
# ---------------------------------------------------------------------------


async def test_album_becomes_one_row_with_every_photo(
    ingestor: MessageIngestor,
    source: Source,
    session_factory: async_sessionmaker[AsyncSession],
    photo_store: FakePhotoStore,
) -> None:
    album = make_message(chat_id=CHAT_ID, message_id=200, photos=3, grouped_id=777)

    raw_id = await ingestor.ingest(source.id, album)

    assert raw_id is not None
    stored = await _row(session_factory, raw_id)
    assert stored.grouped_id == 777
    assert len(stored.media) == 3
    assert [item["s3_key"] for item in stored.media] == [
        raw_key(source.id, 200, 0),
        raw_key(source.id, 200, 1),
        raw_key(source.id, 200, 2),
    ]
    assert set(photo_store.objects) == {item["s3_key"] for item in stored.media}


async def test_photos_beyond_the_limit_are_recorded_but_not_downloaded(
    ingestor: MessageIngestor,
    source: Source,
    session_factory: async_sessionmaker[AsyncSession],
    photo_store: FakePhotoStore,
) -> None:
    """SPEC 4.5 caps downloads at ten per post; the rest still show up in media."""
    raw_id = await ingestor.ingest(
        source.id, make_message(chat_id=CHAT_ID, message_id=300, photos=14, grouped_id=1)
    )

    assert raw_id is not None
    stored = await _row(session_factory, raw_id)
    assert len(stored.media) == 14
    assert len(photo_store.objects) == 10
    assert [item.get("skipped") for item in stored.media[10:]] == ["limit"] * 4


async def test_an_undownloadable_photo_is_still_recorded(
    ingestor: MessageIngestor,
    source: Source,
    gateway: FakeGateway,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A photo over 5 MB must not silently turn the post into a text-only one."""
    gateway.missing_photos.add((CHAT_ID, 400))

    raw_id = await ingestor.ingest(
        source.id, make_message(chat_id=CHAT_ID, message_id=400, photos=1)
    )

    assert raw_id is not None
    stored = await _row(session_factory, raw_id)
    assert len(stored.media) == 1
    assert stored.media[0]["skipped"] == "too_large_or_missing"
    assert "s3_key" not in stored.media[0]


async def test_videos_are_described_but_never_downloaded(
    ingestor: MessageIngestor,
    source: Source,
    session_factory: async_sessionmaker[AsyncSession],
    photo_store: FakePhotoStore,
) -> None:
    raw_id = await ingestor.ingest(
        source.id, make_message(chat_id=CHAT_ID, message_id=500, video=True)
    )

    assert raw_id is not None
    stored = await _row(session_factory, raw_id)
    assert [item["kind"] for item in stored.media] == ["video"]
    assert photo_store.objects == {}


# ---------------------------------------------------------------------------
# Edits (SPEC 4.3)
# ---------------------------------------------------------------------------


async def test_edit_updates_the_same_row_and_requeues_it(
    ingestor: MessageIngestor,
    source: Source,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
) -> None:
    original = make_message(chat_id=CHAT_ID, message_id=600, text="Sotiladi 50 000$")
    first_id = await ingestor.ingest(source.id, original)

    edited = make_message(
        chat_id=CHAT_ID,
        message_id=600,
        text="SOTILDI",
        posted_at=original.posted_at,
        edited_at=now_utc(),
    )
    second_id = await ingestor.ingest(source.id, edited, reason=REASON_EDITED)

    assert first_id == second_id
    stored = await _row(session_factory, second_id or 0)
    assert stored.text == "SOTILDI"
    assert stored.edited_at is not None
    assert stored.status == RawMessageStatus.PENDING

    entries = await _stream_entries(redis_client)
    assert [entry["reason"] for entry in entries] == ["new", "edited"]


async def test_an_edit_resets_a_parsed_row_to_pending(
    ingestor: MessageIngestor,
    source: Source,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Otherwise the parser would never revisit a post that said "sotildi"."""
    raw_id = await ingestor.ingest(source.id, make_message(chat_id=CHAT_ID, message_id=610))
    assert raw_id is not None

    async with session_factory() as session:
        row = (
            await session.execute(select(RawMessage).where(RawMessage.id == raw_id))
        ).scalar_one()
        row.status = RawMessageStatus.PARSED
        await session.commit()

    await ingestor.ingest(
        source.id,
        make_message(chat_id=CHAT_ID, message_id=610, text="changed", edited_at=now_utc()),
        reason=REASON_EDITED,
    )

    assert (await _row(session_factory, raw_id)).status == RawMessageStatus.PENDING


async def test_redelivering_an_unchanged_message_does_not_requeue_it(
    ingestor: MessageIngestor,
    source: Source,
    redis_client: Redis,
) -> None:
    """At-least-once delivery means this happens routinely (SPEC 2.3)."""
    message = make_message(chat_id=CHAT_ID, message_id=700)

    first = await ingestor.ingest(source.id, message)
    second = await ingestor.ingest(source.id, message)

    assert first == second
    assert len(await _stream_entries(redis_client)) == 1


# ---------------------------------------------------------------------------
# Deletions (SPEC 4.3)
# ---------------------------------------------------------------------------


async def test_deletion_marks_rows_and_announces_them(
    ingestor: MessageIngestor,
    source: Source,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
) -> None:
    first = await ingestor.ingest(source.id, make_message(chat_id=CHAT_ID, message_id=800))
    await ingestor.ingest(source.id, make_message(chat_id=CHAT_ID, message_id=801))
    await redis_client.delete(STREAM_RAW)

    affected = await ingestor.mark_deleted(
        DeletedMessages(message_ids=[800, 801, 999], chat_id=CHAT_ID), source.id
    )

    assert affected == 2
    assert (await _row(session_factory, first or 0)).deleted_at is not None
    assert [entry["reason"] for entry in await _stream_entries(redis_client)] == [
        "deleted",
        "deleted",
    ]


async def test_deleting_twice_is_a_no_op(ingestor: MessageIngestor, source: Source) -> None:
    await ingestor.ingest(source.id, make_message(chat_id=CHAT_ID, message_id=810))
    deletion = DeletedMessages(message_ids=[810], chat_id=CHAT_ID)

    assert await ingestor.mark_deleted(deletion, source.id) == 1
    assert await ingestor.mark_deleted(deletion, source.id) == 0


async def test_deletion_of_unknown_messages_affects_nothing(
    ingestor: MessageIngestor, source: Source
) -> None:
    deletion = DeletedMessages(message_ids=[1, 2, 3], chat_id=CHAT_ID)
    assert await ingestor.mark_deleted(deletion, source.id) == 0


# ---------------------------------------------------------------------------
# Gap recovery (SPEC 4.4)
# ---------------------------------------------------------------------------


async def test_gap_recovery_ingests_only_what_was_missed(
    ingestor: MessageIngestor,
    source: Source,
    gateway: FakeGateway,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    gateway.seed(
        CHAT_ID,
        *[make_message(chat_id=CHAT_ID, message_id=index) for index in range(1, 6)],
    )

    stored = await backfill_source(
        gateway, ingestor, source_id=source.id, chat_id=CHAT_ID, min_id=3
    )

    assert stored == 2
    async with session_factory() as session:
        ids = list(
            (
                await session.execute(
                    select(RawMessage.tg_message_id).where(RawMessage.source_id == source.id)
                )
            ).scalars()
        )
    assert sorted(ids) == [4, 5]


async def test_restarting_recovers_missed_messages_without_duplicating(
    ingestor: MessageIngestor,
    source: Source,
    gateway: FakeGateway,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
) -> None:
    """The Phase 1 DoD in prose: restart the collector, lose nothing, duplicate nothing."""
    live = make_message(chat_id=CHAT_ID, message_id=1)
    await ingestor.ingest(source.id, live)

    # Messages 2 and 3 arrived while the process was down.
    gateway.seed(
        CHAT_ID,
        live,
        make_message(chat_id=CHAT_ID, message_id=2),
        make_message(chat_id=CHAT_ID, message_id=3),
    )
    await redis_client.delete(STREAM_RAW)

    await backfill_source(gateway, ingestor, source_id=source.id, chat_id=CHAT_ID, min_id=1)

    async with session_factory() as session:
        count = len(
            list(
                (
                    await session.execute(
                        select(RawMessage.id).where(RawMessage.source_id == source.id)
                    )
                ).scalars()
            )
        )
    assert count == 3
    assert len(await _stream_entries(redis_client)) == 2


async def test_backfill_overlapping_live_traffic_is_silent(
    ingestor: MessageIngestor,
    source: Source,
    gateway: FakeGateway,
    redis_client: Redis,
) -> None:
    """Re-reading messages we already have must not wake the parser again."""
    message = make_message(chat_id=CHAT_ID, message_id=1)
    await ingestor.ingest(source.id, message)
    gateway.seed(CHAT_ID, message)
    await redis_client.delete(STREAM_RAW)

    await backfill_source(gateway, ingestor, source_id=source.id, chat_id=CHAT_ID, min_id=0)

    assert await _stream_entries(redis_client) == []


async def test_first_join_backfill_is_bounded_by_age(
    ingestor: MessageIngestor,
    source: Source,
    gateway: FakeGateway,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SPEC 4.2: a first join takes the last N days, not the whole archive."""
    gateway.seed(
        CHAT_ID,
        make_message(chat_id=CHAT_ID, message_id=1, posted_at=now_utc() - timedelta(days=400)),
        make_message(chat_id=CHAT_ID, message_id=2, posted_at=now_utc() - timedelta(days=30)),
        make_message(chat_id=CHAT_ID, message_id=3, posted_at=now_utc() - timedelta(days=2)),
        make_message(chat_id=CHAT_ID, message_id=4, posted_at=now_utc() - timedelta(hours=1)),
    )

    stored = await backfill_source(
        gateway,
        ingestor,
        source_id=source.id,
        chat_id=CHAT_ID,
        since=now_utc() - timedelta(days=7),
    )

    assert stored == 2
    async with session_factory() as session:
        ids = list(
            (
                await session.execute(
                    select(RawMessage.tg_message_id).where(RawMessage.source_id == source.id)
                )
            ).scalars()
        )
    assert sorted(ids) == [3, 4]


async def test_backfill_respects_its_limit(
    ingestor: MessageIngestor, source: Source, gateway: FakeGateway
) -> None:
    gateway.seed(
        CHAT_ID,
        *[
            make_message(chat_id=CHAT_ID, message_id=index, posted_at=now_utc() - timedelta(days=1))
            for index in range(1, 11)
        ],
    )

    stored = await backfill_source(
        gateway, ingestor, source_id=source.id, chat_id=CHAT_ID, min_id=0, limit=4
    )

    assert stored == 4
