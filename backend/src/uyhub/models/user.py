"""Mini App and bot users, and everything scoped to one of them.

A user is identified only by their Telegram user id. We never store a name, a
username or a phone number for them (SPEC 13).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from uyhub.models.base import Base, IdMixin, TimestampMixin, enum_column
from uyhub.models.enums import Language, SavedSearchMode


class User(IdMixin, TimestampMixin, Base):
    """Someone who opened the Mini App or started the bot."""

    __tablename__ = "users"

    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    lang: Mapped[Language] = mapped_column(
        enum_column(Language, "language"), nullable=False, default=Language.UZ
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Favorite(Base):
    """A saved listing. Composite primary key — a user favourites a listing once."""

    __tablename__ = "favorites"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_favorites_user_created", "user_id", "created_at"),)


class SavedSearch(IdMixin, TimestampMixin, Base):
    """A filter set a user wants to be notified about. Max 10 per user (SPEC 3)."""

    __tablename__ = "saved_searches"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """Validated by the same Pydantic model as the API query parameters."""

    mode: Mapped[SavedSearchMode] = mapped_column(
        enum_column(SavedSearchMode, "saved_search_mode"),
        nullable=False,
        default=SavedSearchMode.INSTANT,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_saved_searches_user", "user_id"),)


class NotificationLog(IdMixin, Base):
    """Proof that a user was told about a listing.

    The unique constraint is the feature: it is what stops a user being notified
    twice about the same flat when it is reposted to another group.
    """

    __tablename__ = "notification_log"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    saved_search_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("saved_searches.id", ondelete="SET NULL")
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_notification_log_user_listing"),
    )
