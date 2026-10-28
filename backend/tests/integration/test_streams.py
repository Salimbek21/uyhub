"""Redis Streams helpers (SPEC 2.3).

These run against real Redis because the behaviour that matters — what a
consumer group redelivers after a crash, what ``XAUTOCLAIM`` hands over — is
exactly what a mock would get wrong.
"""

from __future__ import annotations

import time

import pytest
from redis.asyncio import Redis

from uyhub.core.streams import (
    MAX_STREAM_LENGTH,
    STREAM_DEAD,
    StreamMessage,
    ack,
    claim_stale,
    dead_letter,
    ensure_group,
    pending_count,
    publish,
    read_group,
)

pytestmark = pytest.mark.integration

STREAM = "test:stream"
GROUP = "test-group"


async def test_publish_returns_an_entry_id(redis_client: Redis) -> None:
    entry_id = await publish(redis_client, STREAM, {"raw_message_id": 42})

    assert "-" in entry_id
    entries = await redis_client.xrange(STREAM)
    assert entries[0][1] == {"raw_message_id": "42"}


async def test_values_are_stringified(redis_client: Redis) -> None:
    """Redis stores strings; publishing an int must not blow up at the driver."""
    await publish(redis_client, STREAM, {"listing_id": 1, "version": 3, "event": "created"})

    _entry_id, fields = (await redis_client.xrange(STREAM))[0]
    assert fields == {"listing_id": "1", "version": "3", "event": "created"}


async def test_streams_are_trimmed(redis_client: Redis) -> None:
    await publish(redis_client, STREAM, {"n": 1})

    info = await redis_client.xinfo_stream(STREAM)
    assert info["length"] <= MAX_STREAM_LENGTH


async def test_ensure_group_is_idempotent_and_creates_the_stream(
    redis_client: Redis,
) -> None:
    """Consumers normally start before any producer has written anything."""
    await ensure_group(redis_client, STREAM, GROUP)
    await ensure_group(redis_client, STREAM, GROUP)

    groups = await redis_client.xinfo_groups(STREAM)
    assert [group["name"] for group in groups] == [GROUP]


async def test_read_group_delivers_then_stops(redis_client: Redis) -> None:
    await ensure_group(redis_client, STREAM, GROUP)
    await publish(redis_client, STREAM, {"raw_message_id": 1})

    first = await read_group(redis_client, STREAM, GROUP, "worker-1", block_ms=50)
    second = await read_group(redis_client, STREAM, GROUP, "worker-1", block_ms=50)

    assert [message.fields["raw_message_id"] for message in first] == ["1"]
    assert second == []


async def test_unacked_messages_stay_pending(redis_client: Redis) -> None:
    await ensure_group(redis_client, STREAM, GROUP)
    await publish(redis_client, STREAM, {"raw_message_id": 1})
    messages = await read_group(redis_client, STREAM, GROUP, "worker-1", block_ms=50)

    assert await pending_count(redis_client, STREAM, GROUP) == 1

    await ack(redis_client, STREAM, GROUP, *(message.id for message in messages))

    assert await pending_count(redis_client, STREAM, GROUP) == 0


async def test_pending_count_of_an_unknown_group_is_zero(redis_client: Redis) -> None:
    assert await pending_count(redis_client, "test:missing", GROUP) == 0


async def test_ack_without_ids_is_a_no_op(redis_client: Redis) -> None:
    await ensure_group(redis_client, STREAM, GROUP)
    await ack(redis_client, STREAM, GROUP)


async def test_a_dead_consumers_work_can_be_claimed(redis_client: Redis) -> None:
    """A pod killed between read and ack must not strand its messages."""
    await ensure_group(redis_client, STREAM, GROUP)
    await publish(redis_client, STREAM, {"raw_message_id": 7})
    await read_group(redis_client, STREAM, GROUP, "worker-dead", block_ms=50)

    # min_idle_time of 0 simulates "long enough ago".
    _cursor, entries, _ = await redis_client.xautoclaim(
        name=STREAM, groupname=GROUP, consumername="worker-alive", min_idle_time=0
    )

    assert [fields["raw_message_id"] for _entry_id, fields in entries] == ["7"]


async def test_claim_stale_leaves_fresh_messages_alone(redis_client: Redis) -> None:
    await ensure_group(redis_client, STREAM, GROUP)
    await publish(redis_client, STREAM, {"raw_message_id": 8})
    await read_group(redis_client, STREAM, GROUP, "worker-1", block_ms=50)

    claimed = await claim_stale(redis_client, STREAM, GROUP, "worker-2")

    assert claimed == []


async def test_dead_letter_moves_and_acks(redis_client: Redis) -> None:
    await ensure_group(redis_client, STREAM, GROUP)
    await publish(redis_client, STREAM, {"raw_message_id": 9})
    (message,) = await read_group(redis_client, STREAM, GROUP, "worker-1", block_ms=50)

    await dead_letter(redis_client, STREAM, GROUP, message, error="ValueError")

    assert await pending_count(redis_client, STREAM, GROUP) == 0
    _entry_id, fields = (await redis_client.xrange(STREAM_DEAD))[0]
    assert fields["raw_message_id"] == "9"
    assert fields["_origin_stream"] == STREAM
    assert fields["_error"] == "ValueError"


async def test_blocking_on_an_empty_stream_does_not_break_the_connection(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found by running the parser against a real queue that had emptied.

    A blocking XREADGROUP holds the socket open with nothing on it, which the
    client cannot tell apart from a hung connection. With the block and the
    socket timeout both at five seconds, every idle read tore the connection
    down. The block is now capped below the socket timeout — this asserts the
    relationship rather than the numbers.
    """
    from uyhub.core import redis as redis_module

    assert redis_module.SOCKET_TIMEOUT_SECONDS > redis_module.MAX_BLOCK_SECONDS

    # The cap is lowered so the test waits half a second rather than ten; what
    # is under test is that the request is clamped at all.
    monkeypatch.setattr(redis_module, "MAX_BLOCK_SECONDS", 0.5)

    await ensure_group(redis_client, STREAM, GROUP)
    started = time.monotonic()
    messages = await read_group(redis_client, STREAM, GROUP, "worker-1", block_ms=60_000)
    elapsed = time.monotonic() - started

    assert messages == []
    assert elapsed < 5, f"the 60s block was not clamped (took {elapsed:.1f}s)"


def test_delivery_count_defaults_to_one() -> None:
    """XREADGROUP does not report it; a first delivery is 1 by definition."""
    assert StreamMessage(id="1-0", fields={}).deliveries == 1
    assert StreamMessage(id="1-0", fields={}, deliveries=3).deliveries == 3
