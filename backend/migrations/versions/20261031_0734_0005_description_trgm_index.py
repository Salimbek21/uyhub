"""description trigram index

Revision ID: 0005
Revises: 0004
The feed's text search looks in the description as well as the title and the
landmark. Measured on the first real listings, `landmark` was set on 1 in 27
and the title is only a room count and a district, so a search for "metro"
matched nothing while twelve descriptions mentioned one.

Create Date: 2026-10-31 07:34:17.823977+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_listings_description_trgm",
        "listings",
        ["description"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"description": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_listings_description_trgm",
        table_name="listings",
        postgresql_using="gin",
        postgresql_ops={"description": "gin_trgm_ops"},
    )
