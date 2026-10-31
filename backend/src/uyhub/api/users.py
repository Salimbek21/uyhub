"""Recording that a user is active (SPEC 9.1).

The spec asks for an upsert on every request, throttled. Throttling is not
only about write load: `last_active_at` is a behavioural record, and writing it
on every scroll of the feed would build a far more detailed picture of someone
than the product needs.

Note what is *not* stored. ``initData`` carries a first name, a last name,
sometimes a username and a photo URL; the ``users`` table has a Telegram id, a
language and two flags. There is nowhere for the rest to go, by design.
"""

from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.api.auth import TelegramUser
from uyhub.core.clock import now_utc
from uyhub.core.logging import get_logger
from uyhub.models.enums import Language
from uyhub.models.user import User

log = get_logger(__name__)

TOUCH_INTERVAL_SECONDS = 10 * 60
"""How often one user's row may be rewritten. Ten minutes is far below any
session length that matters for "active users" and far above the rate at which
a person can open screens."""


def language_of(user: TelegramUser) -> Language:
    """Telegram's language code, narrowed to the two languages we ship.

    Russian is the only non-default we can honour; everything else — including
    English and the Cyrillic Uzbek locale — falls back to Uzbek Latin, which
    is the product's default (SPEC 10).
    """
    code = (user.language_code or "").lower()
    return Language.RU if code.startswith("ru") else Language.UZ


async def touch_user(session: AsyncSession, redis: Redis, user: TelegramUser) -> None:
    """Upsert the user and mark them active, at most once per interval."""
    if not await _should_touch(redis, user.tg_user_id):
        return

    statement = (
        insert(User)
        .values(
            tg_user_id=user.tg_user_id,
            lang=language_of(user),
            last_active_at=now_utc(),
        )
        # The language is not overwritten: a user who switched to Russian in
        # our own settings should not be switched back because their Telegram
        # client reports something else.
        .on_conflict_do_update(
            index_elements=[User.tg_user_id],
            set_={"last_active_at": now_utc()},
        )
    )
    await session.execute(statement)
    await session.commit()


async def _should_touch(redis: Redis, tg_user_id: int) -> bool:
    """A Redis key that expires is the throttle. Returns True when it was set.

    If Redis is unreachable we skip the write rather than fall back to writing
    every time: the row is a convenience, and a database write storm is the
    failure mode worth avoiding while Redis is already down.
    """
    try:
        key = f"user:touched:{tg_user_id}"
        return bool(await redis.set(key, "1", ex=TOUCH_INTERVAL_SECONDS, nx=True))
    except RedisError:
        log.warning("api.touch_throttle_unavailable", exc_info=True)
        return False


async def user_id_for(session: AsyncSession, tg_user_id: int) -> int | None:
    """Our own primary key for a Telegram id, once the row exists."""
    return (
        await session.execute(select(User.id).where(User.tg_user_id == tg_user_id))
    ).scalar_one_or_none()
