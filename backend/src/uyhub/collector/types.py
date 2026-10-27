"""Normalised shapes the collector works with.

Telethon's own objects never cross into the ingest logic. Everything below is a
plain dataclass, which is what lets the tests drive the whole pipeline with a
fake gateway and no network (CLAUDE.md: "no test may call real Telegram").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

MediaKind = Literal["photo", "video", "document", "other"]
ChatKind = Literal["channel", "group", "supergroup"]


@dataclass(frozen=True, slots=True)
class IncomingMedia:
    """One attachment. Only photos are downloaded in the MVP (SPEC 4.5)."""

    kind: MediaKind
    message_id: int
    """Which message holds it — for an album, every photo has its own message."""

    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None

    @property
    def is_photo(self) -> bool:
        return self.kind == "photo"


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """A new, edited or backfilled post, with an album folded into one object.

    ``message_id`` is the id of the first message of an album, matching the
    ``raw_messages`` convention in SPEC section 3.
    """

    chat_id: int
    message_id: int
    posted_at: datetime
    text: str = ""
    grouped_id: int | None = None
    edited_at: datetime | None = None
    media: list[IncomingMedia] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    from_self: bool = False
    """Messages the userbot itself posted are ignored (SPEC 4.3)."""

    @property
    def photos(self) -> list[IncomingMedia]:
        return [item for item in self.media if item.is_photo]

    @property
    def is_empty(self) -> bool:
        """No text and no photos — a service message or a sticker (SPEC 4.3)."""
        return not self.text.strip() and not self.photos


@dataclass(frozen=True, slots=True)
class DeletedMessages:
    """A deletion notice.

    ``chat_id`` is ``None`` for private chats and small groups: Telegram simply
    does not say where the message was, and Telethon does not guess (SPEC 4.3).
    """

    message_ids: list[int]
    chat_id: int | None = None


@dataclass(frozen=True, slots=True)
class ResolvedChat:
    """What we learn about a chat once the account can see it."""

    chat_id: int
    title: str | None = None
    username: str | None = None
    kind: ChatKind = "channel"
