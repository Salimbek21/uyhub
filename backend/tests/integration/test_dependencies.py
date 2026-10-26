"""The real Postgres, Redis and MinIO from `make up` answer as expected.

These are the tests that would have caught a wrong port, a wrong password or a
missing bucket — the failures that cost the most time to diagnose by hand.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from uyhub.api import app as app_module
from uyhub.core.config import Settings
from uyhub.core.db import check_database, dispose_engine
from uyhub.core.errors import DependencyUnavailableError
from uyhub.core.redis import check_redis, close_redis
from uyhub.core.s3 import check_s3, s3_client

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


async def test_database_is_reachable(migrated_database: str) -> None:
    try:
        await check_database()
    finally:
        await dispose_engine()


async def test_connection_runs_queries(db_connection: AsyncConnection) -> None:
    result = await db_connection.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


async def test_pg_trgm_extension_is_installed(db_connection: AsyncConnection) -> None:
    """Phase 4's `q` text filter depends on it; the baseline migration enables it."""
    result = await db_connection.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
    )
    assert result.scalar_one_or_none() == 1


async def test_timestamps_are_utc(db_connection: AsyncConnection) -> None:
    """SPEC section 3 requires timestamptz; verify the server agrees on UTC."""
    result = await db_connection.execute(text("SHOW timezone"))
    assert result.scalar_one() in {"UTC", "Etc/UTC"}


async def test_database_check_fails_on_a_bad_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:1/none")
    from uyhub.core.config import get_settings

    get_settings.cache_clear()
    await dispose_engine()
    try:
        with pytest.raises(DependencyUnavailableError) as excinfo:
            await check_database()
        assert excinfo.value.dependency == "postgres"
    finally:
        await dispose_engine()
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


async def test_redis_is_reachable() -> None:
    try:
        await check_redis()
    finally:
        await close_redis()


async def test_redis_round_trip(redis_client: Redis) -> None:
    await redis_client.set("uyhub:test:key", "value")
    assert await redis_client.get("uyhub:test:key") == "value"


async def test_redis_streams_work(redis_client: Redis) -> None:
    """The whole pipeline runs on Streams with consumer groups (SPEC 2.3)."""
    stream = "uyhub:test:stream"
    await redis_client.xadd(stream, {"raw_message_id": "1"})
    await redis_client.xgroup_create(stream, "workers", id="0")
    pending = await redis_client.xreadgroup("workers", "worker-1", {stream: ">"}, count=10)
    assert pending
    _, entries = pending[0]
    assert entries[0][1] == {"raw_message_id": "1"}


async def test_tests_use_a_separate_redis_database(settings: Settings) -> None:
    assert settings.redis_url.endswith("/15")


# ---------------------------------------------------------------------------
# Object storage
# ---------------------------------------------------------------------------


async def test_s3_is_reachable() -> None:
    await check_s3()


async def test_configured_buckets_exist(settings: Settings) -> None:
    """`make up` creates both; a missing one means minio-init did not run."""
    async with s3_client(settings) as client:
        listed = await client.list_buckets()
        names = {bucket["Name"] for bucket in listed.get("Buckets", [])}
    assert settings.s3_bucket_raw in names
    assert settings.s3_bucket_media in names


async def test_object_round_trip(settings: Settings, s3_bucket: str) -> None:
    async with s3_client(settings) as client:
        await client.put_object(Bucket=s3_bucket, Key="a/b.txt", Body=b"hello")
        obj = await client.get_object(Bucket=s3_bucket, Key="a/b.txt")
        body = await obj["Body"].read()
    assert body == b"hello"


# ---------------------------------------------------------------------------
# Readiness against the real stack
# ---------------------------------------------------------------------------


@pytest.fixture
async def live_client() -> AsyncIterator[httpx.AsyncClient]:
    application = app_module.create_app()
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def test_readyz_is_green_against_the_real_stack(
    live_client: httpx.AsyncClient, migrated_database: str
) -> None:
    try:
        response = await live_client.get("/readyz")
    finally:
        await dispose_engine()
        await close_redis()

    assert response.status_code == 200, response.text
    assert response.json()["checks"] == {"postgres": "ok", "redis": "ok", "s3": "ok"}
