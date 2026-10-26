"""UyHub command line interface.

Single entrypoint for every service and admin command (SPEC section 2.1). The
Docker image runs ``uyhub <service>``; operators run the admin commands.
"""

from __future__ import annotations

import asyncio

import typer

from uyhub import __version__
from uyhub.core.config import Settings, get_settings
from uyhub.core.logging import configure_logging, get_logger
from uyhub.service import run_until_stopped

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
    """Run the Telegram collector (Telethon userbot). Implemented in Phase 1."""
    _bootstrap("collector")
    asyncio.run(run_until_stopped("collector"))


@app.command()
def parser() -> None:
    """Run the parser worker (prefilter, regex, LLM). Implemented in Phase 2."""
    _bootstrap("parser")
    asyncio.run(run_until_stopped("parser"))


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
    """Run periodic jobs. Implemented in Phase 2 onwards."""
    _bootstrap("scheduler")
    asyncio.run(run_until_stopped("scheduler"))


@app.command(name="init-storage")
def init_storage() -> None:
    """Create the MinIO buckets if they are missing. Idempotent."""
    from uyhub.core.s3 import ensure_buckets

    settings = _bootstrap("cli")
    asyncio.run(ensure_buckets(settings))
    typer.echo(f"buckets ready: {settings.s3_bucket_raw}, {settings.s3_bucket_media}")


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
