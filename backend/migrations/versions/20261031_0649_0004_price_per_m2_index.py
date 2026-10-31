"""price per m2 expression index

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31 06:49:57.319561+00:00

The `price_per_m2` sort (SPEC 9.2) orders by an expression, so it needs an
index on that expression — a plain column index cannot serve it. The spelling
here must match `api.feed.price_per_m2_expression` exactly, including the bare
`0` rather than a bind parameter, or the planner will not use it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_listings_price_per_m2",
        "listings",
        ["status", sa.literal_column("(price_usd / nullif(area_m2, 0))"), "id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_listings_price_per_m2", table_name="listings")
