"""The parser worker against real Postgres and Redis (SPEC 2.3, 5, 6).

The pipeline itself is covered by unit tests on strings. What these exercise is
everything around it: reading the right row, writing the verdict back, acking,
and what happens to a message that keeps failing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uyhub.core.clock import now_utc, today_utc
from uyhub.core.config import Settings, get_settings
from uyhub.core.streams import (
    MAX_DELIVERIES,
    STREAM_DEAD,
    STREAM_RAW,
    StreamMessage,
    ensure_group,
    pending_count,
    publish,
    read_group,
)
from uyhub.models.enums import Currency, RawMessageStatus, SourceStatus
from uyhub.models.telegram import RawMessage, Source
from uyhub.parser.reparse import requeue
from uyhub.parser.runner import CONSUMER_GROUP, ParserWorker, load_context
from uyhub.parser.schema import RawExtraction
from uyhub.rates.cbu import Rate
from uyhub.rates.store import latest_rate, save_rate

pytestmark = pytest.mark.integration

LISTING = (
    "SOTILADI\n3 xonali kvartira, Chilonzor tumani\n3/5/9, 75 m2\n"
    "Narxi: 65 000 $\nTel: +998 90 123 45 67"
)
CHAT = "Assalomu alaykum hurmatli guruh a'zolari"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("PHONE_HASH_KEY", "parser-runner-test-key")
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Source]:
    async with session_factory() as session:
        row = Source(
            tg_chat_id=-1005555555555,
            username="parser_test",
            status=SourceStatus.ACTIVE,
            trust_score=1.0,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        yield row


@pytest.fixture
def worker(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    settings: Settings,
) -> ParserWorker:
    return ParserWorker(
        session_factory=session_factory,
        redis=redis_client,
        settings=settings,
        consumer_name="test-worker",
    )


async def _store(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    *,
    text: str,
    tg_message_id: int = 1,
    photos: int = 0,
) -> int:
    media = [{"kind": "photo", "s3_key": f"raw/1/1/{n}.jpg"} for n in range(photos)]
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
        return row.id


async def _row(session_factory: async_sessionmaker[AsyncSession], raw_id: int) -> RawMessage:
    async with session_factory() as session:
        return (
            await session.execute(select(RawMessage).where(RawMessage.id == raw_id))
        ).scalar_one()


# ---------------------------------------------------------------------------
# Reading the message
# ---------------------------------------------------------------------------


async def test_context_carries_the_text_photos_and_source_trust(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    """Trust feeds the quality score, so it has to come from the source row."""
    async with session_factory() as session:
        await session.execute(update(Source).where(Source.id == source.id).values(trust_score=0.5))
        await session.commit()

    raw_id = await _store(session_factory, source, text=LISTING, photos=3)

    async with session_factory() as session:
        context = await load_context(session, raw_id)

    assert context is not None
    assert context.text == LISTING
    assert context.photo_count == 3
    assert context.source_trust == 0.5


async def test_a_missing_row_yields_no_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert await load_context(session, 999_999) is None


# ---------------------------------------------------------------------------
# Parsing a batch
# ---------------------------------------------------------------------------


async def test_a_listing_is_parsed_and_stored(
    worker: ParserWorker,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    settings: Settings,
) -> None:
    raw_id = await _store(session_factory, source, text=LISTING, photos=4)

    parsed = await worker.handle_batch(
        [StreamMessage(id="1-0", fields={"raw_message_id": str(raw_id)})]
    )

    assert parsed == 1
    row = await _row(session_factory, raw_id)
    assert row.status is RawMessageStatus.PARSED
    assert row.parser_version == settings.parser_version
    assert row.extracted is not None
    assert row.extracted["deal_type"] == "sale"
    assert row.extracted["rooms"] == 3
    assert row.extracted["district"] == "chilonzor"
    assert row.extracted["title"] == "3 xonali kvartira, Chilonzor, 75 m²"


async def test_no_plaintext_phone_reaches_the_database(
    worker: ParserWorker,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
) -> None:
    """The whole point of docs/DECISIONS.md P.2, asserted against real storage."""
    raw_id = await _store(session_factory, source, text=LISTING)

    await worker.handle_batch([StreamMessage(id="1-0", fields={"raw_message_id": str(raw_id)})])

    row = await _row(session_factory, raw_id)
    assert row.extracted is not None
    assert len(row.extracted["phone_hashes"]) == 1
    assert "901234567" not in str(row.extracted)
    assert "phones" not in row.extracted


async def test_a_non_listing_is_marked_rejected_with_no_extraction(
    worker: ParserWorker,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
) -> None:
    raw_id = await _store(session_factory, source, text=CHAT)

    await worker.handle_batch([StreamMessage(id="1-0", fields={"raw_message_id": str(raw_id)})])

    row = await _row(session_factory, raw_id)
    assert row.status is RawMessageStatus.REJECTED_PREFILTER
    assert row.extracted is None


async def test_parsing_the_same_message_twice_is_harmless(
    worker: ParserWorker,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
) -> None:
    """At-least-once delivery means this happens routinely (SPEC 2.3)."""
    raw_id = await _store(session_factory, source, text=LISTING)
    message = StreamMessage(id="1-0", fields={"raw_message_id": str(raw_id)})

    await worker.handle_batch([message])
    first = (await _row(session_factory, raw_id)).extracted
    await worker.handle_batch([message])
    second = (await _row(session_factory, raw_id)).extracted

    assert first == second


async def test_a_deleted_row_is_acked_rather_than_retried_forever(
    worker: ParserWorker, redis_client: Redis
) -> None:
    await ensure_group(redis_client, STREAM_RAW, CONSUMER_GROUP)
    await publish(redis_client, STREAM_RAW, {"raw_message_id": 999_999})
    messages = await read_group(
        redis_client, STREAM_RAW, CONSUMER_GROUP, "test-worker", block_ms=50
    )

    assert await worker.handle_batch(messages) == 1
    assert await pending_count(redis_client, STREAM_RAW, CONSUMER_GROUP) == 0


async def test_a_batch_continues_past_one_bad_message(
    worker: ParserWorker,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
) -> None:
    good = await _store(session_factory, source, text=LISTING, tg_message_id=2)
    batch = [
        StreamMessage(id="1-0", fields={"raw_message_id": "not-a-number"}),
        StreamMessage(id="2-0", fields={"raw_message_id": str(good)}),
    ]

    assert await worker.handle_batch(batch) == 1
    assert (await _row(session_factory, good)).status is RawMessageStatus.PARSED


async def test_a_message_that_keeps_failing_is_dead_lettered(
    worker: ParserWorker,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    redis_client: Redis,
) -> None:
    """Otherwise one unparseable post blocks the group forever (SPEC 2.3)."""
    raw_id = await _store(session_factory, source, text=LISTING, tg_message_id=3)
    exhausted = StreamMessage(
        id="9-0",
        fields={"raw_message_id": str(raw_id), "reason": "new"},
        deliveries=MAX_DELIVERIES,
    )

    await ensure_group(redis_client, STREAM_RAW, CONSUMER_GROUP)
    await worker._on_failure(exhausted, ValueError("broken"))

    dead = await redis_client.xrange(STREAM_DEAD)
    assert [fields["raw_message_id"] for _entry_id, fields in dead] == [str(raw_id)]
    assert (await _row(session_factory, raw_id)).status is RawMessageStatus.FAILED


async def test_a_first_failure_is_left_for_redelivery(
    worker: ParserWorker,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    redis_client: Redis,
) -> None:
    raw_id = await _store(session_factory, source, text=LISTING, tg_message_id=4)
    fresh = StreamMessage(id="9-0", fields={"raw_message_id": str(raw_id)}, deliveries=1)

    await worker._on_failure(fresh, ValueError("transient"))

    assert await redis_client.xlen(STREAM_DEAD) == 0
    assert (await _row(session_factory, raw_id)).status is RawMessageStatus.PENDING


# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------


async def test_a_uzs_price_is_converted_using_the_stored_rate(
    worker: ParserWorker,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
) -> None:
    async with session_factory() as session:
        await save_rate(
            session, Rate(currency=Currency.USD, rate_uzs=Decimal(12_000), on_date=today_utc())
        )
        await session.commit()

    text = "Продается 2-комнатная квартира, Юнусабад, 780 000 000 сум. 90 123 45 67"
    raw_id = await _store(session_factory, source, text=text, tg_message_id=5)

    await worker.handle_batch([StreamMessage(id="1-0", fields={"raw_message_id": str(raw_id)})])

    row = await _row(session_factory, raw_id)
    assert row.extracted is not None
    assert row.extracted["price_usd"] == "65000.00"


async def test_without_a_rate_a_uzs_price_has_no_usd_value(
    worker: ParserWorker,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
) -> None:
    """A missing rate must not become a wrong number in the price filter."""
    text = "Продается квартира, Чиланзар, 2-комнатная, 780 000 000 сум. 90 123 45 67"
    raw_id = await _store(session_factory, source, text=text, tg_message_id=6)

    await worker.handle_batch([StreamMessage(id="1-0", fields={"raw_message_id": str(raw_id)})])

    row = await _row(session_factory, raw_id)
    assert row.extracted is not None
    assert row.extracted["price_amount"] == "780000000"
    assert row.extracted["price_usd"] is None


class TestRateStore:
    async def test_saving_the_same_day_twice_updates(self, db_session: AsyncSession) -> None:
        for value in (Decimal(11_000), Decimal(12_000)):
            await save_rate(
                db_session, Rate(currency=Currency.USD, rate_uzs=value, on_date=today_utc())
            )
        assert await latest_rate(db_session) == Decimal(12_000)

    async def test_the_newest_rate_wins(self, db_session: AsyncSession) -> None:
        await save_rate(
            db_session,
            Rate(
                currency=Currency.USD,
                rate_uzs=Decimal(11_000),
                on_date=today_utc() - timedelta(days=3),
            ),
        )
        await save_rate(
            db_session,
            Rate(currency=Currency.USD, rate_uzs=Decimal(12_000), on_date=today_utc()),
        )
        assert await latest_rate(db_session) == Decimal(12_000)

    async def test_a_stale_rate_is_ignored(self, db_session: AsyncSession) -> None:
        """Weeks old is wrong enough to be worse than missing."""
        await save_rate(
            db_session,
            Rate(
                currency=Currency.USD,
                rate_uzs=Decimal(11_000),
                on_date=today_utc() - timedelta(days=90),
            ),
        )
        assert await latest_rate(db_session) is None

    async def test_no_rate_at_all_is_none(self, db_session: AsyncSession) -> None:
        assert await latest_rate(db_session) is None


# ---------------------------------------------------------------------------
# Reparse
# ---------------------------------------------------------------------------


class TestReparse:
    async def test_messages_are_republished(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        source: Source,
        redis_client: Redis,
    ) -> None:
        raw_id = await _store(session_factory, source, text=LISTING, tg_message_id=10)

        async with session_factory() as session:
            assert await requeue(session, redis_client) == 1

        entries = await redis_client.xrange(STREAM_RAW)
        assert [fields["raw_message_id"] for _entry_id, fields in entries] == [str(raw_id)]
        assert entries[0][1]["reason"] == "reparse"

    async def test_version_below_skips_already_current_messages(
        self,
        worker: ParserWorker,
        session_factory: async_sessionmaker[AsyncSession],
        source: Source,
        redis_client: Redis,
        settings: Settings,
    ) -> None:
        raw_id = await _store(session_factory, source, text=LISTING, tg_message_id=11)
        await worker.handle_batch([StreamMessage(id="1-0", fields={"raw_message_id": str(raw_id)})])
        await redis_client.delete(STREAM_RAW)

        async with session_factory() as session:
            same = await requeue(session, redis_client, version_below=settings.parser_version)
            newer = await requeue(session, redis_client, version_below=settings.parser_version + 1)

        assert same == 0
        assert newer == 1

    async def test_a_never_parsed_message_qualifies(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        source: Source,
        redis_client: Redis,
    ) -> None:
        await _store(session_factory, source, text=LISTING, tg_message_id=12)

        async with session_factory() as session:
            assert await requeue(session, redis_client, version_below=1) == 1

    async def test_since_filters_by_posting_date(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        source: Source,
        redis_client: Redis,
    ) -> None:
        async with session_factory() as session:
            session.add(
                RawMessage(
                    source_id=source.id,
                    tg_message_id=13,
                    posted_at=now_utc() - timedelta(days=400),
                    text=LISTING,
                )
            )
            await session.commit()

        async with session_factory() as session:
            recent = await requeue(session, redis_client, since=now_utc() - timedelta(days=7))

        assert recent == 0

    async def test_a_purged_message_cannot_be_reparsed(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        source: Source,
        redis_client: Redis,
    ) -> None:
        """Retention eventually removes the text (OPEN_QUESTIONS A7)."""
        async with session_factory() as session:
            session.add(
                RawMessage(source_id=source.id, tg_message_id=14, posted_at=now_utc(), text=None)
            )
            await session.commit()

        async with session_factory() as session:
            assert await requeue(session, redis_client) == 0

    async def test_the_limit_is_respected(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        source: Source,
        redis_client: Redis,
    ) -> None:
        for index in range(5):
            await _store(session_factory, source, text=LISTING, tg_message_id=20 + index)

        async with session_factory() as session:
            assert await requeue(session, redis_client, limit=2) == 2


def test_a_raw_extraction_rejects_unknown_fields() -> None:
    """`extra="forbid"` is what stops an LLM inventing a field we then store."""
    with pytest.raises(ValueError, match="surprise"):
        RawExtraction(surprise="value")  # type: ignore[call-arg]
