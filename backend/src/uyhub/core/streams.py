"""Redis Streams: the pipeline bus (SPEC section 2.3).

Delivery is at-least-once, so every consumer must be idempotent — keyed by
``raw_message_id`` for ``stream:raw`` and by ``listing_id`` + ``version`` for
``stream:listings``. Nothing here tries to make delivery exactly-once; that
guarantee belongs to the consumer's own write, not to the queue.

A message that fails ``MAX_DELIVERIES`` times is moved to ``stream:dead`` rather
than redelivered forever. ``uyhub streams replay-dead`` puts it back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from uyhub.core.logging import get_logger

log = get_logger(__name__)

STREAM_RAW: Final = "stream:raw"
"""Collector → parser. Fields: ``raw_message_id``, ``reason`` (new|edited|backfill)."""

STREAM_LISTINGS: Final = "stream:listings"
"""Parser → bot and poster. Fields: ``listing_id``, ``event``, ``version``."""

STREAM_DEAD: Final = "stream:dead"
"""Messages that exhausted their retries. Inspected and replayed by an admin."""

MAX_STREAM_LENGTH: Final = 100_000
"""Approximate cap per stream. ``MAXLEN ~`` trims cheaply at node boundaries."""

MAX_DELIVERIES: Final = 5
"""Attempts before a message is dead-lettered (SPEC 2.3)."""

STALE_MESSAGE_MS: Final = 5 * 60 * 1000
"""How long a pending message may sit with a dead consumer before it is reclaimed."""


@dataclass(frozen=True, slots=True)
class StreamMessage:
    """One entry read from a stream."""

    id: str
    fields: dict[str, str]

    @property
    def delivery_count(self) -> int:
        """How many times this entry has been delivered, when known."""
        return int(self.fields.get("_deliveries", "1"))


async def publish(
    client: Redis,
    stream: str,
    fields: dict[str, Any],
) -> str:
    """Append an entry and trim the stream. Returns the entry id."""
    entry_id: str = await client.xadd(
        stream,
        {key: str(value) for key, value in fields.items()},
        maxlen=MAX_STREAM_LENGTH,
        approximate=True,
    )
    return entry_id


async def ensure_group(client: Redis, stream: str, group: str) -> None:
    """Create the consumer group, and the stream with it. Idempotent.

    ``mkstream`` matters: consumers usually start before the first producer, and
    ``XGROUP CREATE`` on a missing stream is an error rather than a no-op.
    """
    try:
        await client.xgroup_create(stream, group, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def read_group(
    client: Redis,
    stream: str,
    group: str,
    consumer: str,
    *,
    count: int = 10,
    block_ms: int = 5_000,
) -> list[StreamMessage]:
    """Block for up to ``block_ms`` waiting for new entries for this consumer."""
    response = await client.xreadgroup(
        groupname=group,
        consumername=consumer,
        streams={stream: ">"},
        count=count,
        block=block_ms,
    )
    if not response:
        return []
    return [
        StreamMessage(id=entry_id, fields=fields)
        for _, entries in response
        for entry_id, fields in entries
    ]


async def claim_stale(
    client: Redis,
    stream: str,
    group: str,
    consumer: str,
    *,
    count: int = 10,
) -> list[StreamMessage]:
    """Take over entries abandoned by a consumer that died mid-work.

    Without this, a pod that is killed between ``XREADGROUP`` and ``XACK`` leaves
    its messages pending forever.
    """
    _cursor, entries, _deleted = await client.xautoclaim(
        name=stream,
        groupname=group,
        consumername=consumer,
        min_idle_time=STALE_MESSAGE_MS,
        count=count,
    )
    return [StreamMessage(id=entry_id, fields=fields) for entry_id, fields in entries]


async def ack(client: Redis, stream: str, group: str, *entry_ids: str) -> None:
    """Mark entries as handled so they stop being redelivered."""
    if entry_ids:
        await client.xack(stream, group, *entry_ids)


async def dead_letter(
    client: Redis,
    stream: str,
    group: str,
    message: StreamMessage,
    *,
    error: str,
) -> None:
    """Move a message that will never succeed to ``stream:dead`` and ack it."""
    await publish(
        client,
        STREAM_DEAD,
        {**message.fields, "_origin_stream": stream, "_origin_id": message.id, "_error": error},
    )
    await ack(client, stream, group, message.id)
    log.warning(
        "stream.dead_lettered",
        stream=stream,
        entry_id=message.id,
        error=error,
    )


async def pending_count(client: Redis, stream: str, group: str) -> int:
    """Entries delivered but not yet acked. The lag signal alerts watch."""
    try:
        summary: dict[str, Any] = await client.xpending(stream, group)
    except ResponseError:
        return 0
    return int(summary.get("pending", 0))
