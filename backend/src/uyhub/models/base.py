"""Declarative base and shared column conventions."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, Enum, Identity, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
"""Deterministic constraint names so Alembic autogenerate produces stable diffs."""


class Base(DeclarativeBase):
    """Base class for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """``created_at`` / ``updated_at`` in UTC, as required by SPEC section 3."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IdMixin:
    """Surrogate ``bigint`` identity primary key, the default for every table."""

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)


class UuidMixin:
    """UUID primary key, generated application-side.

    Only ``listings`` uses this: its id is public (it appears in Mini App deep
    links and channel posts), and a sequential integer would leak how much
    inventory the system holds.
    """

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def enum_column(enum_type: type[StrEnum], name: str) -> Enum:
    """A ``VARCHAR`` + ``CHECK`` column for a :class:`StrEnum`.

    ``native_enum=False`` keeps adding a value a plain migration away rather than
    an ``ALTER TYPE``. ``create_constraint=True`` is not the SQLAlchemy default
    and is the whole point of this helper: without it the column is an unchecked
    ``VARCHAR`` and a typo in a hand-written UPDATE lands silently.

    ``values_callable`` stores the string values rather than the Python member
    names, so what is in the database matches what the API returns.
    """
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )
