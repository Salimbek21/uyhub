"""Building the feed query (SPEC 9.2).

Kept apart from the router so the hard part — translating filters into SQL and
paging without ``OFFSET`` — can be read and tested on its own.

Two things here are easy to get subtly wrong and are therefore spelled out:

*Nulls.* A listing with no price still exists and still deserves to be listed,
so price sorts put nulls last rather than dropping the rows. That makes the
keyset predicate asymmetric: once paging reaches the null tail there is no
value left to compare, only ids.

*Total order.* Sorting by price alone is not a total order — two flats at
$65,000 could each be skipped or repeated at a page boundary depending on which
way the planner happened to return them. Every sort therefore ends in ``id``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, SQLColumnExpression, and_, func, literal_column, or_, select
from sqlalchemy.sql.elements import ColumnElement

from uyhub.api.cursor import Cursor, CursorError, fingerprint_filters
from uyhub.models.enums import DealType, District, ListingStatus, PropertyType
from uyhub.models.listing import Listing, ListingPhoto

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 50
"""SPEC 9.2."""


class Sort(StrEnum):
    NEW = "new"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    PRICE_PER_M2 = "price_per_m2"


def price_per_m2_expression() -> ColumnElement[Decimal | None]:
    """Price per square metre, null when there is no area to divide by.

    ``NULLIF`` guards the zero rather than a ``CASE``, because the expression
    has to match the index definition for Postgres to use it.

    The zero is a ``literal_column`` and not a plain ``0`` on purpose: passing
    it as a bind parameter renders ``nullif(area_m2, $1)``, and a parameter is
    not a constant when the planner decides whether an expression index
    applies — so the index would simply never be used.
    """
    return Listing.price_usd / func.nullif(Listing.area_m2, literal_column("0"))


@dataclass(frozen=True, slots=True)
class FeedFilters:
    """Everything ``GET /v1/listings`` accepts."""

    deal_type: DealType | None = None
    property_type: PropertyType | None = None
    districts: tuple[District, ...] = ()
    rooms_min: int | None = None
    rooms_max: int | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    area_min: Decimal | None = None
    area_max: Decimal | None = None
    has_photos: bool = False
    q: str | None = None
    sort: Sort = Sort.NEW

    def fingerprint(self) -> str:
        """Identifies this filter set, so a cursor cannot cross into another.

        The sort is deliberately excluded — the cursor records it separately
        and reports a changed sort as its own, clearer error.
        """
        return fingerprint_filters(
            {
                "deal_type": self.deal_type,
                "property_type": self.property_type,
                "districts": sorted(self.districts),
                "rooms_min": self.rooms_min,
                "rooms_max": self.rooms_max,
                "price_min": self.price_min,
                "price_max": self.price_max,
                "area_min": self.area_min,
                "area_max": self.area_max,
                "has_photos": self.has_photos,
                "q": self.q,
            }
        )


def visible() -> list[ColumnElement[bool]]:
    """What the feed is allowed to show.

    ``needs_review`` means the parser flagged its own reading as implausible —
    a price or an area outside the sanity bands. Showing it would be knowingly
    displaying something we believe is wrong, so it waits for the admin queue
    (DECISIONS 4.4).
    """
    return [Listing.status == ListingStatus.ACTIVE, Listing.needs_review.is_(False)]


def conditions(filters: FeedFilters) -> list[ColumnElement[bool]]:
    """The filter set as SQL, in the order SPEC 9.2 lists it."""
    clauses = visible()

    if filters.deal_type is not None:
        clauses.append(Listing.deal_type == filters.deal_type)
    if filters.property_type is not None:
        clauses.append(Listing.property_type == filters.property_type)
    if filters.districts:
        clauses.append(Listing.district.in_(filters.districts))
    if filters.rooms_min is not None:
        clauses.append(Listing.rooms >= filters.rooms_min)
    if filters.rooms_max is not None:
        clauses.append(Listing.rooms <= filters.rooms_max)
    if filters.price_min is not None:
        clauses.append(Listing.price_usd >= filters.price_min)
    if filters.price_max is not None:
        clauses.append(Listing.price_usd <= filters.price_max)
    if filters.area_min is not None:
        clauses.append(Listing.area_m2 >= filters.area_min)
    if filters.area_max is not None:
        clauses.append(Listing.area_m2 <= filters.area_max)

    if filters.has_photos:
        clauses.append(
            select(ListingPhoto.id).where(ListingPhoto.listing_id == Listing.id).exists()
        )

    if filters.q:
        # Both columns carry a trigram GIN index, which is what makes a
        # leading-wildcard ILIKE indexable at all.
        pattern = f"%{filters.q.strip()}%"
        clauses.append(
            or_(Listing.title.ilike(pattern), Listing.landmark.ilike(pattern)),
        )

    return clauses


def sort_key(sort: Sort) -> SQLColumnExpression[Any]:
    """The column or expression a given sort orders by."""
    if sort is Sort.NEW:
        return Listing.first_seen_at
    if sort is Sort.PRICE_PER_M2:
        return price_per_m2_expression()
    return Listing.price_usd


def order_by(sort: Sort) -> list[SQLColumnExpression[Any]]:
    """The ORDER BY, always ending in ``id`` so the order is total."""
    key = sort_key(sort)
    if sort is Sort.NEW:
        return [key.desc(), Listing.id.asc()]
    if sort is Sort.PRICE_DESC:
        return [key.desc().nullslast(), Listing.id.asc()]
    return [key.asc().nullslast(), Listing.id.asc()]


def after(cursor: Cursor, sort: Sort) -> ColumnElement[bool]:
    """Rows strictly after the one the cursor points at, in sort order."""
    key = sort_key(sort)
    descending = sort in (Sort.NEW, Sort.PRICE_DESC)
    last_id = _listing_id(cursor.listing_id)

    if cursor.key is None:
        # Already in the nulls-last tail: everything before it is behind us,
        # and within the tail only the id orders the rows.
        if sort is Sort.NEW:
            # `first_seen_at` is NOT NULL, so this cursor cannot be genuine.
            return Listing.id > last_id
        return and_(key.is_(None), Listing.id > last_id)

    value = _sort_value(cursor.key, sort)
    beyond = key < value if descending else key > value
    same = and_(key == value, Listing.id > last_id)

    if sort is Sort.NEW:
        return or_(beyond, same)
    # Nulls sort last under both price orders, so the tail is always "after".
    return or_(beyond, same, key.is_(None))


def _sort_value(raw: str, sort: Sort) -> datetime | Decimal:
    """The cursor's key as the type its column actually holds.

    Handing Postgres a string and letting it cast would mostly work and would
    fail on the day a locale or a format changed something underneath us.
    """
    try:
        return datetime.fromisoformat(raw) if sort is Sort.NEW else Decimal(raw)
    except (ValueError, ArithmeticError) as exc:
        raise CursorError("malformed_cursor") from exc


def _listing_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise CursorError("malformed_cursor") from exc


def page_query(filters: FeedFilters, cursor: Cursor | None, limit: int) -> Select[tuple[Listing]]:
    """One page of listings, one row more than asked for.

    The extra row is how the caller learns whether a next page exists without
    a second count; it is dropped before the response is built.
    """
    query = select(Listing).where(*conditions(filters))
    if cursor is not None:
        query = query.where(after(cursor, filters.sort))
    return query.order_by(*order_by(filters.sort)).limit(limit + 1)


def count_query(filters: FeedFilters) -> Select[tuple[int]]:
    """How many listings match, ignoring pagination."""
    return select(func.count()).select_from(Listing).where(*conditions(filters))


def cursor_for(listing: Listing, filters: FeedFilters) -> Cursor:
    """The cursor a client sends back to continue after ``listing``."""
    if filters.sort is Sort.NEW:
        key: str | None = listing.first_seen_at.isoformat()
    elif filters.sort is Sort.PRICE_PER_M2:
        key = _per_m2(listing)
    else:
        key = str(listing.price_usd) if listing.price_usd is not None else None

    return Cursor(
        sort=filters.sort.value,
        key=key,
        listing_id=str(listing.id),
        fingerprint=filters.fingerprint(),
    )


def _per_m2(listing: Listing) -> str | None:
    if listing.price_usd is None or not listing.area_m2:
        return None
    return str(listing.price_usd / listing.area_m2)
