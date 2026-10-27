"""Turning a received message into a ``raw_messages`` row and a queue entry.

This is the hinge of the collector and the part the tests drive hardest: albums,
edits, deletions and backfill all converge here, and every one of them has to be
safe to run twice. The unique key ``(source_id, tg_message_id)`` plus an upsert
is what makes that true — a redelivered message updates the same row rather than
creating a second one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uyhub.collector.gateway import MAX_PHOTOS_PER_POST, TelegramGateway
from uyhub.collector.media import PhotoStore, raw_key
from uyhub.collector.sources import record_message
from uyhub.collector.types import DeletedMessages, IncomingMedia, IncomingMessage
from uyhub.core.clock import now_utc
from uyhub.core.logging import get_logger
from uyhub.core.streams import STREAM_RAW, publish
from uyhub.models.enums import RawMessageStatus
from uyhub.models.telegram import RawMessage

log = get_logger(__name__)

SessionFactory = Callable[[], AsyncSession]

REASON_NEW = "new"
REASON_EDITED = "edited"
REASON_BACKFILL = "backfill"


class MessageIngestor:
    """Writes received messages to Postgres and announces them on ``stream:raw``."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        gateway: TelegramGateway,
        photo_store: PhotoStore,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._gateway = gateway
        self._photos = photo_store

    async def ingest(
        self,
        source_id: int,
        message: IncomingMessage,
        *,
        reason: str = REASON_NEW,
    ) -> int | None:
        """Store one message or album. Returns the ``raw_messages`` id, or ``None``
        if the message was ignored.

        Photos are downloaded before the row is written so that a row never
        promises media the parser cannot find.
        """
        if message.from_self or message.is_empty:
            log.debug(
                "collector.message_ignored",
                source_id=source_id,
                tg_message_id=message.message_id,
                reason="from_self" if message.from_self else "empty",
            )
            return None

        media = await self._store_photos(source_id, message)

        async with self._session_factory() as session:
            raw_message_id, changed = await self._upsert(session, source_id, message, media)
            await record_message(
                session,
                source_id,
                tg_message_id=message.message_id,
                posted_at=message.posted_at,
            )
            await session.commit()

        if not changed:
            log.debug(
                "collector.message_unchanged",
                source_id=source_id,
                tg_message_id=message.message_id,
            )
            return raw_message_id

        await publish(
            self._redis,
            STREAM_RAW,
            {"raw_message_id": raw_message_id, "reason": reason},
        )
        log.info(
            "collector.message_ingested",
            source_id=source_id,
            tg_message_id=message.message_id,
            raw_message_id=raw_message_id,
            photos=len([item for item in media if item.get("kind") == "photo"]),
            reason=reason,
        )
        return raw_message_id

    async def mark_deleted(self, deletion: DeletedMessages, source_id: int) -> int:
        """Flag deleted posts. Returns how many rows were actually affected.

        Deletions are advisory: SPEC 8 keeps the listing alive for three days
        because people routinely delete and immediately repost.
        """
        if not deletion.message_ids:
            return 0

        async with self._session_factory() as session:
            result = await session.execute(
                update(RawMessage)
                .where(
                    RawMessage.source_id == source_id,
                    RawMessage.tg_message_id.in_(deletion.message_ids),
                    RawMessage.deleted_at.is_(None),
                )
                .values(deleted_at=now_utc())
                .returning(RawMessage.id)
            )
            affected = list(result.scalars())
            await session.commit()

        for raw_message_id in affected:
            await publish(
                self._redis,
                STREAM_RAW,
                {"raw_message_id": raw_message_id, "reason": "deleted"},
            )

        if affected:
            log.info("collector.messages_deleted", source_id=source_id, count=len(affected))
        return len(affected)

    # -- internals ----------------------------------------------------------

    async def _store_photos(self, source_id: int, message: IncomingMessage) -> list[dict[str, Any]]:
        """Download up to ``MAX_PHOTOS_PER_POST`` photos and describe every attachment.

        A photo that fails to download is still recorded, without an ``s3_key``,
        so the post is not silently reduced to "no media".
        """
        described: list[dict[str, Any]] = []
        photo_index = 0

        for item in message.media:
            if not item.is_photo:
                described.append(_describe(item))
                continue

            if photo_index >= MAX_PHOTOS_PER_POST:
                described.append(_describe(item, skipped="limit"))
                continue

            data = await self._gateway.download_photo(message.chat_id, item.message_id)
            if data is None:
                described.append(_describe(item, skipped="too_large_or_missing"))
                photo_index += 1
                continue

            key = raw_key(source_id, message.message_id, photo_index)
            await self._photos.put(key, data)
            described.append(_describe(item, s3_key=key, index=photo_index))
            photo_index += 1

        return described

    async def _upsert(
        self,
        session: AsyncSession,
        source_id: int,
        message: IncomingMessage,
        media: list[dict[str, Any]],
    ) -> tuple[int, bool]:
        """Insert or update the row. Returns ``(id, changed)``.

        ``changed`` is False when an identical message arrives again — a
        redelivery or a backfill overlapping live ingestion — and the parser
        should not be woken for it.
        """
        existing = await session.execute(
            select(RawMessage.id, RawMessage.text, RawMessage.edited_at).where(
                RawMessage.source_id == source_id,
                RawMessage.tg_message_id == message.message_id,
            )
        )
        row = existing.first()
        if row is not None and row.text == message.text and row.edited_at == message.edited_at:
            return int(row.id), False

        statement = (
            insert(RawMessage)
            .values(
                source_id=source_id,
                tg_message_id=message.message_id,
                grouped_id=message.grouped_id,
                posted_at=message.posted_at,
                edited_at=message.edited_at,
                text=message.text,
                media=media,
                raw=message.raw,
                status=RawMessageStatus.PENDING,
            )
            .on_conflict_do_update(
                constraint="uq_raw_messages_source_message",
                set_={
                    "text": message.text,
                    "edited_at": message.edited_at,
                    "media": media,
                    "raw": message.raw,
                    # An edit means the parser must look again (SPEC 4.3).
                    "status": RawMessageStatus.PENDING,
                    "updated_at": now_utc(),
                },
            )
            .returning(RawMessage.id)
        )
        raw_message_id = (await session.execute(statement)).scalar_one()
        return int(raw_message_id), True


def _describe(
    item: IncomingMedia,
    *,
    s3_key: str | None = None,
    index: int | None = None,
    skipped: str | None = None,
) -> dict[str, Any]:
    """One entry of ``raw_messages.media``."""
    described: dict[str, Any] = {
        "kind": item.kind,
        "message_id": item.message_id,
        "size_bytes": item.size_bytes,
        "width": item.width,
        "height": item.height,
    }
    if s3_key is not None:
        described["s3_key"] = s3_key
    if index is not None:
        described["index"] = index
    if skipped is not None:
        described["skipped"] = skipped
    return described
