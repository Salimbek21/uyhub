"""The collector's event routing, source registry and shutdown (SPEC 4.3, 4.4)."""

from __future__ import annotations

import asyncio

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fakes import FakeGateway, FakePhotoStore, make_message
from uyhub.collector import accounts
from uyhub.collector.heartbeat import (
    HEARTBEAT_TTL_SECONDS,
    heartbeat_key,
    is_alive,
    write_heartbeat,
)
from uyhub.collector.ingest import MessageIngestor
from uyhub.collector.runner import Collector, SourceRegistry
from uyhub.collector.types import DeletedMessages
from uyhub.core.config import Settings
from uyhub.core.streams import STREAM_RAW
from uyhub.models.enums import SourceStatus
from uyhub.models.telegram import RawMessage, Source, TgAccount

pytestmark = pytest.mark.integration

ACTIVE_CHAT = -1001111111111
PAUSED_CHAT = -1002222222222
UNKNOWN_CHAT = -1003333333333


@pytest.fixture
async def account(session_factory: async_sessionmaker[AsyncSession]) -> TgAccount:
    async with session_factory() as session:
        row = await accounts.ensure_account(session, label="primary", phone="+998901234567")
        await session.commit()
        await session.refresh(row)
        return row


@pytest.fixture
async def seeded_sources(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with session_factory() as session:
        active = Source(tg_chat_id=ACTIVE_CHAT, username="active_src", status=SourceStatus.ACTIVE)
        paused = Source(tg_chat_id=PAUSED_CHAT, username="paused_src", status=SourceStatus.PAUSED)
        session.add_all([active, paused])
        await session.commit()
        return {"active": active.id, "paused": paused.id}


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def collector(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    gateway: FakeGateway,
    settings: Settings,
    account: TgAccount,
) -> Collector:
    ingestor = MessageIngestor(
        session_factory=session_factory,
        redis=redis_client,
        gateway=gateway,
        photo_store=FakePhotoStore(),
    )
    built = Collector(
        session_factory=session_factory,
        redis=redis_client,
        gateway=gateway,
        ingestor=ingestor,
        settings=settings,
        account_id=account.id,
    )
    built.register_handlers()
    return built


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------


async def test_registry_contains_only_active_sources(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    seeded_sources: dict[str, int],
) -> None:
    registry = SourceRegistry(session_factory, redis_client)
    await registry.refresh()

    assert registry.source_for(ACTIVE_CHAT) == seeded_sources["active"]
    assert registry.source_for(PAUSED_CHAT) is None
    assert registry.source_for(UNKNOWN_CHAT) is None
    assert registry.source_for(None) is None


async def test_registry_picks_up_a_newly_activated_source(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    seeded_sources: dict[str, int],
) -> None:
    """A join must start being read without restarting the process (SPEC 4.3)."""
    registry = SourceRegistry(session_factory, redis_client)
    await registry.refresh()
    assert registry.source_for(PAUSED_CHAT) is None

    async with session_factory() as session:
        row = (
            await session.execute(select(Source).where(Source.id == seeded_sources["paused"]))
        ).scalar_one()
        row.status = SourceStatus.ACTIVE
        await session.commit()

    await registry.refresh()
    assert registry.source_for(PAUSED_CHAT) == seeded_sources["paused"]


# ---------------------------------------------------------------------------
# Event routing
# ---------------------------------------------------------------------------


async def test_messages_from_active_sources_are_ingested(
    collector: Collector,
    gateway: FakeGateway,
    seeded_sources: dict[str, int],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await collector.registry.refresh()

    await gateway.emit_new(make_message(chat_id=ACTIVE_CHAT, message_id=1))
    await collector.drain()

    async with session_factory() as session:
        stored = list(
            (
                await session.execute(
                    select(RawMessage.source_id).where(RawMessage.tg_message_id == 1)
                )
            ).scalars()
        )
    assert stored == [seeded_sources["active"]]


async def test_messages_from_unknown_chats_are_dropped(
    collector: Collector,
    gateway: FakeGateway,
    redis_client: Redis,
) -> None:
    """The userbot is in chats we do not collect from; those must be ignored."""
    await collector.registry.refresh()

    await gateway.emit_new(make_message(chat_id=UNKNOWN_CHAT, message_id=1))
    await gateway.emit_new(make_message(chat_id=PAUSED_CHAT, message_id=2))
    await collector.drain()

    assert await redis_client.xlen(STREAM_RAW) == 0


async def test_albums_and_edits_route_through_their_handlers(
    collector: Collector,
    gateway: FakeGateway,
    redis_client: Redis,
    seeded_sources: dict[str, int],
) -> None:
    await collector.registry.refresh()

    await gateway.emit_album(
        make_message(chat_id=ACTIVE_CHAT, message_id=10, photos=2, grouped_id=5)
    )
    await collector.drain()
    await gateway.emit_edited(
        make_message(chat_id=ACTIVE_CHAT, message_id=10, photos=2, grouped_id=5, text="SOTILDI")
    )
    await collector.drain()

    entries = await redis_client.xrange(STREAM_RAW)
    assert [fields["reason"] for _entry_id, fields in entries] == ["new", "edited"]


async def test_deletions_mark_the_rows(
    collector: Collector,
    gateway: FakeGateway,
    seeded_sources: dict[str, int],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await collector.registry.refresh()
    await gateway.emit_new(make_message(chat_id=ACTIVE_CHAT, message_id=20))
    await collector.drain()

    await gateway.emit_deleted(DeletedMessages(message_ids=[20], chat_id=ACTIVE_CHAT))
    await collector.drain()

    async with session_factory() as session:
        row = (
            await session.execute(select(RawMessage).where(RawMessage.tg_message_id == 20))
        ).scalar_one()
    assert row.deleted_at is not None


async def test_a_deletion_without_a_chat_id_is_survivable(
    collector: Collector, gateway: FakeGateway
) -> None:
    """Telegram omits the chat for private chats and small groups (SPEC 4.3)."""
    await collector.registry.refresh()

    await gateway.emit_deleted(DeletedMessages(message_ids=[1, 2], chat_id=None))
    await collector.drain()


async def test_a_failing_ingest_does_not_kill_the_collector(
    collector: Collector,
    gateway: FakeGateway,
    seeded_sources: dict[str, int],
) -> None:
    """One malformed message must not take the service down (SPEC 4.4)."""
    await collector.registry.refresh()

    async def exploding_download(chat_id: int, message_id: int) -> bytes | None:
        raise RuntimeError("storage is on fire")

    gateway.download_photo = exploding_download  # type: ignore[method-assign]

    await gateway.emit_new(make_message(chat_id=ACTIVE_CHAT, message_id=30, photos=1))
    await collector.drain()

    # Still serving: a later, healthy message is ingested normally.
    gateway.download_photo = FakeGateway().download_photo  # type: ignore[method-assign]
    await gateway.emit_new(make_message(chat_id=ACTIVE_CHAT, message_id=31))
    await collector.drain()


async def test_drain_waits_for_in_flight_work(
    collector: Collector,
    gateway: FakeGateway,
    seeded_sources: dict[str, int],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SIGTERM must not drop a download that is halfway done (SPEC 4.4)."""
    await collector.registry.refresh()
    released = asyncio.Event()

    original = gateway.download_photo

    async def slow_download(chat_id: int, message_id: int) -> bytes | None:
        await released.wait()
        return await original(chat_id, message_id)

    gateway.download_photo = slow_download  # type: ignore[method-assign]

    await gateway.emit_new(make_message(chat_id=ACTIVE_CHAT, message_id=40, photos=1))
    await asyncio.sleep(0)
    released.set()
    await collector.drain()

    async with session_factory() as session:
        stored = (
            await session.execute(select(RawMessage).where(RawMessage.tg_message_id == 40))
        ).scalar_one()
    assert stored.media[0]["s3_key"].endswith("/0.jpg")


async def test_drain_with_nothing_in_flight_returns(collector: Collector) -> None:
    await collector.drain()


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


async def test_heartbeat_is_written_with_a_ttl(redis_client: Redis) -> None:
    await write_heartbeat(redis_client, 1)

    assert await is_alive(redis_client, 1) is True
    ttl = await redis_client.ttl(heartbeat_key(1))
    assert 0 < ttl <= HEARTBEAT_TTL_SECONDS


async def test_a_missing_heartbeat_reads_as_dead(redis_client: Redis) -> None:
    assert await is_alive(redis_client, 999) is False
