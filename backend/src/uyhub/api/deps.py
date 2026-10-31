"""Request-scoped dependencies.

Authentication lives here rather than in a middleware because FastAPI's
dependency system is what makes "this endpoint needs a user" visible in the
endpoint's own signature, and `/healthz` needs to stay reachable without one.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.api.auth import InitDataError, TelegramUser, parse_authorization_header, verify_init_data
from uyhub.api.users import touch_user
from uyhub.core.config import Settings, get_settings
from uyhub.core.db import get_sessionmaker
from uyhub.core.logging import get_logger
from uyhub.core.ratelimit import RateLimiter

log = get_logger(__name__)

INSECURE_USER = TelegramUser(
    tg_user_id=0,
    username="insecure-dev",
    language_code="uz",
    is_premium=False,
)
"""Who a request is attributed to when `API_ALLOW_INSECURE_AUTH` is on.

A fixed, obviously-named id, so anything it touches is recognisable as having
come in without a signature. Production refuses to start with that flag set
(DECISIONS 4.5)."""


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


async def db_session(settings: SettingsDep) -> AsyncIterator[AsyncSession]:
    """One session per request, rolled back if the handler raises."""
    async with get_sessionmaker(settings)() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(db_session)]


def redis_client(request: Request) -> Redis:
    """The connection pool created at startup, not a new one per request."""
    return request.app.state.redis  # type: ignore[no-any-return]


RedisDep = Annotated[Redis, Depends(redis_client)]


def rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter  # type: ignore[no-any-return]


async def enforce_rate_limit(
    request: Request,
    limiter: Annotated[RateLimiter, Depends(rate_limiter)],
) -> None:
    """Per-IP limiting, applied before the caller is identified (SPEC 9.3).

    Per-IP rather than per-user because an unauthenticated flood never gets as
    far as having a user, and that is the flood worth stopping cheaply.
    """
    client = request.client.host if request.client else "unknown"
    result = await limiter.check("ip", client, now=time.time())
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limited",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


async def current_user(
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(rate_limiter)],
    authorization: Annotated[str | None, Header()] = None,
) -> TelegramUser:
    """Who is calling, proven by Telegram's signature (SPEC 9.1)."""
    if settings.api_allow_insecure_auth and authorization is None:
        return INSECURE_USER

    try:
        init_data = parse_authorization_header(authorization)
        user = verify_init_data(init_data, bot_token=settings.bot_token.get_secret_value())
    except InitDataError as exc:
        # The reason is safe to log — it names which check failed, not what
        # the caller sent. `initData` itself carries a display name and is
        # never written anywhere.
        log.info("api.auth_rejected", reason=exc.reason)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.reason,
            headers={"WWW-Authenticate": "tma"},
        ) from exc

    result = await limiter.check("user", str(user.tg_user_id), now=time.time())
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limited",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )

    await touch_user(session, redis, user)
    return user


CurrentUser = Annotated[TelegramUser, Depends(current_user)]
