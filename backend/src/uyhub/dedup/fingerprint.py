"""The two fingerprints dedup matches on (SPEC 7.1).

``dedup_key`` is the cheap exact match: a hash of the fields that, taken
together, identify one property. ``simhash`` is the fuzzy one, for reposts that
changed a word or two.

Neither uses Python's built-in ``hash()``. It is salted per process, so the
same text would fingerprint differently after a restart and every stored value
would quietly stop matching.
"""

from __future__ import annotations

import re
from decimal import Decimal
from hashlib import blake2b

from uyhub.models.enums import DealType, District, PropertyType

SIMHASH_BITS = 64
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

SALE_PRICE_ROUNDING = -3
"""Sale prices are compared to the nearest thousand dollars (SPEC 7.1)."""

RENT_PRICE_ROUNDING = -1
"""Rents to the nearest ten."""


def _digest(value: str) -> int:
    return int.from_bytes(blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def dedup_key(
    *,
    phone_hashes: list[str],
    deal_type: DealType | None,
    property_type: PropertyType | None,
    rooms: int | None,
    district: District | None,
    price_usd: Decimal | None,
) -> str | None:
    """The exact-match key, or ``None`` when the post cannot have one.

    SPEC 7.1 builds this from the first phone hash. A post with no phone would
    therefore key on an empty string, and two genuinely different three-room
    flats in Chilonzor at the same price would collapse into one listing —
    which is a wrong answer shown to a user, not merely a missed merge. Without
    a phone the key is ``None`` and matching falls through to rules 3 and 4
    (docs/DECISIONS.md 3.3, OPEN_QUESTIONS B1).
    """
    if not phone_hashes or deal_type is None:
        return None

    rounding = SALE_PRICE_ROUNDING if deal_type is DealType.SALE else RENT_PRICE_ROUNDING
    rounded_price = str(int(round(float(price_usd), rounding))) if price_usd is not None else ""

    parts = (
        sorted(phone_hashes)[0],
        deal_type.value,
        property_type.value if property_type else "",
        str(rooms) if rooms is not None else "",
        district.value if district else "",
        rounded_price,
    )
    return blake2b("|".join(parts).encode("utf-8"), digest_size=16).hexdigest()


def simhash(text: str, *, bits: int = SIMHASH_BITS) -> int:
    """Charikar SimHash of a piece of text.

    Each token votes on every bit of the final value; a repost that changes a
    few words moves only the bits those words dominated. Hamming distance
    between two of these is therefore a measure of how much the text changed,
    which is what SPEC 7.1 rule 3 asks for.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return 0

    weights = [0] * bits
    for token in tokens:
        token_hash = _digest(token)
        for position in range(bits):
            if token_hash >> position & 1:
                weights[position] += 1
            else:
                weights[position] -= 1

    value = 0
    for position in range(bits):
        if weights[position] > 0:
            value |= 1 << position
    return value


def hamming_distance(left: int, right: int) -> int:
    return int((left ^ right).bit_count())


def to_signed_64(value: int) -> int:
    """Map a 64-bit fingerprint into the range a Postgres ``bigint`` accepts."""
    return value - (1 << 64) if value >= (1 << 63) else value


def from_signed_64(value: int) -> int:
    return value + (1 << 64) if value < 0 else value
