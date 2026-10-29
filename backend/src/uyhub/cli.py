"""UyHub command line interface.

Single entrypoint for every service and admin command (SPEC section 2.1). The
Docker image runs ``uyhub <service>``; operators run the admin commands.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import typer

from uyhub import __version__
from uyhub.core.config import Settings, get_settings
from uyhub.core.logging import configure_logging, get_logger
from uyhub.service import run_until_stopped

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

app = typer.Typer(
    name="uyhub",
    help="UyHub — Telegram real-estate aggregator for Tashkent.",
    no_args_is_help=True,
    add_completion=False,
)

log = get_logger(__name__)

SERVICE_NAMES = ("collector", "parser", "api", "bot", "poster", "scheduler")
"""Every long-running entrypoint. Kept in sync with SPEC section 2.1."""


def _bootstrap(service: str) -> Settings:
    """Load settings and configure logging for a service process."""
    settings = get_settings()
    configure_logging(service, level=settings.log_level, log_format=settings.log_format)
    return settings


@app.command()
def version() -> None:
    """Print the application version."""
    typer.echo(__version__)


@app.command()
def collector() -> None:
    """Run the Telegram collector (Telethon userbot)."""
    from uyhub.collector.bootstrap import run_from_settings

    settings = _bootstrap("collector")
    asyncio.run(run_from_settings(settings))


@app.command()
def parser(
    consumer: str = typer.Option("parser-1", help="Consumer name within the group."),
) -> None:
    """Run the parser worker: consume stream:raw, extract, store."""
    from uyhub.core.db import dispose_engine, get_sessionmaker
    from uyhub.core.redis import close_redis, get_redis
    from uyhub.parser.runner import run_parser

    settings = _bootstrap("parser")

    async def _run() -> None:
        try:
            await run_parser(
                session_factory=get_sessionmaker(settings),
                redis=get_redis(settings),
                settings=settings,
                consumer_name=consumer,
            )
        finally:
            await dispose_engine()
            await close_redis()

    asyncio.run(_run())


@app.command(name="reparse")
def reparse(
    since: str | None = typer.Option(None, help="ISO date; only messages posted after it."),
    version_below: int | None = typer.Option(
        None, help="Only messages parsed by a version older than this."
    ),
    limit: int = typer.Option(1000, help="Maximum messages to re-queue."),
) -> None:
    """Re-queue stored messages so an improved parser can run over them again.

    Nothing is re-extracted here; the messages are simply published back onto
    stream:raw and the running parser picks them up.
    """
    from uyhub.core.db import dispose_engine, session_scope
    from uyhub.core.redis import close_redis, get_redis
    from uyhub.parser.reparse import requeue

    settings = _bootstrap("cli")

    async def _run() -> int:
        try:
            async with session_scope() as session:
                return await requeue(
                    session,
                    get_redis(settings),
                    since=_parse_date(since),
                    version_below=version_below,
                    limit=limit,
                )
        finally:
            await dispose_engine()
            await close_redis()

    typer.echo(f"re-queued {asyncio.run(_run())} messages")


def _parse_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@app.command(name="update-rates")
def update_rates() -> None:
    """Fetch today's CBU exchange rate and store it. Idempotent."""
    from uyhub.core.db import dispose_engine, session_scope
    from uyhub.rates.cbu import CbuRateProvider
    from uyhub.rates.store import save_rate

    settings = _bootstrap("cli")

    async def _run() -> str:
        try:
            rate = await CbuRateProvider(settings).fetch()
            async with session_scope() as session:
                await save_rate(session, rate)
            return f"{rate.currency.value} {rate.rate_uzs} on {rate.on_date.isoformat()}"
        finally:
            await dispose_engine()

    typer.echo(asyncio.run(_run()))


@app.command()
def api(
    host: str | None = typer.Option(None, help="Bind address. Defaults to API_HOST."),
    port: int | None = typer.Option(None, help="Bind port. Defaults to API_PORT."),
    reload: bool = typer.Option(False, help="Auto-reload on code changes (local only)."),
) -> None:
    """Run the FastAPI application."""
    import uvicorn

    settings = _bootstrap("api")
    uvicorn.run(
        "uyhub.api.app:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
        log_config=None,  # structlog already owns stdlib logging
        access_log=False,
    )


@app.command()
def bot() -> None:
    """Run the Telegram bot (aiogram). Implemented in Phase 6."""
    _bootstrap("bot")
    asyncio.run(run_until_stopped("bot"))


@app.command()
def poster() -> None:
    """Run the channel poster. Implemented in Phase 6."""
    _bootstrap("poster")
    asyncio.run(run_until_stopped("poster"))


@app.command()
def scheduler() -> None:
    """Run periodic jobs: exchange rates, listing expiry, suppressions, trust."""
    from uyhub.core.db import dispose_engine, get_sessionmaker
    from uyhub.core.redis import close_redis, get_redis
    from uyhub.scheduler.runner import run_scheduler

    settings = _bootstrap("scheduler")

    async def _run() -> None:
        try:
            await run_scheduler(
                session_factory=get_sessionmaker(settings),
                redis=get_redis(settings),
                settings=settings,
            )
        finally:
            await dispose_engine()
            await close_redis()

    asyncio.run(_run())


