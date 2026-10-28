"""Re-running an improved parser over messages already collected (SPEC 6.4).

Nothing is re-extracted here. Messages are published back onto ``stream:raw``
and the ordinary worker handles them, so there is exactly one code path that
writes ``raw_messages.extracted`` and no second implementation to drift.

OPEN_QUESTIONS A7 applies: retention eventually purges ``raw_messages.text``,
and a message with no text cannot be reparsed. Those are skipped rather than
re-queued to fail.
"""

from __future__ import annotations

from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.core.logging import get_logger
from uyhub.core.streams import STREAM_RAW, publish
from uyhub.models.telegram import RawMessage

log = get_logger(__name__)

REASON = "reparse"


async def requeue(
    session: AsyncSession,
    redis: Redis,
    *,
    since: datetime | None = None,
    version_below: int | None = None,
    limit: int = 1000,
) -> int:
    """Publish matching messages back onto ``stream:raw``. Returns the count."""
    stmt = (
        select(RawMessage.id)
        .where(RawMessage.text.is_not(None), RawMessage.deleted_at.is_(None))
        .order_by(RawMessage.id)
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(RawMessage.posted_at >= since)
    if version_below is not None:
        # A message never parsed at all also qualifies: it has no version yet.
        stmt = stmt.where(
            or_(
                RawMessage.parser_version.is_(None),
                RawMessage.parser_version < version_below,
            )
        )

    ids = list((await session.execute(stmt)).scalars())
    for raw_message_id in ids:
        await publish(redis, STREAM_RAW, {"raw_message_id": raw_message_id, "reason": REASON})

    log.info(
        "parser.reparse_queued",
        count=len(ids),
        since=since.isoformat() if since else None,
        version_below=version_below,
    )
    return len(ids)
