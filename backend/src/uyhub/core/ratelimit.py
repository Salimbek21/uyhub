"""Token-bucket rate limiting on Redis (SPEC 9.3).

A bucket holds ``capacity`` tokens and refills at a steady rate. A request
takes one. This shape is chosen over a fixed window because a window lets a
caller spend its whole minute's budget in the first second and then again in
the first second of the next, which is exactly the burst a window is meant to
prevent.

The whole read-modify-write runs as one Lua script so it is atomic: two
requests arriving together cannot both read the same token count and both
decide they may spend it.
"""

from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from uyhub.core.logging import get_logger

log = get_logger(__name__)

# KEYS[1] bucket, ARGV: capacity, refill-per-second, now (seconds, float), cost
_SCRIPT = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'at')
local tokens = tonumber(bucket[1])
local at = tonumber(bucket[2])

if tokens == nil or at == nil then
  tokens = capacity
  at = now
end

tokens = math.min(capacity, tokens + (now - at) * rate)

local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'at', now)
-- Idle buckets are full buckets, so there is nothing to remember about one
-- that has had time to refill completely.
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) + 1)

local retry = 0
if allowed == 0 then
  retry = math.ceil((cost - tokens) / rate)
end
return {allowed, retry}
"""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


class RateLimiter:
    """Shared limiter. One instance per process; buckets live in Redis."""

    def __init__(self, redis: Redis, *, per_minute: int, burst: int) -> None:
        self._redis = redis
        self._rate = per_minute / 60.0
        self._capacity = float(burst)
        self._script = redis.register_script(_SCRIPT)

    async def check(self, scope: str, identity: str, *, now: float) -> RateLimitResult:
        """Spend one token for ``identity`` within ``scope``.

        ``now`` is passed in rather than read here so the caller controls the
        clock — Redis's own time would be a second network round trip, and
        tests need to be able to move it.
        """
        try:
            raw = await self._script(
                keys=[f"rl:{scope}:{identity}"],
                args=[self._capacity, self._rate, now, 1],
            )
        except RedisError:
            # A limiter that fails closed would take the API down with Redis,
            # which is a worse outcome than briefly not limiting. Readiness
            # already reports Redis being gone.
            log.warning("ratelimit.unavailable", scope=scope, exc_info=True)
            return RateLimitResult(allowed=True, retry_after_seconds=0)

        allowed, retry_after = int(raw[0]), int(raw[1])
        if allowed == 1:
            return RateLimitResult(allowed=True, retry_after_seconds=0)
        return RateLimitResult(allowed=False, retry_after_seconds=max(retry_after, 1))