@app.command(name="init-storage")
def init_storage() -> None:
    """Create the MinIO buckets if they are missing. Idempotent."""
    from uyhub.core.s3 import ensure_buckets

    settings = _bootstrap("cli")
    asyncio.run(ensure_buckets(settings))
    typer.echo(f"buckets ready: {settings.s3_bucket_raw}, {settings.s3_bucket_media}")


sources_app = typer.Typer(
    name="sources",
    help="Manage the groups and channels the collector reads (SPEC 4.2).",
    no_args_is_help=True,
)
app.add_typer(sources_app)


def _run_with_session(coro_factory: Callable[[AsyncSession], Awaitable[str]]) -> None:
    """Run one admin operation in a transaction and print what it did.

    Every ``sources`` subcommand is a single short transaction followed by a
    notification, so they all share this shape.
    """
    from uyhub.collector.runner import notify_sources_changed
    from uyhub.core.db import dispose_engine, session_scope
    from uyhub.core.redis import close_redis, get_redis

    async def _run() -> str:
        try:
            async with session_scope() as session:
                message = await coro_factory(session)
            await notify_sources_changed(get_redis())
            return message
        finally:
            await dispose_engine()
            await close_redis()

    typer.echo(asyncio.run(_run()))


@sources_app.command("add")
def sources_add(
    ref: str = typer.Argument(..., help="@username, t.me link or invite link."),
    priority: int = typer.Option(
        100, help="Join order, lowest first. Use 1-30 for the curated first batch."
    ),
    city: str = typer.Option("tashkent", help="City this source covers."),
) -> None:
    """Register a source. It is joined later by the collector's join worker."""
    from uyhub.collector.sources import add_source

    _bootstrap("cli")

    async def operation(session: AsyncSession) -> str:
        source = await add_source(session, ref, priority=priority, city=city)
        return f"source {source.id}: {source.status.value} (priority {source.priority})"

    try:
        _run_with_session(operation)
    except ValueError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=1) from exc


@sources_app.command("list")
def sources_list(
    status: str | None = typer.Option(None, help="Filter by status."),
) -> None:
    """List sources with their status and counters."""
    from uyhub.collector.sources import list_sources
    from uyhub.core.db import dispose_engine, session_scope
    from uyhub.models.enums import SourceStatus

    _bootstrap("cli")

    async def _run() -> list[str]:
        try:
            async with session_scope() as session:
                wanted = SourceStatus(status) if status else None
                rows = await list_sources(session, status=wanted)
                return [
                    f"{row.id:>4}  {row.status.value:<13} p{row.priority:<4} "
                    f"{(row.username and '@' + row.username) or row.invite_link or '-':<32} "
                    f"msgs={row.messages_total}"
                    for row in rows
                ]
        finally:
            await dispose_engine()

    for line in asyncio.run(_run()) or ["no sources"]:
        typer.echo(line)


@sources_app.command("pause")
def sources_pause(source_id: int = typer.Argument(..., help="Source id.")) -> None:
    """Stop processing a source's messages but stay in the chat."""
    from uyhub.collector.sources import set_status
    from uyhub.models.enums import SourceStatus

    _bootstrap("cli")

    async def operation(session: AsyncSession) -> str:
        await set_status(session, source_id, SourceStatus.PAUSED)
        return f"source {source_id}: paused"

    _run_with_session(operation)


@sources_app.command("resume")
def sources_resume(source_id: int = typer.Argument(..., help="Source id.")) -> None:
    """Resume a paused source."""
    from uyhub.collector.sources import set_status
    from uyhub.models.enums import SourceStatus

    _bootstrap("cli")

    async def operation(session: AsyncSession) -> str:
        await set_status(session, source_id, SourceStatus.ACTIVE)
        return f"source {source_id}: active"

    _run_with_session(operation)


@sources_app.command("remove")
def sources_remove(source_id: int = typer.Argument(..., help="Source id.")) -> None:
    """Mark a source as left. Leaving the chat itself is a manual step."""
    from uyhub.collector.sources import set_status
    from uyhub.models.enums import SourceStatus

    _bootstrap("cli")

    async def operation(session: AsyncSession) -> str:
        await set_status(session, source_id, SourceStatus.LEFT)
        return f"source {source_id}: left"

    _run_with_session(operation)


@app.command(name="check")
def check() -> None:
    """Probe every external dependency and report. Exits non-zero on failure."""
    from uyhub.api.app import READINESS_CHECKS
    from uyhub.core.db import dispose_engine
    from uyhub.core.errors import DependencyUnavailableError
    from uyhub.core.redis import close_redis

    _bootstrap("cli")

    async def _run() -> bool:
        ok = True
        try:
            for name, probe in READINESS_CHECKS.items():
                try:
                    await probe()
                except DependencyUnavailableError as exc:
                    typer.echo(f"  {name}: FAIL ({exc.reason})")
                    ok = False
                else:
                    typer.echo(f"  {name}: ok")
        finally:
            await dispose_engine()
            await close_redis()
        return ok

    if not asyncio.run(_run()):
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
