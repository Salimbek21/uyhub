"""Uzbek phone numbers: finding them, normalising them, and hashing them.

The hash is the only form that is ever stored. It is what dedup matches on
(SPEC 7.1) and what a removal request suppresses, and keeping the plaintext
would make the database a re-publishable list of numbers collected without
consent (docs/DECISIONS.md P.2).

The hard part is not the format but telling a phone number from a price. Uzbek
posts write prices as nine-digit sums just as often as they write phone numbers
as nine digits — ``650 000 000 so'm`` and ``90 123 45 67`` are both nine digits
once the separators are stripped. Two rules keep them apart: a bare number must
start with a real mobile operator code, and a number followed by a currency word
is a price, whatever it starts with.
"""

from __future__ import annotations

import hmac
import re
from hashlib import sha256

from uyhub.core.config import Settings, get_settings
from uyhub.core.errors import ConfigError

COUNTRY_CODE = "998"
NATIONAL_DIGITS = 9

MOBILE_PREFIXES = frozenset(
    {
        "20",  # Humans / Perfectum
        "33",  # Humans
        "50",  # Perfectum / Ucell
        "55",  # Uzmobile
        "77",  # Ucell
        "88",  # Ucell / Humans
        "90",  # Beeline
        "91",  # Beeline
        "93",  # Ucell
        "94",  # Ucell
        "95",  # Uzmobile
        "97",  # Mobiuz
        "98",  # Mobiuz
        "99",  # Uzmobile
    }
)
"""Mobile operator codes. A bare nine-digit run must start with one of these to
be read as a phone number; ``71`` and the other landline codes are excluded on
purpose, because a Tashkent landline in a listing is rare and ``71`` collides
with far too many prices."""

_SEPARATORS = r"[\s\-().]*"

_CANDIDATE_RE = re.compile(
    rf"""
    (?<![\d])                       # not in the middle of a longer number
    # +998… / 998… / 8998… — the trunk 8 is how a number is dialled from a
    # landline and people paste it into posts that way.
    (?:\+?(?:8{_SEPARATORS})?{COUNTRY_CODE}{_SEPARATORS})?
    (\d{{2}}){_SEPARATORS}
    (\d{{3}}){_SEPARATORS}
    (\d{{2}}){_SEPARATORS}
    (\d{{2}})
    (?![\d])
    """,
    re.VERBOSE,
)

_CURRENCY_AFTER_RE = re.compile(
    r"""^[\s\-–—]{0,3}
    (?:s[ou]['’ʻ`]?m|сум|сўм|usd|\$|y\.?\s?e\.?|у\.?\s?е\.?|
       ming|минг|mln|млн|million|миллион|mlrd|млрд|milliard|миллиард)
    """,
    re.IGNORECASE | re.VERBOSE,
)
"""A number trailed by one of these is a price, not a phone."""


def _resolve(text: str, match: re.Match[str]) -> str | None:
    """The E.164 number this match represents, or ``None`` if it is not one."""
    if _CURRENCY_AFTER_RE.match(text[match.end() : match.end() + 12]):
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return _to_e164(digits, had_country_prefix=_has_country_prefix(match.group(0)))


def find_phones(text: str) -> list[str]:
    """Every phone number in ``text``, as E.164, in order, without duplicates."""
    found: list[str] = []
    for match in _CANDIDATE_RE.finditer(text):
        number = _resolve(text, match)
        if number is not None and number not in found:
            found.append(number)
    return found


def _has_country_prefix(raw: str) -> bool:
    return raw.lstrip("+").replace(" ", "").startswith(COUNTRY_CODE)


def _to_e164(digits: str, *, had_country_prefix: bool) -> str | None:
    """``digits`` is the candidate with separators removed."""
    if digits.startswith("8" + COUNTRY_CODE):
        digits = digits[1:]
    if digits.startswith(COUNTRY_CODE):
        digits = digits[len(COUNTRY_CODE) :]

    if len(digits) != NATIONAL_DIGITS:
        return None

    # With an explicit country code the intent is unambiguous. Without one, the
    # operator code is the only thing separating a phone from a price.
    if not had_country_prefix and digits[:2] not in MOBILE_PREFIXES:
        return None

    return f"+{COUNTRY_CODE}{digits}"


def normalize_phone(raw: str) -> str | None:
    """Normalise a single number, or ``None`` if it is not one."""
    found = find_phones(raw)
    return found[0] if found else None


def hash_phone(phone: str, settings: Settings | None = None) -> str:
    """Keyed HMAC-SHA256 of an E.164 number, hex encoded.

    Keyed rather than plain: the space of Uzbek mobile numbers is small enough
    that an unkeyed hash is reversible by brute force in minutes.
    """
    cfg = settings or get_settings()
    key = cfg.phone_hash_key.get_secret_value()
    if not key:
        msg = "PHONE_HASH_KEY must be set before phone numbers can be hashed"
        raise ConfigError(msg)
    return hmac.new(key.encode(), phone.encode(), sha256).hexdigest()


def hash_phones(phones: list[str], settings: Settings | None = None) -> list[str]:
    """Hash several numbers, preserving order and dropping duplicates."""
    cfg = settings or get_settings()
    hashed: list[str] = []
    for phone in phones:
        digest = hash_phone(phone, cfg)
        if digest not in hashed:
            hashed.append(digest)
    return hashed


def strip_phones(text: str) -> str:
    """Remove phone numbers from text, for the stored description (SPEC 6.3).

    Uses exactly the same decision as :func:`find_phones`, so a price can never
    be deleted from the description by mistake.
    """
    return _CANDIDATE_RE.sub(
        lambda match: "" if _resolve(text, match) is not None else match.group(0),
        text,
    )
