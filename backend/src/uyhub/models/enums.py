"""Enumerated values shared by the models, the API and the parser.

Every one of these is stored as a ``VARCHAR`` with a ``CHECK`` constraint rather
than a native PostgreSQL ``ENUM`` type: adding a value then costs an ordinary
migration instead of ``ALTER TYPE``, which cannot run inside a transaction with
other DDL. See docs/DECISIONS.md.

The string values are the wire format. They must stay identical to the unions in
``miniapp/src/types.ts`` and to the ids in docs/SPEC.md sections 3 and 6.5.
"""

from __future__ import annotations

from enum import StrEnum


class AccountStatus(StrEnum):
    """Lifecycle of a userbot account (SPEC 3 ``tg_accounts``)."""

    ACTIVE = "active"
    FLOOD_WAIT = "flood_wait"
    BANNED = "banned"
    DISABLED = "disabled"


class SourceKind(StrEnum):
    """What kind of chat a source is."""

    CHANNEL = "channel"
    GROUP = "group"
    SUPERGROUP = "supergroup"


class SourceStatus(StrEnum):
    """Lifecycle of a source (SPEC 4.2)."""

    PENDING_JOIN = "pending_join"
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    LEFT = "left"


class RawMessageStatus(StrEnum):
    """Where a collected message sits in the parsing pipeline (SPEC 3)."""

    PENDING = "pending"
    REJECTED_PREFILTER = "rejected_prefilter"
    REJECTED_LLM = "rejected_llm"
    PARSED = "parsed"
    FAILED = "failed"


class DealType(StrEnum):
    SALE = "sale"
    RENT = "rent"


class PropertyType(StrEnum):
    APARTMENT = "apartment"
    HOUSE = "house"
    LAND = "land"
    COMMERCIAL = "commercial"
    ROOM = "room"
    OTHER = "other"


class BuildingType(StrEnum):
    BRICK = "brick"
    PANEL = "panel"
    MONOLITH = "monolith"
    OTHER = "other"
    UNKNOWN = "unknown"


class Renovation(StrEnum):
    EURO = "euro"
    GOOD = "good"
    COSMETIC = "cosmetic"
    NEEDS_REPAIR = "needs_repair"
    NONE = "none"
    UNKNOWN = "unknown"


class Currency(StrEnum):
    USD = "USD"
    UZS = "UZS"


class PricePeriod(StrEnum):
    """Rent period. ``NULL`` for sale listings."""

    MONTH = "month"
    DAY = "day"


class District(StrEnum):
    """The twelve districts of Tashkent (SPEC 6.5)."""

    BEKTEMIR = "bektemir"
    CHILONZOR = "chilonzor"
    MIROBOD = "mirobod"
    MIRZO_ULUGBEK = "mirzo_ulugbek"
    OLMAZOR = "olmazor"
    SERGELI = "sergeli"
    SHAYXONTOHUR = "shayxontohur"
    UCHTEPA = "uchtepa"
    YAKKASAROY = "yakkasaroy"
    YASHNOBOD = "yashnobod"
    YUNUSOBOD = "yunusobod"
    YANGIHAYOT = "yangihayot"


class ListingStatus(StrEnum):
    """Listing lifecycle (SPEC section 8)."""

    ACTIVE = "active"
    SOLD = "sold"
    EXPIRED = "expired"
    REMOVED = "removed"


class Language(StrEnum):
    UZ = "uz"
    RU = "ru"


class SavedSearchMode(StrEnum):
    INSTANT = "instant"
    DAILY = "daily"


class SuppressionReason(StrEnum):
    """Why a phone number is on the suppression list (SPEC 3)."""

    SELLER_REQUEST = "seller_request"
    ADMIN = "admin"
    SPAM = "spam"
