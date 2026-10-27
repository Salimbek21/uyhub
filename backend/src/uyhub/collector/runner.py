"""The collector service loop.

Wiring only: it owns the gateway, the set of chats we are allowed to read, the
background workers, and shutdown. The behaviour being wired lives in the modules
next to this one so that it can be tested without a service at all.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uyhub.collector import accounts, sources
from uyhub.collector.backfill import backfill_source
from uyhub.collector.gateway import TelegramGateway
from uyhub.collector.heartbeat import run_heartbeat
from uyhub.collector.ingest import REASON_EDITED, REASON_NEW, MessageIngestor
from uyhub.collector.joiner import JoinWorker
from uyhub.collector.types import DeletedMessages, IncomingMessage
from uyhub.core.clock import now_utc
from uyhub.core.config import Settings
from uyhub.core.logging import get_logger
from uyhub.service import SHUTDOWN_GRACE_SECONDS, install_signal_handlers

log = get_logger(__name__)

SOURCES_CHANGED_CHANNEL = "sources:changed"
"""Published by the CLI when a source is added, paused or removed (SPEC 4.3)."""

REGISTRY_REFRESH_SECONDS = 60
"""Fallback refresh, so a missed pub/sub message costs a minute, not a restart."""

MAX_CONCURRENT_INGESTS = 8
"""Handlers must return quickly; the real work runs here, bounded (SPEC 4.3)."""

FLOOD_WAIT_ALERT_SECONDS = 3600
"""A wait longer than this is an incident, not a hiccup (SPEC 4.4)."""


class SourceRegistry:
    """The ``{chat_id: source_id}`` map the handlers filter on."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], redis: Redis) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._chat_ids: dict[int, int] = {}

    def source_for(self, chat_id: int | None) -> int | None:
        if chat_id is None:
            return None
        return self._chat_ids.get(chat_id)

    @property
    def chat_ids(self) -> dict[int, int]:
        return dict(self._chat_ids)

    async def refresh(self) -> None:
        async with self._session_factory() as session:
            self._chat_ids = await sources.active_chat_ids(session)

    async def run(self, stop: asyncio.Event) -> None:
        """Refresh on every pub/sub notification, and once a minute regardless."""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(SOURCES_CHANGED_CHANNEL)
        try:
            while not stop.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=REGISTRY_REFRESH_SECONDS
                )
                if stop.is_set():
                    break
                if message is not None:
                    log.info("collector.sources_changed")
                await self.refresh()
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(SOURCES_CHANGED_CHANNEL)
                await pubsub.aclose()  # type: ignore[no-untyped-call]


async def notify_sources_changed(redis: Redis) -> None:
    """Tell a running collector to reload its source set."""
    await redis.publish(SOURCES_CHANGED_CHANNEL, "1")


