"""Migrations apply and reverse cleanly.

CLAUDE.md forbids editing an applied migration, so a revision with a broken
downgrade is permanent. This test is the gate that stops one being committed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TextIO

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import create_async_engine

from uyhub.core.config import get_settings

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(database_url: str, output_buffer: TextIO | None = None) -> Config:
    # output_buffer must be passed to the constructor; offline mode reads it from
    # there, not from an attribute assigned afterwards.
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"), output_buffer=output_buffer)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


async def _current_revision(database_url: str) -> str | None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            row = result.scalar_one_or_none()
            return str(row) if row is not None else None
    finally:
        await engine.dispose()


def test_there_is_exactly_one_head() -> None:
    """Two heads mean someone branched without merging; migrations would not apply."""
    script = ScriptDirectory.from_config(_alembic_config("postgresql+asyncpg://unused/db"))
    assert len(script.get_heads()) == 1, f"multiple heads: {script.get_heads()}"


def test_revision_ids_are_unique() -> None:
    script = ScriptDirectory.from_config(_alembic_config("postgresql+asyncpg://unused/db"))
    revisions = [rev.revision for rev in script.walk_revisions()]
    assert len(revisions) == len(set(revisions))


async def test_database_is_at_head(migrated_database: str) -> None:
    script = ScriptDirectory.from_config(_alembic_config(migrated_database))
    assert await _current_revision(migrated_database) == script.get_current_head()


def test_upgrade_downgrade_upgrade_is_clean(migrated_database: str) -> None:
    """Round-trip the whole chain. Runs in a thread: Alembic owns its own loop."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", migrated_database)
        get_settings.cache_clear()
        cfg = _alembic_config(migrated_database)
        try:
            command.downgrade(cfg, "base")
            assert asyncio.run(_current_revision(migrated_database)) is None
            command.upgrade(cfg, "head")
        finally:
            # Leave the database at head for whichever test runs next.
            command.upgrade(cfg, "head")
    get_settings.cache_clear()

    script = ScriptDirectory.from_config(_alembic_config(migrated_database))
    assert asyncio.run(_current_revision(migrated_database)) == script.get_current_head()


def test_offline_mode_renders_sql(migrated_database: str, tmp_path: Path) -> None:
    """`alembic upgrade head --sql` must work so a DBA can review a release."""
    output = tmp_path / "upgrade.sql"
    with output.open("w") as handle:
        command.upgrade(_alembic_config(migrated_database, handle), "head", sql=True)
    rendered = output.read_text()
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in rendered
    assert "alembic_version" in rendered
