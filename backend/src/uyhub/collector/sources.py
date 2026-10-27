"""Source management (SPEC 4.2).

Sources are added by reference — ``@username``, a ``t.me`` link or a private
invite link — and start life as ``pending_join``. The join worker promotes them;
nothing here talks to Telegram.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.collector.types import ResolvedChat
from uyhub.core.clock import now_utc
from uyhub.core.logging import get_logger
from uyhub.models.enums import SourceKind, SourceStatus
from uyhub.models.telegram import Source

log = get_logger(__name__)

DEFAULT_PRIORITY = 100
"""Sources added without an explicit priority join after the curated first batch."""

_USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{3,31})$")
_PUBLIC_LINK_RE = re.compile(r"(?:https?://)?t\.me/(?!joinchat/|\+)([A-Za-z][A-Za-z0-9_]{3,31})")
_INVITE_RE = re.compile(r"(?:https?://)?t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)")


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A parsed source reference. Exactly one of the two fields is set."""

    username: str | None = None
    invite_link: str | None = None

    @property
    def as_telegram_ref(self) -> str:
        """What the gateway should be asked to resolve or join."""
        if self.username is not None:
            return f"@{self.username}"
        assert self.invite_link is not None
        return self.invite_link


def parse_ref(ref: str) -> SourceRef:
    """Turn operator input into a :class:`SourceRef`.

    Raises ``ValueError`` on anything we cannot act on, so a typo fails at the
    CLI rather than silently creating a source that can never be joined.
    """
    cleaned = ref.strip()

    invite = _INVITE_RE.search(cleaned)
    if invite is not None:
        return SourceRef(invite_link=f"https://t.me/+{invite.group(1)}")

    public = _PUBLIC_LINK_RE.search(cleaned)
    if public is not None:
        return SourceRef(username=public.group(1))

    username = _USERNAME_RE.match(cleaned)
    if username is not None:
        return SourceRef(username=username.group(1))

    msg = f"not a Telegram username, t.me link or invite link: {ref!r}"
    raise ValueError(msg)


async def add_source(
    session: AsyncSession,
    ref: str,
    *,
    priority: int = DEFAULT_PRIORITY,
    city: str = "tashkent",
    account_id: int | None = None,
) -> Source:
    """Register a source, or return the existing row if it is already known."""
    parsed = parse_ref(ref)

    existing = await _find_by_ref(session, parsed)
    if existing is not None:
        return existing

    source = Source(
        username=parsed.username,
        invite_link=parsed.invite_link,
        city=city,
        priority=priority,
        account_id=account_id,
        status=SourceStatus.PENDING_JOIN,
    )
    session.add(source)
    await session.flush()
    log.info("source.added", source_id=source.id, priority=priority)
    return source


async def _find_by_ref(session: AsyncSession, parsed: SourceRef) -> Source | None:
    if parsed.username is not None:
        stmt = select(Source).where(Source.username == parsed.username)
    else:
        stmt = select(Source).where(Source.invite_link == parsed.invite_link)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_sources(
    session: AsyncSession, *, status: SourceStatus | None = None
) -> list[Source]:
    stmt = select(Source).order_by(Source.priority, Source.id)
    if status is not None:
        stmt = stmt.where(Source.status == status)
    return list((await session.execute(stmt)).scalars())


async def get_by_chat_id(session: AsyncSession, chat_id: int) -> Source | None:
    stmt = select(Source).where(Source.tg_chat_id == chat_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def active_chat_ids(session: AsyncSession) -> dict[int, int]:
    """``{tg_chat_id: source_id}`` for every active source.

    The collector keeps this in memory and refreshes it periodically, which is
    what lets a newly joined source start being read without a restart.
    """
    stmt = select(Source.tg_chat_id, Source.id).where(
        Source.status == SourceStatus.ACTIVE,
        Source.tg_chat_id.is_not(None),
    )
    rows = (await session.execute(stmt)).all()
    return {chat_id: source_id for chat_id, source_id in rows if chat_id is not None}


async def next_pending(session: AsyncSession) -> Source | None:
    """The next source to join: lowest priority number, then oldest."""
    stmt = (
        select(Source)
        .where(Source.status == SourceStatus.PENDING_JOIN)
        .order_by(Source.priority, Source.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_status(
    session: AsyncSession,
    source_id: int,
    status: SourceStatus,
    *,
    error_text: str | None = None,
) -> None:
    await session.execute(
        update(Source).where(Source.id == source_id).values(status=status, error_text=error_text)
    )
    log.info("source.status_changed", source_id=source_id, status=status.value)


async def mark_error(session: AsyncSession, source_id: int, error_text: str) -> None:
    """Park a source we can no longer read, with the reason an admin will see."""
    await set_status(session, source_id, SourceStatus.ERROR, error_text=error_text)


async def mark_joined(session: AsyncSession, source_id: int, chat: ResolvedChat) -> None:
    """Record a successful join.

    The source deliberately stays ``pending_join`` until backfill has finished,
    so a crash between the two retries the backfill rather than skipping it.
    """
    await session.execute(
        update(Source)
        .where(Source.id == source_id)
        .values(
            tg_chat_id=chat.chat_id,
            title=chat.title,
            username=chat.username,
            kind=SourceKind(chat.kind),
            joined_at=now_utc(),
            error_text=None,
        )
    )


async def record_message(
    session: AsyncSession,
    source_id: int,
    *,
    tg_message_id: int,
    posted_at: datetime,
) -> None:
    """Advance the high-water mark that gap recovery reads (SPEC 4.4).

    Guarded so an out-of-order backfill message cannot move the mark backwards.
    """
    await session.execute(
        update(Source)
        .where(
            Source.id == source_id,
            or_(Source.last_message_id.is_(None), Source.last_message_id < tg_message_id),
        )
        .values(last_message_id=tg_message_id, last_message_at=posted_at)
    )
    await session.execute(
        update(Source)
        .where(Source.id == source_id)
        .values(messages_total=Source.messages_total + 1)
    )
