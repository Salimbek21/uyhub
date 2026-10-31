"""listing photo retention columns

Revision ID: 0006
Revises: 0005
Originals are 84% of stored bytes and are never served. `created_at` is what
the retention window counts from; `original_pruned_at` records that the
full-size file has been reclaimed, so a second run does not try again.

Existing rows get `created_at = now()`, which gives them a full retention
window from this migration rather than deleting anything on the first run.

Create Date: 2026-10-31 13:51:00.700045+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "listing_photos",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "listing_photos", sa.Column("original_pruned_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_listing_photos_prunable",
        "listing_photos",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("original_pruned_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_listing_photos_prunable",
        table_name="listing_photos",
        postgresql_where=sa.text("original_pruned_at IS NULL"),
    )
    op.drop_column("listing_photos", "original_pruned_at")
    op.drop_column("listing_photos", "created_at")