class Collector:
    """One Telethon account, its handlers, and its background workers."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        gateway: TelegramGateway,
        ingestor: MessageIngestor,
        settings: Settings,
        account_id: int,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._gateway = gateway
        self._ingestor = ingestor
        self._settings = settings
        self._account_id = account_id

        self.registry = SourceRegistry(session_factory, redis)
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_INGESTS)
        self._inflight: set[asyncio.Task[None]] = set()

    # -- handlers -----------------------------------------------------------

    def register_handlers(self) -> None:
        self._gateway.on_new_message(self._on_message(REASON_NEW))
        self._gateway.on_album(self._on_message(REASON_NEW))
        self._gateway.on_edited(self._on_message(REASON_EDITED))
        self._gateway.on_deleted(self._on_deleted)

    def _on_message(self, reason: str):  # type: ignore[no-untyped-def]
        async def handler(message: IncomingMessage) -> None:
            source_id = self.registry.source_for(message.chat_id)
            if source_id is None:
                return
            self._spawn(self._ingest(source_id, message, reason))

        return handler

    async def _on_deleted(self, deletion: DeletedMessages) -> None:
        source_id = self.registry.source_for(deletion.chat_id)
        if source_id is None:
            # Telegram omits the chat for private chats and small groups; there
            # is nothing to resolve against, so count it and move on (SPEC 4.3).
            log.info("collector.deletion_without_chat", count=len(deletion.message_ids))
            return
        self._spawn(self._ingestor.mark_deleted(deletion, source_id))

    def _spawn(self, coro) -> None:  # type: ignore[no-untyped-def]
        """Run background work without letting the task be garbage collected."""
        task = asyncio.create_task(self._guarded(coro))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _guarded(self, coro) -> None:  # type: ignore[no-untyped-def]
        from telethon.errors import FloodWaitError

        async with self._semaphore:
            try:
                await coro
            except FloodWaitError as exc:
                await self._handle_flood_wait(exc.seconds)
            except Exception as exc:
                log.exception("collector.ingest_failed", error=type(exc).__name__)

    async def _ingest(self, source_id: int, message: IncomingMessage, reason: str) -> None:
        await self._ingestor.ingest(source_id, message, reason=reason)

    async def _handle_flood_wait(self, seconds: int) -> None:
        until = now_utc() + timedelta(seconds=seconds)
        async with self._session_factory() as session:
            await accounts.start_flood_wait(session, self._account_id, until)
            await session.commit()
        if seconds >= FLOOD_WAIT_ALERT_SECONDS:
            log.error("collector.flood_wait_long", seconds=seconds)
        await asyncio.sleep(seconds)
        async with self._session_factory() as session:
            await accounts.clear_flood_wait(session, self._account_id)
            await session.commit()

    # -- lifecycle ----------------------------------------------------------

    async def recover_gaps(self) -> None:
        """Replay everything missed while the process was down (SPEC 4.4)."""
        async with self._session_factory() as session:
            active = await sources.list_sources(session, status=None)
            pairs = [
                (source.id, source.tg_chat_id, source.last_message_id or 0)
                for source in active
                if source.tg_chat_id is not None and source.status.value == "active"
            ]

        for source_id, chat_id, min_id in pairs:
            try:
                await backfill_source(
                    self._gateway,
                    self._ingestor,
                    source_id=source_id,
                    chat_id=chat_id,
                    min_id=min_id,
                )
            except Exception as exc:
                log.warning(
                    "collector.gap_recovery_failed",
                    source_id=source_id,
                    error=type(exc).__name__,
                )

    async def drain(self) -> None:
        """Let in-flight downloads finish, but not forever (SPEC 4.4)."""
        if not self._inflight:
            return
        log.info("collector.draining", tasks=len(self._inflight))
        pending = list(self._inflight)
        done, still_running = await asyncio.wait(pending, timeout=SHUTDOWN_GRACE_SECONDS)
        for task in still_running:
            task.cancel()
        log.info("collector.drained", finished=len(done), cancelled=len(still_running))


async def run_collector(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    gateway: TelegramGateway,
    ingestor: MessageIngestor,
    settings: Settings,
    account_id: int,
    stop: asyncio.Event | None = None,
) -> None:
    """Start the collector and run until SIGTERM."""
    stop = stop or asyncio.Event()
    install_signal_handlers(stop)

    collector = Collector(
        session_factory=session_factory,
        redis=redis,
        gateway=gateway,
        ingestor=ingestor,
        settings=settings,
        account_id=account_id,
    )
    joiner = JoinWorker(
        session_factory=session_factory,
        gateway=gateway,
        ingestor=ingestor,
        settings=settings,
        account_id=account_id,
    )

    await gateway.start()
    await collector.registry.refresh()
    collector.register_handlers()

    log.info("service.started", service="collector", sources=len(collector.registry.chat_ids))

    workers = [
        asyncio.create_task(collector.registry.run(stop)),
        asyncio.create_task(run_heartbeat(redis, account_id, stop)),
        asyncio.create_task(joiner.run(stop)),
    ]

    try:
        await collector.recover_gaps()
        await stop.wait()
    finally:
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        await collector.drain()
        await gateway.stop()
        log.info("service.stopped", service="collector")
