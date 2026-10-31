"""The canonical listing and everything attached to it.

A listing is the deduplicated result of one or more raw messages: the same flat
cross-posted to ten groups is one row here and ten rows in ``listing_sources``.

Phone numbers are stored **only** as keyed hashes. They are what dedup matches on
(SPEC 7.1) and they are never served to anyone — the Mini App links to the original
Telegram post instead. Keeping the plaintext would create a re-publishable database
of numbers collected without consent; see docs/DECISIONS.md and OPEN_QUESTIONS C1.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from uyhub.models.base import Base, IdMixin, TimestampMixin, UuidMixin, enum_column
from uyhub.models.enums import (
    BuildingType,
    Currency,
    DealType,
    District,
    ListingStatus,
    PricePeriod,
    PropertyType,
    Renovation,
)


class Listing(UuidMixin, TimestampMixin, Base):
    """One real-world property on offer (SPEC 3 ``listings``)."""

    __tablename__ = "listings"

    # -- What is on offer ----------------------------------------------------
    deal_type: Mapped[DealType] = mapped_column(enum_column(DealType, "deal_type"), nullable=False)
    property_type: Mapped[PropertyType] = mapped_column(
        enum_column(PropertyType, "property_type"),
        nullable=False,
        default=PropertyType.OTHER,
    )
    """``other`` is the not-yet-known value, like ``building_type``'s ``unknown``.

    It used to default to ``apartment``, which stored a guess as a fact: a post
    that never says what it is would be filtered as a flat, and the derived
    title said "obyekt" while the column said "kvartira". A later sighting that
    does name the type fills it in (see ``dedup.merge``)."""
    rooms: Mapped[int | None] = mapped_column(SmallInteger)
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    land_sotix: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    floor: Mapped[int | None] = mapped_column(SmallInteger)
    floors_total: Mapped[int | None] = mapped_column(SmallInteger)
    building_type: Mapped[BuildingType] = mapped_column(
        enum_column(BuildingType, "building_type"),
        nullable=False,
        default=BuildingType.UNKNOWN,
    )
    renovation: Mapped[Renovation] = mapped_column(
        enum_column(Renovation, "renovation"),
        nullable=False,
        default=Renovation.UNKNOWN,
    )

    # -- Price ---------------------------------------------------------------
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_currency: Mapped[Currency | None] = mapped_column(enum_column(Currency, "currency"))
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    """Derived from ``price_amount`` via the CBU rate. The only field worth sorting on."""

    price_period: Mapped[PricePeriod | None] = mapped_column(
        enum_column(PricePeriod, "price_period")
    )
    negotiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # -- Where ---------------------------------------------------------------
    district: Mapped[District | None] = mapped_column(enum_column(District, "district"))
    landmark: Mapped[str | None] = mapped_column(Text)
    address_text: Mapped[str | None] = mapped_column(Text)

    # -- Text ----------------------------------------------------------------
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    """Generated, Uzbek, e.g. "3 xonali kvartira, Chilonzor, 75 m²"."""

    description: Mapped[str | None] = mapped_column(Text)
    """Original post text with phones, @mentions and links removed (SPEC 6.3)."""

    phone_hashes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    """HMAC-SHA256 of each phone, keyed by ``PHONE_HASH_KEY``. Never reversible here."""

    # -- Quality and state ---------------------------------------------------
    status: Mapped[ListingStatus] = mapped_column(
        enum_column(ListingStatus, "listing_status"),
        nullable=False,
        default=ListingStatus.ACTIVE,
    )
    quality_score: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # -- Dedup fingerprints (SPEC 7.1) ---------------------------------------
    dedup_key: Mapped[str | None] = mapped_column(String(64))
    text_simhash: Mapped[int | None] = mapped_column(BigInteger)
    cover_phash: Mapped[int | None] = mapped_column(BigInteger)

    # -- Timeline ------------------------------------------------------------
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_to_channel_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    """Bumped on every material change; the Mini App and the poster use it to
    decide whether a cached card is stale."""

    __table_args__ = (
        # The feed's filter query, in selectivity order.
        Index(
            "ix_listings_feed",
            "status",
            "deal_type",
            "district",
            "rooms",
            "price_usd",
        ),
        # The default feed sort: newest active listings first.
        Index("ix_listings_status_first_seen", "status", desc("first_seen_at")),
        Index("ix_listings_dedup_key", "dedup_key"),
        Index("ix_listings_phone_hashes", "phone_hashes", postgresql_using="gin"),
        Index(
            "ix_listings_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_listings_landmark_trgm",
            "landmark",
            postgresql_using="gin",
            postgresql_ops={"landmark": "gin_trgm_ops"},
        ),
        # The feed's text search also looks in the description: the title is
        # only a room count and a district, so searching for a landmark or a
        # metro station finds nothing without this.
        Index(
            "ix_listings_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
        # The `price_per_m2` sort (SPEC 9.2). The expression must be spelled
        # exactly as `api.feed.price_per_m2_expression` renders it or the
        # planner will not match the two.
        Index(
            "ix_listings_price_per_m2",
            "status",
            text("(price_usd / nullif(area_m2, 0))"),
            "id",
        ),
    )


class ListingSource(IdMixin, Base):
    """Where a listing was seen. One row per raw message that fed it (SPEC 3).

    This is the attribution the Mini App shows and SPEC 13 requires: every listing
    links back to the posts it came from.
    """

    __tablename__ = "listing_sources"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    raw_message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_messages.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    tg_link: Mapped[str | None] = mapped_column(Text)
    """``https://t.me/...``, or NULL for private chats that have no public link."""

    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("listing_id", "raw_message_id", name="uq_listing_sources_listing_raw"),
        Index("ix_listing_sources_listing", "listing_id"),
    )


class ListingPhoto(IdMixin, Base):
    """A processed photo. Originals stay private; only the derivatives are served."""

    __tablename__ = "listing_photos"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    s3_key_original: Mapped[str] = mapped_column(Text, nullable=False)
    s3_key_large: Mapped[str | None] = mapped_column(Text)
    s3_key_thumb: Mapped[str | None] = mapped_column(Text)

    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    phash: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """When the photo was stored. This is what the retention window counts."""

    original_pruned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the full-size original was deleted to reclaim disk, or NULL while it
    is still there. The derivatives are unaffected and `s3_key_original` is kept
    so the record of where the file was does not disappear with it.

    This column, not the bucket, is the record of what has been reclaimed — it
    is what stops a second run re-deleting the same keys (docs/DECISIONS.md 6.3)."""

    __table_args__ = (
        UniqueConstraint("listing_id", "sha256", name="uq_listing_photos_listing_sha256"),
        # The prune job's query: oldest first, among those not yet reclaimed.
        # Partial, because the reclaimed rows are the ones it never looks at and
        # they are eventually almost all of them.
        Index(
            "ix_listing_photos_prunable",
            "created_at",
            postgresql_where=text("original_pruned_at IS NULL"),
        ),
        Index("ix_listing_photos_listing_position", "listing_id", "position"),
    )


class PriceHistory(IdMixin, Base):
    """Every price we have observed for a listing (SPEC 7.2)."""

    __tablename__ = "price_history"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_currency: Mapped[Currency | None] = mapped_column(enum_column(Currency, "currency"))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_price_history_listing_observed", "listing_id", "observed_at"),)
