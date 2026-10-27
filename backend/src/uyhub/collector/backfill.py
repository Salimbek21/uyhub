"""Gap recovery and history backfill (SPEC 4.4).

Both are the same operation — "give me everything after message N" — so they
share one code path. It runs on startup, after every reconnect, and once more
right after a source is joined.
"""

from __future__ import annotations

from datetime import datetime

from uyhub.collector.gateway import TelegramGateway
from uyhub.collector.ingest import REASON_BACKFILL, MessageIngestor
from uyhub.core.logging import get_logger

log = get_logger(__name__)

MAX_BACKFILL_MESSAGES = 1_000
"""Ceiling per source per pass, so a long-dormant source cannot stall startup."""


async def backfill_source(
    gateway: TelegramGateway,
    ingestor: MessageIngestor,
    *,
    source_id: int,
    chat_id: int,
    min_id: int = 0,
    since: datetime | None = None,
    limit: int | None = MAX_BACKFILL_MESSAGES,
) -> int:
    """Ingest missed messages. Returns how many were stored.

    Two callers, two shapes. Gap recovery knows the last message it saw and walks
    forward from it. A first join has no such mark, so it passes ``since`` and
    takes the last ``COLLECTOR_BACKFILL_DAYS`` days instead — walking forward
    from zero would mean the channel's entire history.

    Ingestion is idempotent, so an overlap with live handlers is harmless: the
    second write finds the row unchanged and does not re-queue it.
    """
    if since is not None:
        messages = await gateway.fetch_recent(chat_id, since=since, limit=limit)
    else:
        messages = await gateway.fetch_since(chat_id, min_id=min_id, limit=limit)
    stored = 0
    for message in messages:
        raw_message_id = await ingestor.ingest(source_id, message, reason=REASON_BACKFILL)
        if raw_message_id is not None:
            stored += 1

    log.info(
        "collector.backfill_done",
        source_id=source_id,
        from_message_id=min_id,
        since=since.isoformat() if since else None,
        fetched=len(messages),
        stored=stored,
    )
    return stored
