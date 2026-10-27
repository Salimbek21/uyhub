"""The schema actually created by migration 0002 (SPEC section 3).

Autogenerate can produce a migration that applies cleanly and is still wrong —
a missing GIN index does not fail, it just makes dedup slow in a year. These
assertions are about the indexes and constraints the rest of the system relies
on, not about every column.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from uyhub.core.clock import now_utc
from uyhub.models.enums import DealType, District, ListingStatus
from uyhub.models.listing import Listing
from uyhub.models.telegram import RawMessage, Source

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "alembic_version",
    "exchange_rates",
    "favorites",
    "listing_photos",
    "listing_sources",
    "listings",
    "llm_calls",
    "notification_log",
    "price_history",
    "raw_messages",
    "saved_searches",
    "sources",
    "suppressed_phones",
    "tg_accounts",
    "users",
}


async def test_every_spec_table_exists(db_connection: AsyncConnection) -> None:
    names = await db_connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    assert names == EXPECTED_TABLES


async def test_contact_reveals_is_deliberately_absent(
    db_connection: AsyncConnection,
) -> None:
    """Phone numbers are never served, so there is no reveal to audit (D17)."""
    names = await db_connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    assert "contact_reveals" not in names


async def test_listings_has_no_plaintext_phone_column(
    db_connection: AsyncConnection,
) -> None:
    columns = await db_connection.run_sync(
        lambda sync: {column["name"] for column in inspect(sync).get_columns("listings")}
    )
    assert "phone_hashes" in columns
    assert "phones" not in columns


@pytest.mark.parametrize(
    ("table", "index"),
    [
        ("listings", "ix_listings_feed"),
        ("listings", "ix_listings_status_first_seen"),
        ("listings", "ix_listings_dedup_key"),
        ("listings", "ix_listings_phone_hashes"),
        ("listings", "ix_listings_title_trgm"),
        ("listings", "ix_listings_landmark_trgm"),
        ("raw_messages", "ix_raw_messages_status_id"),
        ("sources", "ix_sources_status_priority"),
    ],
)
async def test_required_indexes_exist(
    db_connection: AsyncConnection, table: str, index: str
) -> None:
    names = await db_connection.run_sync(
        lambda sync: {item["name"] for item in inspect(sync).get_indexes(table)}
    )
    assert index in names


@pytest.mark.parametrize(
    ("index", "method"),
    [
        ("ix_listings_phone_hashes", "gin"),
        ("ix_listings_title_trgm", "gin"),
        ("ix_listings_landmark_trgm", "gin"),
        ("ix_listings_feed", "btree"),
    ],
)
async def test_indexes_use_the_right_access_method(
    db_connection: AsyncConnection, index: str, method: str
) -> None:
    """A trigram index silently created as btree would not answer ``q=`` searches."""
    found = (
        await db_connection.execute(
            text(
                "SELECT am.amname FROM pg_class c "
                "JOIN pg_am am ON am.oid = c.relam "
                "WHERE c.relname = :name"
            ),
            {"name": index},
        )
    ).scalar_one()
    assert found == method


async def test_pg_trgm_is_available(db_connection: AsyncConnection) -> None:
    result = await db_connection.execute(text("SELECT similarity('chilonzor', 'chilanzar')"))
    assert result.scalar_one() > 0


async def test_one_raw_message_per_source_and_telegram_id(db_session: AsyncSession) -> None:
    """The constraint that makes ingestion idempotent (SPEC 4.3)."""
    source = Source(tg_chat_id=-100555, username="dupe_test")
    db_session.add(source)
    await db_session.flush()

    db_session.add(RawMessage(source_id=source.id, tg_message_id=1, posted_at=now_utc()))
    await db_session.flush()

    db_session.add(RawMessage(source_id=source.id, tg_message_id=1, posted_at=now_utc()))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_enum_columns_reject_values_outside_the_set(db_session: AsyncSession) -> None:
    """``native_enum=False`` must still produce a real CHECK constraint.

    ``swap`` is the same length as ``sale``, so this fails the constraint rather
    than the column width — which is what we actually want to prove.
    """
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO listings (id, deal_type, property_type, building_type, "
                "renovation, status, title, negotiable, quality_score, confidence, "
                "needs_review, version, phone_hashes) VALUES (:id, 'swap', 'apartment', "
                "'unknown', 'unknown', 'active', 't', false, 0, 0, false, 1, '{}')"
            ),
            {"id": str(uuid.uuid4())},
        )
    await db_session.rollback()


async def test_a_listing_round_trips_through_the_orm(db_session: AsyncSession) -> None:
    listing = Listing(
        deal_type=DealType.SALE,
        district=District.CHILONZOR,
        title="3 xonali kvartira, Chilonzor, 75 m²",
        rooms=3,
        phone_hashes=["a" * 64],
    )
    db_session.add(listing)
    await db_session.flush()

    stored = (
        await db_session.execute(select(Listing).where(Listing.id == listing.id))
    ).scalar_one()

    assert isinstance(stored.id, uuid.UUID)
    assert stored.deal_type is DealType.SALE
    assert stored.district is District.CHILONZOR
    assert stored.status is ListingStatus.ACTIVE
    assert stored.version == 1
    assert stored.phone_hashes == ["a" * 64]
    assert stored.first_seen_at is not None
