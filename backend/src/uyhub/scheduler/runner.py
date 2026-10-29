"""The scheduler service loop."""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uyhub.core.config import Settings
from uyhub.core.logging import get_logger
from uyhub.scheduler.jobs import build_jobs, run_loop
from uyhub.service import install_signal_handlers

log = get_logger(__name__)


async def run_scheduler(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    stop: asyncio.Event | None = None,
) -> None:
    """Run every periodic job until SIGTERM."""
    stop = stop or asyncio.Event()
    install_signal_handlers(stop)

    jobs = build_jobs(session_factory=session_factory, redis=redis, settings=settings)
    log.info("service.started", service="scheduler", jobs=[job.name for job in jobs])
    try:
        await run_loop(jobs, stop)
    finally:
        log.info("service.stopped", service="scheduler")
