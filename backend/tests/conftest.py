"""Shared pytest fixtures.

Integration tests run against the real Postgres, Redis and MinIO from ``make up``
(CLAUDE.md "Code rules"). They use a separate ``*_test`` database and Redis DB 15 so
a test run can never touch development data.

Scoping note: session-scoped setup is deliberately synchronous. Async fixtures run
in the per-test event loop, and a session-scoped async fixture would hand objects
bound to one loop to tests running in another.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from redis.asyncio import Redis
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from uyhub.core.config import Settings, get_settings

TEST_DB_SUFFIX = "_test"
TEST_REDIS_DB = "15"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _with_path(url: str, path: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{path}", parts.query, parts.fragment))


def _path_of(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def base_settings() -> Settings:
    """Settings as configured on this machine, before any test override."""
    return Settings()


@pytest.fixture(scope="session")
def test_database_url(base_settings: Settings) -> str:
    """URL of the dedicated test database."""
    return _with_path(
        base_settings.database_url, _path_of(base_settings.database_url) + TEST_DB_SUFFIX
    )


@pytest.fixture(scope="session")
def test_redis_url(base_settings: Settings) -> str:
    """URL of the Redis database reserved for tests."""
    return _with_path(base_settings.redis_url, TEST_REDIS_DB)


@pytest.fixture(autouse=True)
def _isolate_settings(
    monkeypatch: pytest.MonkeyPatch,
    test_database_url: str,
    test_redis_url: str,
) -> Iterator[None]:
    """Point every test at the test database and clear the settings cache.

    Autouse, so no test can read the developer's own values or write to the
    development database by forgetting a fixture.
    """
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("REDIS_URL", test_redis_url)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    """Settings for the current test, with the overrides above applied."""
    return get_settings()


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


async def _recreate_database(admin_url: str, database: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            # Identifiers cannot be bound as parameters; the name is derived from
            # our own configuration, not from user input.
            await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            await conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_database(base_settings: Settings, test_database_url: str) -> str:
    """Drop, recreate and migrate the test database once per session.

    Recreating gives every run a known-good schema instead of inheriting whatever
    the previous run left behind.
    """
    from alembic import command
    from alembic.config import Config

    asyncio.run(
        _recreate_database(
            _with_path(base_settings.database_url, "postgres"),
            _path_of(test_database_url),
        )
    )

    with pytest.MonkeyPatch.context() as mp:
        # migrations/env.py reads DATABASE_URL through Settings, by design.
        mp.setenv("DATABASE_URL", test_database_url)
        get_settings.cache_clear()
        cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        command.upgrade(cfg, "head")
    get_settings.cache_clear()

    return test_database_url


@pytest.fixture
async def db_connection(migrated_database: str) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is always rolled back.

    Tests see a migrated schema and leave no trace, which is far faster than
    recreating the schema per test.
    """
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                yield connection
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """An ORM session bound to the rolled-back connection.

    ``create_savepoint`` means a test can provoke an ``IntegrityError`` and then
    ``rollback()`` without tearing down the outer transaction the fixture owns.
    """
    factory = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with factory() as session:
        yield session


@pytest.fixture
def session_factory(db_connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """A sessionmaker for code that opens its own sessions and commits.

    ``join_transaction_mode="create_savepoint"`` turns each ``commit()`` into a
    savepoint release inside the test's outer transaction, so production code can
    commit for real and the test still rolls everything back afterwards.
    """
    return async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


@pytest.fixture
async def redis_client(settings: Settings) -> AsyncIterator[Redis]:
    """A client on the reserved test database, flushed before and after."""
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.flushdb()
        yield client
        await client.flushdb()
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Object storage
# ---------------------------------------------------------------------------


@pytest.fixture
async def s3_bucket(settings: Settings, request: pytest.FixtureRequest) -> AsyncIterator[str]:
    """A bucket unique to this test, emptied and removed afterwards."""
    from uyhub.core.s3 import s3_client

    raw = request.node.name.lower()
    safe = "".join(ch if ch.isalnum() else "-" for ch in raw).strip("-")
    bucket = f"test-{safe}"[:62].rstrip("-")

    async with s3_client(settings) as client:
        await client.create_bucket(Bucket=bucket)
        try:
            yield bucket
        finally:
            listed = await client.list_objects_v2(Bucket=bucket)
            for obj in listed.get("Contents", []):
                key = obj.get("Key")
                if key:
                    await client.delete_object(Bucket=bucket, Key=key)
            await client.delete_bucket(Bucket=bucket)
