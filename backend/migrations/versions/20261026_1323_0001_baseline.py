"""baseline

Phase 0 ships an intentionally empty baseline so that ``alembic upgrade head`` is a
working, tested command and ``alembic_version`` is initialized before any table
exists. The tables from docs/SPEC.md section 3 arrive in Phase 1 as revision 0002.

Enables the extensions the schema will depend on:

``pg_trgm``  trigram indexes on ``listings.title`` and ``listings.landmark`` for the
            ``q`` text filter (SPEC 3, 9.2). Creating the extension needs superuser,
            so it belongs here rather than in a later revision that might run under
            a reduced-privilege role.

Revision ID: 0001
Revises:
Create Date: 2026-10-26 13:23 UTC
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
