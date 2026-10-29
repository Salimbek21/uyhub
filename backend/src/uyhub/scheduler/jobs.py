"""The periodic work nobody triggers (SPEC 2.1).

Four jobs. Each is a plain async function taking a session, so each can be run
on its own from a test or from the CLI when something needs forcing.

None of them is allowed to take the service down: a job that raises is logged
and the next one still runs. A failed rate refresh means so'm prices keep
yesterday's dollar value, which is a far better outcome than a scheduler that
stops expiring listings because cbu.uz was down.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uyhub import lifecycle
from uyhub.core.config import Settings
from uyhub.core.logging import get_logger
from uyhub.rates.cbu import CbuRateProvider, RateProvider
from uyhub.rates.store import save_rate

log = get_logger(__name__)

JobResult = int


@dataclass(frozen=True, slots=True)
class Job:
    """One periodic task and how often it should run."""

    name: str
    interval: timedelta
    run: Callable[[], Awaitable[JobResult]]


async def refresh_rates(session: AsyncSession, provider: RateProvider) -> int:
    """Store today's CBU rate. Returns 1 when a rate was written."""
    rate = await provider.fetch()
    await save_rate(session, rate)
    return 1


async def expire_listings(session: AsyncSession, redis: Redis, settings: Settings) -> int:
    """Retire listings that have gone quiet or whose posts were all deleted."""
    stale = await lifecycle.expire_stale(session, redis, settings)
    deleted = await lifecycle.expire_fully_deleted(session, redis)
    return stale + deleted


async def enforce_suppressions(session: AsyncSession, redis: Redis) -> int:
    """Take down anything whose seller has since asked to be removed."""
    return await lifecycle.remove_suppressed(session, redis)


async def update_trust_scores(session: AsyncSession) -> int:
    return await lifecycle.recompute_trust_scores(session)


def build_jobs(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    rate_provider: RateProvider | None = None,
) -> list[Job]:
    """The schedule. Intervals are deliberately coarse — none of this is urgent."""
    provider = rate_provider or CbuRateProvider(settings)

    async def _rates() -> int:
        async with session_factory() as session:
            written = await refresh_rates(session, provider)
            await session.commit()
            return written

    async def _expire() -> int:
        async with session_factory() as session:
            count = await expire_listings(session, redis, settings)
            await session.commit()
            return count

    async def _suppress() -> int:
        async with session_factory() as session:
            count = await enforce_suppressions(session, redis)
            await session.commit()
            return count

    async def _trust() -> int:
        async with session_factory() as session:
            count = await update_trust_scores(session)
            await session.commit()
            return count

    return [
        Job("rates", timedelta(hours=6), _rates),
        # Suppression is the one with a person waiting on it, so it runs often.
        Job("suppressions", timedelta(minutes=15), _suppress),
        Job("expiry", timedelta(hours=1), _expire),
        Job("trust_scores", timedelta(hours=12), _trust),
    ]


async def run_job_once(job: Job) -> None:
    """Run one job, swallowing its failure.

    The scheduler is a long-lived process; one unreachable external service
    must not end it.
    """
    try:
        result = await job.run()
    except Exception as exc:
        log.warning("scheduler.job_failed", job=job.name, error=type(exc).__name__)
    else:
        log.info("scheduler.job_done", job=job.name, result=result)


async def run_loop(jobs: list[Job], stop: asyncio.Event, *, tick: float = 30.0) -> None:
    """Run each job on its own interval until stopped.

    Every job runs once at startup. That is what makes a restart a recovery:
    whatever was missed while the process was down is caught up immediately
    rather than waiting out a full interval.
    """
    next_run = dict.fromkeys((job.name for job in jobs), 0.0)
    elapsed = 0.0

    while not stop.is_set():
        for job in jobs:
            if elapsed >= next_run[job.name]:
                await run_job_once(job)
                next_run[job.name] = elapsed + job.interval.total_seconds()

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=tick)
        elapsed += tick
