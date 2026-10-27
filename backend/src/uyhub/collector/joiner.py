"""The join worker (SPEC 4.2).

Joining chats is the single riskiest thing the userbot does — it is what gets
accounts banned — so this worker is deliberately slow: at most
``COLLECTOR_MAX_JOINS_PER_DAY`` per account, with ten to forty minutes of
randomised quiet in between, lowest ``priority`` number first.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uyhub.collector import accounts, sources
from uyhub.collector.backfill import backfill_source
from uyhub.collector.gateway import TelegramGateway
from uyhub.collector.ingest import MessageIngestor
from uyhub.core.clock import now_utc
from uyhub.core.config import Settings
from uyhub.core.logging import get_logger
from uyhub.models.enums import SourceStatus
from uyhub.models.telegram import Source

log = get_logger(__name__)

MIN_JOIN_GAP_SECONDS = 10 * 60
MAX_JOIN_GAP_SECONDS = 40 * 60
IDLE_POLL_SECONDS = 300
"""How long to wait before looking for new pending sources when there are none."""


class JoinWorker:
    """Promotes ``pending_join`` sources to ``active``, slowly."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: TelegramGateway,
        ingestor: MessageIngestor,
        settings: Settings,
        account_id: int,
    ) -> None:
        self._session_factory = session_factory
        self._gateway = gateway
        self._ingestor = ingestor
        self._settings = settings
        self._account_id = account_id

    async def run(self, stop: asyncio.Event) -> None:
        """Join one source at a time until stopped."""
        while not stop.is_set():
            try:
                joined = await self.join_next()
            except Exception as exc:
                log.exception("collector.join_worker_error", error=type(exc).__name__)
                joined = False

            delay = self._next_delay() if joined else IDLE_POLL_SECONDS
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)

    async def join_next(self) -> bool:
        """Join at most one source. Returns True when one was actually joined."""
        async with self._session_factory() as session:
            source = await sources.next_pending(session)
            if source is None:
                await session.rollback()
                return False

            has_budget = await accounts.claim_join_slot(
                session,
                self._account_id,
                max_per_day=self._settings.collector_max_joins_per_day,
            )
            if not has_budget:
                await session.rollback()
                log.info("collector.join_budget_exhausted", account_id=self._account_id)
                return False

            source_id = source.id
            ref = _telegram_ref(source)
            await session.commit()

        if ref is None:
            await self._fail(source_id, "source has neither username nor invite link")
            return False

        return await self._join(source_id, ref)

    async def _join(self, source_id: int, ref: str) -> bool:
        from telethon.errors import FloodWaitError, RPCError

        try:
            chat = await self._gateway.join(ref)
        except FloodWaitError as exc:
            await self._flood_wait(exc.seconds)
            return False
        except RPCError as exc:
            await self._fail(source_id, type(exc).__name__)
            return False

        async with self._session_factory() as session:
            await sources.mark_joined(session, source_id, chat)
            await session.commit()

        await backfill_source(
            self._gateway,
            self._ingestor,
            source_id=source_id,
            chat_id=chat.chat_id,
            since=now_utc() - timedelta(days=self._settings.collector_backfill_days),
        )

        async with self._session_factory() as session:
            await sources.set_status(session, source_id, SourceStatus.ACTIVE)
            await session.commit()

        log.info("collector.source_joined", source_id=source_id, chat_id=chat.chat_id)
        return True

    async def _fail(self, source_id: int, reason: str) -> None:
        async with self._session_factory() as session:
            await sources.mark_error(session, source_id, reason)
            await session.commit()
        log.warning("collector.join_failed", source_id=source_id, reason=reason)

    async def _flood_wait(self, seconds: int) -> None:
        until = now_utc() + timedelta(seconds=seconds)
        async with self._session_factory() as session:
            await accounts.start_flood_wait(session, self._account_id, until)
            await session.commit()

    def _next_delay(self) -> float:
        # Not security-sensitive: this is jitter to look less like a script.
        return random.uniform(MIN_JOIN_GAP_SECONDS, MAX_JOIN_GAP_SECONDS)  # noqa: S311


def _telegram_ref(source: Source) -> str | None:
    if source.username:
        return f"@{source.username}"
    return source.invite_link
