"""Collector-side tables: userbot accounts, sources, and the raw message log.

``raw_messages`` is deliberately immutable in spirit — it is the copy of what
Telegram actually sent us. Everything downstream (parser, dedup, listings) can be
rebuilt from it, which is what makes ``uyhub parser reparse`` possible.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from uyhub.models.base import Base, IdMixin, TimestampMixin, enum_column
from uyhub.models.enums import AccountStatus, RawMessageStatus, SourceKind, SourceStatus


class TgAccount(IdMixin, TimestampMixin, Base):
    """A Telethon userbot account (SPEC 4.1).

    One account owns many sources. MVP runs a single account, but the join budget
    and flood-wait state are per account from the start so adding a second one is
    a row, not a refactor.
    """

    __tablename__ = "tg_accounts"

    label: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    phone_masked: Mapped[str] = mapped_column(String(16), nullable=False)
    """Last four digits only. The full number never reaches the database (SPEC 13)."""

    status: Mapped[AccountStatus] = mapped_column(
        enum_column(AccountStatus, "account_status"),
        nullable=False,
        default=AccountStatus.ACTIVE,
    )
    flood_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joins_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    joins_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Source(IdMixin, TimestampMixin, Base):
    """A group or channel we read (SPEC 4.2)."""

    __tablename__ = "sources"

    tg_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    """Unknown until the account has actually joined."""

    username: Mapped[str | None] = mapped_column(String(64))
    invite_link: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[SourceKind | None] = mapped_column(enum_column(SourceKind, "source_kind"))
    city: Mapped[str] = mapped_column(String(64), nullable=False, default="tashkent")

    account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tg_accounts.id", ondelete="SET NULL")
    )
    status: Mapped[SourceStatus] = mapped_column(
        enum_column(SourceStatus, "source_status"),
        nullable=False,
        default=SourceStatus.PENDING_JOIN,
    )

    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=100)
    """Join order, lowest first. Lets the first batch of sources go live in days
    rather than weeks under the daily join cap (docs/DECISIONS.md, OPEN_QUESTIONS A3)."""

    last_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_text: Mapped[str | None] = mapped_column(Text)

    messages_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    listings_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    trust_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    __table_args__ = (
        # The join worker's hot query: next pending source, best priority first.
        Index("ix_sources_status_priority", "status", "priority"),
    )


class RawMessage(IdMixin, TimestampMixin, Base):
    """One received message, or one album stored as a single row (SPEC 3).

    For an album, ``tg_message_id`` is the id of the first message and ``media``
    carries every photo in the group.
    """

    __tablename__ = "raw_messages"

    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    tg_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    grouped_id: Mapped[int | None] = mapped_column(BigInteger)

    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    text: Mapped[str | None] = mapped_column(Text)
    media: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    """Photo refs and their S3 keys; videos and documents as metadata only (SPEC 4.5)."""

    raw: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    """Trimmed Telethon payload, kept for debugging and reparsing."""

    status: Mapped[RawMessageStatus] = mapped_column(
        enum_column(RawMessageStatus, "raw_message_status"),
        nullable=False,
        default=RawMessageStatus.PENDING,
    )
    parser_version: Mapped[int | None] = mapped_column(Integer)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("source_id", "tg_message_id", name="uq_raw_messages_source_message"),
        # The parser's backlog query and `reparse --version-below N`.
        Index("ix_raw_messages_status_id", "status", "id"),
        Index("ix_raw_messages_source_tg_message", "source_id", "tg_message_id"),
    )
