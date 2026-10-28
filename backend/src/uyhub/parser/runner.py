"""The parser service: consume ``stream:raw``, parse, store, acknowledge.

Delivery is at-least-once (SPEC 2.3), so the unit of work is idempotent by
construction — parsing a message twice writes the same row twice and nothing
else happens. A message that fails is retried until ``MAX_DELIVERIES``, then
dead-lettered rather than redelivered forever.

The exchange rate is read once per batch rather than per message: it changes
daily and the lookup would otherwise be the busiest query in the system.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uyhub.core.config import Settings
from uyhub.core.logging import get_logger
from uyhub.core.streams import (
    MAX_DELIVERIES,
    STREAM_RAW,
    StreamMessage,
    ack,
    claim_stale,
    dead_letter,
    ensure_group,
    read_group,
)
from uyhub.models.enums import Currency, RawMessageStatus
from uyhub.models.telegram import RawMessage, Source
from uyhub.parser.extractor import Extractor
from uyhub.parser.pipeline import ParseResult, parse
from uyhub.rates.store import latest_rate
from uyhub.service import install_signal_handlers

log = get_logger(__name__)

CONSUMER_GROUP = "parser"
BATCH_SIZE = 20
BLOCK_MS = 5_000


@dataclass(frozen=True, slots=True)
class MessageContext:
    """Everything the pipeline needs about a stored message."""

    raw_message_id: int
    text: str
    photo_count: int
    source_trust: float


async def load_context(session: AsyncSession, raw_message_id: int) -> MessageContext | None:
    """Read one message and its source's trust score."""
    row = (
        await session.execute(
            select(RawMessage.id, RawMessage.text, RawMessage.media, Source.trust_score)
            .join(Source, Source.id == RawMessage.source_id)
            .where(RawMessage.id == raw_message_id)
        )
    ).first()
    if row is None:
        return None

    photos = [item for item in (row.media or []) if item.get("kind") == "photo"]
    return MessageContext(
        raw_message_id=row.id,
        text=row.text or "",
        photo_count=len(photos),
        source_trust=float(row.trust_score),
    )


async def store_result(
    session: AsyncSession, raw_message_id: int, result: ParseResult, parser_version: int
) -> None:
    """Write the parser's verdict back onto the message."""
    extracted = result.extraction.as_json() if result.extraction is not None else None
    await session.execute(
        update(RawMessage)
        .where(RawMessage.id == raw_message_id)
        .values(
            status=result.status,
            parser_version=parser_version,
            extracted=extracted,
        )
    )


class ParserWorker:
    """One consumer of ``stream:raw``."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        settings: Settings,
        consumer_name: str = "parser-1",
        extractor: Extractor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._settings = settings
        self._consumer = consumer_name
        self._extractor = extractor

    async def run(self, stop: asyncio.Event) -> None:
        await ensure_group(self._redis, STREAM_RAW, CONSUMER_GROUP)
        log.info("service.started", service="parser", consumer=self._consumer)
        try:
            while not stop.is_set():
                # Reclaim before reading: a restarted worker should finish what
                # its predecessor was holding before taking on anything new.
                stale = await claim_stale(
                    self._redis, STREAM_RAW, CONSUMER_GROUP, self._consumer, count=BATCH_SIZE
                )
                messages = stale or await read_group(
                    self._redis,
                    STREAM_RAW,
                    CONSUMER_GROUP,
                    self._consumer,
                    count=BATCH_SIZE,
                    block_ms=BLOCK_MS,
                )
                if messages:
                    await self.handle_batch(messages)
        finally:
            log.info("service.stopped", service="parser")

    async def handle_batch(self, messages: list[StreamMessage]) -> int:
        """Parse a batch. Returns how many were parsed successfully."""
        uzs_per_usd = await self._rate()
        parsed = 0

        for message in messages:
            try:
                await self._handle_one(message, uzs_per_usd)
            except Exception as exc:
                await self._on_failure(message, exc)
            else:
                await ack(self._redis, STREAM_RAW, CONSUMER_GROUP, message.id)
                parsed += 1

        return parsed

    async def _handle_one(self, message: StreamMessage, uzs_per_usd: Decimal | None) -> None:
        raw_message_id = int(message.fields["raw_message_id"])

        async with self._session_factory() as session:
            context = await load_context(session, raw_message_id)
            if context is None:
                # The row was deleted under us; there is nothing to parse and
                # nothing to retry.
                log.info("parser.message_missing", raw_message_id=raw_message_id)
                return

            result = parse(
                context.text,
                photo_count=context.photo_count,
                source_trust=context.source_trust,
                uzs_per_usd=uzs_per_usd,
                extractor=self._extractor,
                settings=self._settings,
            )
            await store_result(session, raw_message_id, result, self._settings.parser_version)
            await session.commit()

        log.info(
            "parser.message_parsed",
            raw_message_id=raw_message_id,
            status=result.status.value,
            reject_reason=result.reject_reason,
            quality=result.extraction.quality_score if result.extraction else None,
        )

    async def _on_failure(self, message: StreamMessage, exc: Exception) -> None:
        if message.deliveries >= MAX_DELIVERIES:
            await dead_letter(
                self._redis, STREAM_RAW, CONSUMER_GROUP, message, error=type(exc).__name__
            )
            await self._mark_failed(message)
            return
        # Left unacked: the group redelivers it, and claim_stale picks it up.
        log.warning(
            "parser.message_failed",
            entry_id=message.id,
            error=type(exc).__name__,
            delivery=message.deliveries,
        )

    async def _mark_failed(self, message: StreamMessage) -> None:
        raw_id = message.fields.get("raw_message_id")
        if raw_id is None:
            return
        async with self._session_factory() as session:
            await session.execute(
                update(RawMessage)
                .where(RawMessage.id == int(raw_id))
                .values(status=RawMessageStatus.FAILED)
            )
            await session.commit()

    async def _rate(self) -> Decimal | None:
        async with self._session_factory() as session:
            return await latest_rate(session, Currency.USD)


async def run_parser(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    consumer_name: str = "parser-1",
    stop: asyncio.Event | None = None,
) -> None:
    """Start the parser worker and run until SIGTERM."""
    stop = stop or asyncio.Event()
    install_signal_handlers(stop)

    worker = ParserWorker(
        session_factory=session_factory,
        redis=redis,
        settings=settings,
        consumer_name=consumer_name,
    )
    with contextlib.suppress(asyncio.CancelledError):
        await worker.run(stop)
