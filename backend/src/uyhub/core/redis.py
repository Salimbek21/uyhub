"""Async Redis access.

Redis is both a cache and the message bus: SPEC section 2.3 runs the pipeline over
Redis Streams. Phase 0 provides the client and a readiness probe only.
"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from uyhub.core.config import Settings, get_settings
from uyhub.core.errors import DependencyUnavailableError

HEALTHCHECK_TIMEOUT_SECONDS = 3.0

MAX_BLOCK_SECONDS = 10.0
"""Longest a consumer may ask Redis to block waiting for work.

``XREADGROUP ... BLOCK`` holds the socket open with nothing on it, which looks
exactly like a hung connection to the client. The socket timeout must therefore
be longer than any intended block, or an idle queue tears the connection down
every few seconds. :func:`uyhub.core.streams.read_group` caps its block at this
value; the socket timeout below leaves headroom on top of it.
"""

SOCKET_TIMEOUT_SECONDS = MAX_BLOCK_SECONDS + 5.0

_client: Redis | None = None


def get_redis(settings: Settings | None = None) -> Redis:
    """Return the process-wide Redis client, creating it on first use."""
    global _client
    if _client is None:
        cfg = settings or get_settings()
        _client = Redis.from_url(
            cfg.redis_url,
            decode_responses=True,
            socket_timeout=SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=5.0,
            health_check_interval=30,
        )
    return _client


async def check_redis() -> None:
    """Raise :class:`DependencyUnavailableError` if Redis is not reachable."""
    try:
        async with asyncio.timeout(HEALTHCHECK_TIMEOUT_SECONDS):
            await get_redis().ping()
    except TimeoutError as exc:
        raise DependencyUnavailableError("redis", "timeout") from exc
    except Exception as exc:
        raise DependencyUnavailableError("redis", type(exc).__name__) from exc


async def close_redis() -> None:
    """Close the client. Called on shutdown and between tests."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
