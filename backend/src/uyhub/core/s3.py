"""Async S3-compatible object storage (MinIO).

Two buckets (SPEC sections 4.5 and 7.3):

``uyhub-raw``    originals downloaded by the collector — private, never served.
``uyhub-media``  derived ``large`` and ``thumb`` webp images — read-only public
                 prefix served by Caddy (SPEC 9.3).

Keeping them in separate buckets rather than separate prefixes of one bucket is
what makes "public read for derivatives, private for originals" expressible as a
bucket policy; see docs/DECISIONS.md.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import aioboto3
from aiobotocore.config import AioConfig
from botocore.exceptions import ClientError

from uyhub.core.config import Settings, get_settings
from uyhub.core.errors import DependencyUnavailableError
from uyhub.core.logging import get_logger

if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client

log = get_logger(__name__)

HEALTHCHECK_TIMEOUT_SECONDS = 5.0

_BOTO_CONFIG = AioConfig(
    connect_timeout=5,
    read_timeout=15,
    retries={"max_attempts": 3, "mode": "standard"},
    signature_version="s3v4",
)
"""Every external call gets a timeout and bounded retries (CLAUDE.md "Code rules")."""


@asynccontextmanager
async def s3_client(settings: Settings | None = None) -> AsyncIterator[S3Client]:
    """Yield an S3 client bound to the configured endpoint.

    aioboto3 clients are async context managers and are not safe to cache across
    event loops, so each caller opens one for the duration of its work.
    """
    cfg = settings or get_settings()
    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=cfg.s3_endpoint_url,
        aws_access_key_id=cfg.s3_access_key,
        aws_secret_access_key=cfg.s3_secret_key.get_secret_value(),
        region_name=cfg.s3_region,
        config=_BOTO_CONFIG,
    ) as client:
        yield client


async def ensure_buckets(settings: Settings | None = None) -> None:
    """Create the configured buckets if they do not exist. Idempotent."""
    cfg = settings or get_settings()
    async with s3_client(cfg) as client:
        for bucket in (cfg.s3_bucket_raw, cfg.s3_bucket_media):
            try:
                await client.head_bucket(Bucket=bucket)
            except ClientError:
                await client.create_bucket(Bucket=bucket)
                log.info("s3.bucket_created", bucket=bucket)


async def check_s3() -> None:
    """Raise :class:`DependencyUnavailableError` if object storage is not reachable."""
    cfg = get_settings()
    try:
        async with asyncio.timeout(HEALTHCHECK_TIMEOUT_SECONDS):
            async with s3_client(cfg) as client:
                await client.head_bucket(Bucket=cfg.s3_bucket_media)
    except TimeoutError as exc:
        raise DependencyUnavailableError("s3", "timeout") from exc
    except Exception as exc:
        raise DependencyUnavailableError("s3", type(exc).__name__) from exc
