"""Opaque cursors for the feed (SPEC 9.2).

Keyset pagination, not ``OFFSET``: SPEC 9.3 asks for p95 under 200 ms with
200k listings, and ``OFFSET 10000`` makes Postgres walk ten thousand rows it
then throws away. A cursor instead carries the sort value and id of the last
row returned, so every page is an index range scan of the same cost.

The cursor is opaque to the client but not secret — it holds nothing the caller
did not already send or receive. It is not signed, because forging one can only
produce a different page of public listings.

It does carry a fingerprint of the filters it was issued under. Without it,
changing a filter and paging on would silently splice two different result sets
together; with it the server can say so (DECISIONS 4.2).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any

FILTER_FINGERPRINT_LENGTH = 12
"""Long enough that filter sets do not collide, short enough to keep the
cursor small. A collision would only mean a confusing page, never wrong data
leaving the database."""


class CursorError(Exception):
    """The cursor is unreadable, or belongs to a different query."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Cursor:
    """Where the previous page stopped."""

    sort: str
    """The sort the cursor was issued under. Changing sort invalidates it."""

    key: str | None
    """The last row's sort value, as a string. ``None`` when that row sorted
    into the nulls-last tail — listings with no price, for instance."""

    listing_id: str
    """Breaks ties, and makes the ordering total. Without it two listings with
    the same price could each be skipped or repeated at a page boundary."""

    fingerprint: str
    """Of the filters, see module docstring."""


def fingerprint_filters(values: dict[str, Any]) -> str:
    """A stable short hash of the filter set.

    ``sort_keys`` and ``default=str`` make this deterministic across processes
    and over values Python's JSON encoder does not handle (``Decimal``, enum
    members), which matters because the next page is usually served by a
    different worker.
    """
    encoded = json.dumps(values, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.blake2b(encoded.encode(), digest_size=16).hexdigest()
    return digest[:FILTER_FINGERPRINT_LENGTH]


def encode(cursor: Cursor) -> str:
    payload = json.dumps(
        {"s": cursor.sort, "k": cursor.key, "i": cursor.listing_id, "f": cursor.fingerprint},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode(raw: str, *, sort: str, fingerprint: str) -> Cursor:
    """Read a cursor back, refusing one issued for a different query."""
    padding = "=" * (-len(raw) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw + padding))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CursorError("malformed_cursor") from exc

    if not isinstance(payload, dict):
        raise CursorError("malformed_cursor")

    key = payload.get("k")
    listing_id = payload.get("i")
    if not isinstance(listing_id, str) or not (key is None or isinstance(key, str)):
        raise CursorError("malformed_cursor")

    if payload.get("s") != sort:
        raise CursorError("sort_changed")
    if payload.get("f") != fingerprint:
        raise CursorError("filters_changed")

    return Cursor(sort=sort, key=key, listing_id=listing_id, fingerprint=fingerprint)
