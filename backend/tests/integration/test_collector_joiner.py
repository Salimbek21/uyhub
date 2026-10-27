"""The join worker and the account budget (SPEC 4.2, 4.4).

Joining is rate-limited on purpose: it is the behaviour most likely to get the
userbot banned, so the budget lives in Postgres and survives a restart.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon.errors.rpcerrorlist import ChannelPrivateError, FloodWaitError

from fakes import FakeGateway, FakePhotoStore, make_message
from uyhub.collector import accounts
from uyhub.collector.ingest import MessageIngestor
from uyhub.collector.joiner import JoinWorker
from uyhub.collector.types import ResolvedChat
from uyhub.core.clock import now_utc
from uyhub.core.config import Settings
from uyhub.models.enums import AccountStatus, SourceStatus
from uyhub.models.telegram import RawMessage, Source, TgAccount

pytestmark = pytest.mark.integration

CHAT_ID = -1009876543210


@pytest.fixture
async def account(session_factory: async_sessionmaker[AsyncSession]) -> TgAccount:
    async with session_factory() as session:
        row = await accounts.ensure_account(session, label="primary", phone="+998901234567")
        await session.commit()
        await session.refresh(row)
        return row


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    gateway.join_result = ResolvedChat(
        chat_id=CHAT_ID, title="Test group", username="uyhub_test", kind="supergroup"
    )
    return gateway


@pytest.fixture
def worker(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    gateway: FakeGateway,
    settings: Settings,
    account: TgAccount,
) -> JoinWorker:
    ingestor = MessageIngestor(
        session_factory=session_factory,
        redis=redis_client,
        gateway=gateway,
        photo_store=FakePhotoStore(),
    )
    return JoinWorker(
        session_factory=session_factory,
        gateway=gateway,
        ingestor=ingestor,
        settings=settings,
        account_id=account.id,
    )


async def _add_source(
    session_factory: async_sessionmaker[AsyncSession], username: str, priority: int = 100
) -> int:
    async with session_factory() as session:
        row = Source(username=username, priority=priority, status=SourceStatus.PENDING_JOIN)
        session.add(row)
        await session.commit()
        return row.id


async def _source(session_factory: async_sessionmaker[AsyncSession], source_id: int) -> Source:
    async with session_factory() as session:
        return (await session.execute(select(Source).where(Source.id == source_id))).scalar_one()


async def test_no_pending_sources_is_not_an_error(worker: JoinWorker) -> None:
    assert await worker.join_next() is False


async def test_joining_records_the_chat_and_activates_the_source(
    worker: JoinWorker,
    gateway: FakeGateway,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _add_source(session_factory, "uyhub_test")
    gateway.seed(CHAT_ID, make_message(chat_id=CHAT_ID, message_id=1))

    assert await worker.join_next() is True

    joined = await _source(session_factory, source_id)
    assert joined.status == SourceStatus.ACTIVE
    assert joined.tg_chat_id == CHAT_ID
    assert joined.title == "Test group"
    assert joined.joined_at is not None
    assert gateway.joined == ["@uyhub_test"]


async def test_history_is_backfilled_on_join(
    worker: JoinWorker,
    gateway: FakeGateway,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A newly joined source arrives with its recent posts, but not its archive."""
    source_id = await _add_source(session_factory, "uyhub_test")
    gateway.seed(
        CHAT_ID,
        *[make_message(chat_id=CHAT_ID, message_id=index) for index in range(1, 4)],
        make_message(chat_id=CHAT_ID, message_id=99, posted_at=now_utc() - timedelta(days=365)),
    )

    await worker.join_next()

    async with session_factory() as session:
        stored = list(
            (
                await session.execute(
                    select(RawMessage.tg_message_id).where(RawMessage.source_id == source_id)
                )
            ).scalars()
        )
    assert sorted(stored) == [1, 2, 3]


async def test_sources_are_joined_in_priority_order(
    worker: JoinWorker, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The curated first batch goes first (docs/DECISIONS.md, OPEN_QUESTIONS A3)."""
    await _add_source(session_factory, "low_priority", priority=100)
    urgent_id = await _add_source(session_factory, "high_priority", priority=1)

    await worker.join_next()

    assert (await _source(session_factory, urgent_id)).status == SourceStatus.ACTIVE


async def test_daily_budget_stops_the_worker(
    worker: JoinWorker,
    gateway: FakeGateway,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    account: TgAccount,
) -> None:
    for index in range(settings.collector_max_joins_per_day + 2):
        await _add_source(session_factory, f"source_{index}")

    joined = 0
    for _ in range(settings.collector_max_joins_per_day + 2):
        # Each join needs a distinct chat id, or the unique constraint fires.
        gateway.join_result = ResolvedChat(chat_id=CHAT_ID - joined, kind="supergroup")
        if await worker.join_next():
            joined += 1

    assert joined == settings.collector_max_joins_per_day

    async with session_factory() as session:
        refreshed = (
            await session.execute(select(TgAccount).where(TgAccount.id == account.id))
        ).scalar_one()
        assert refreshed.joins_today == settings.collector_max_joins_per_day


async def test_budget_resets_after_a_day(
    session_factory: async_sessionmaker[AsyncSession], account: TgAccount
) -> None:
    async with session_factory() as session:
        row = (
            await session.execute(select(TgAccount).where(TgAccount.id == account.id))
        ).scalar_one()
        row.joins_today = 5
        row.joins_reset_at = now_utc() - accounts.JOIN_BUDGET_WINDOW
        await session.commit()

    async with session_factory() as session:
        assert await accounts.claim_join_slot(session, account.id, max_per_day=5) is True
        await session.commit()

    async with session_factory() as session:
        refreshed = (
            await session.execute(select(TgAccount).where(TgAccount.id == account.id))
        ).scalar_one()
        assert refreshed.joins_today == 1


async def test_flood_wait_parks_the_account(
    worker: JoinWorker,
    gateway: FakeGateway,
    session_factory: async_sessionmaker[AsyncSession],
    account: TgAccount,
) -> None:
    await _add_source(session_factory, "uyhub_test")
    gateway.join_error = FloodWaitError(request=None, capture=300)

    assert await worker.join_next() is False

    async with session_factory() as session:
        refreshed = (
            await session.execute(select(TgAccount).where(TgAccount.id == account.id))
        ).scalar_one()
    assert refreshed.status == AccountStatus.FLOOD_WAIT
    assert refreshed.flood_until is not None
    assert refreshed.flood_until > now_utc()


async def test_a_private_channel_parks_the_source_with_a_reason(
    worker: JoinWorker,
    gateway: FakeGateway,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _add_source(session_factory, "uyhub_test")
    gateway.join_error = ChannelPrivateError(request=None)

    assert await worker.join_next() is False

    failed = await _source(session_factory, source_id)
    assert failed.status == SourceStatus.ERROR
    assert failed.error_text == "ChannelPrivateError"


async def test_a_source_with_no_reference_cannot_be_joined(
    worker: JoinWorker, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        row = Source(status=SourceStatus.PENDING_JOIN)
        session.add(row)
        await session.commit()
        source_id = row.id

    assert await worker.join_next() is False
    assert (await _source(session_factory, source_id)).status == SourceStatus.ERROR
