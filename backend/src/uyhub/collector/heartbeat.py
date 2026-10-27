"""Collector liveness signal (SPEC 4.4).

A key with a TTL shorter than the write interval means "no key" unambiguously
reads as "this account is not collecting", which is what ``/readyz`` and the
alerting in SPEC 14 need. A boolean flag written by the process itself could not
distinguish a crash from a clean exit.
"""

from __future__ import annotations

import asyncio
import contextlib

from redis.asyncio import Redis

from uyhub.core.logging import get_logger

log = get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_TTL_SECONDS = 90


def heartbeat_key(account_id: int) -> str:
    return f"collector:heartbeat:{account_id}"


async def write_heartbeat(redis: Redis, account_id: int) -> None:
    await redis.set(heartbeat_key(account_id), "1", ex=HEARTBEAT_TTL_SECONDS)


async def is_alive(redis: Redis, account_id: int) -> bool:
    return bool(await redis.exists(heartbeat_key(account_id)))


async def run_heartbeat(redis: Redis, account_id: int, stop: asyncio.Event) -> None:
    """Refresh the key until ``stop`` is set."""
    while not stop.is_set():
        try:
            await write_heartbeat(redis, account_id)
        except Exception as exc:
            log.warning("collector.heartbeat_failed", error=type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)
