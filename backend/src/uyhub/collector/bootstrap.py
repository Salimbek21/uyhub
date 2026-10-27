"""Assembling a collector from settings.

Kept out of ``cli.py`` so that the CLI stays a thin argument parser, and out of
``runner.py`` so that the runner can be constructed from fakes in tests without
touching Telethon, Postgres, Redis or MinIO.
"""

from __future__ import annotations

from uyhub.collector.accounts import default_account
from uyhub.collector.client import build_client
from uyhub.collector.gateway import TelethonGateway
from uyhub.collector.ingest import MessageIngestor
from uyhub.collector.media import S3PhotoStore
from uyhub.collector.runner import run_collector
from uyhub.core.config import Settings, get_settings
from uyhub.core.db import dispose_engine, get_sessionmaker
from uyhub.core.errors import ConfigError
from uyhub.core.logging import get_logger
from uyhub.core.redis import close_redis, get_redis

log = get_logger(__name__)


async def run_from_settings(settings: Settings | None = None) -> None:
    """Build every dependency and run the collector until SIGTERM."""
    cfg = settings or get_settings()

    session_factory = get_sessionmaker(cfg)
    redis = get_redis(cfg)

    async with session_factory() as session:
        account = await default_account(session)

    if account is None:
        msg = (
            "no active userbot account found; run `make login-userbot` on the "
            "server to create the session and register the account"
        )
        raise ConfigError(msg)

    gateway = TelethonGateway(build_client(cfg))
    ingestor = MessageIngestor(
        session_factory=session_factory,
        redis=redis,
        gateway=gateway,
        photo_store=S3PhotoStore(cfg),
    )

    try:
        await run_collector(
            session_factory=session_factory,
            redis=redis,
            gateway=gateway,
            ingestor=ingestor,
            settings=cfg,
            account_id=account.id,
        )
    finally:
        await dispose_engine()
        await close_redis()
