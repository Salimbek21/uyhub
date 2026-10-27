"""SQLAlchemy models — every table in SPEC section 3.

Every model module must be imported here so Alembic autogenerate sees it;
``migrations/env.py`` reads ``Base.metadata`` and nothing else.

One table from SPEC section 3 is deliberately absent: ``contact_reveals``. It
audits an endpoint that does not exist, because phone numbers are never served
(docs/DECISIONS.md, OPEN_QUESTIONS C1).
"""

from uyhub.models.base import Base, IdMixin, TimestampMixin, UuidMixin
from uyhub.models.listing import Listing, ListingPhoto, ListingSource, PriceHistory
from uyhub.models.ops import ExchangeRate, LlmCall, SuppressedPhone
from uyhub.models.telegram import RawMessage, Source, TgAccount
from uyhub.models.user import Favorite, NotificationLog, SavedSearch, User

__all__ = [
    "Base",
    "ExchangeRate",
    "Favorite",
    "IdMixin",
    "Listing",
    "ListingPhoto",
    "ListingSource",
    "LlmCall",
    "NotificationLog",
    "PriceHistory",
    "RawMessage",
    "SavedSearch",
    "Source",
    "SuppressedPhone",
    "TgAccount",
    "TimestampMixin",
    "User",
    "UuidMixin",
]
