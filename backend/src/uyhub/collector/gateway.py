"""The only module that imports Telethon.

Everything else in the collector talks to :class:`TelegramGateway`, so the ingest
logic can be driven end to end by a fake in tests and so a future switch of
Telegram library stays contained here.

The userbot is read-only. There is deliberately no method on this interface that
sends, forwards, reacts or edits anything (CLAUDE.md "Hard safety rules").
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from uyhub.collector.types import (
    ChatKind,
    DeletedMessages,
    IncomingMedia,
    IncomingMessage,
    MediaKind,
    ResolvedChat,
)
from uyhub.core.logging import get_logger

if TYPE_CHECKING:
    from telethon import TelegramClient
    from telethon.tl.custom.message import Message

log = get_logger(__name__)

MessageHandler = Callable[[IncomingMessage], Awaitable[None]]
DeletionHandler = Callable[[DeletedMessages], Awaitable[None]]

MAX_PHOTO_BYTES = 5 * 1024 * 1024
"""Largest photo we download (SPEC 4.5). Bigger ones are recorded as metadata."""

MAX_PHOTOS_PER_POST = 10
"""Album photos beyond this are recorded but not downloaded (SPEC 4.5)."""


class TelegramGateway(Protocol):
    """What the collector needs from Telegram. Read-only by construction."""

    async def start(self) -> None:
        """Connect using the existing session. Must not prompt for login."""
        ...

    async def stop(self) -> None: ...

    async def resolve(self, ref: str) -> ResolvedChat:
        """Look up a chat by ``@username``, ``t.me`` link or invite link."""
        ...

    async def join(self, ref: str) -> ResolvedChat:
        """Join a public chat or accept an invite link."""
        ...

    async def leave(self, chat_id: int) -> None: ...

    async def fetch_since(
        self, chat_id: int, *, min_id: int = 0, limit: int | None = None
    ) -> list[IncomingMessage]:
        """Messages newer than ``min_id``, oldest first, albums folded together."""
        ...

    async def fetch_recent(
        self, chat_id: int, *, since: datetime, limit: int | None = None
    ) -> list[IncomingMessage]:
        """Messages posted after ``since``, oldest first.

        Used on a first join, where ``min_id`` is 0 and walking forward from the
        beginning could mean years of history.
        """
        ...

    async def download_photo(self, chat_id: int, message_id: int) -> bytes | None:
        """Largest size of the photo on that message, or ``None`` if too big."""
        ...

    def on_new_message(self, handler: MessageHandler) -> None: ...

    def on_album(self, handler: MessageHandler) -> None: ...

    def on_edited(self, handler: MessageHandler) -> None: ...

    def on_deleted(self, handler: DeletionHandler) -> None: ...


def _media_of(message: Message) -> list[IncomingMedia]:
    """Describe a message's attachment without downloading anything."""
    file = getattr(message, "file", None)
    size = getattr(file, "size", None)
    width = getattr(file, "width", None)
    height = getattr(file, "height", None)

    kind: MediaKind
    if message.photo is not None:
        kind = "photo"
    elif message.video is not None:
        kind = "video"
    elif message.document is not None:
        kind = "document"
    else:
        return []

    return [
        IncomingMedia(
            kind=kind,
            message_id=message.id,
            size_bytes=size,
            width=width,
            height=height,
        )
    ]


def _trimmed_raw(message: Message) -> dict[str, Any]:
    """The few Telethon fields worth keeping for debugging and reparsing.

    Deliberately not the whole object: it carries sender names and phone numbers
    that SPEC 13 says we must not store.
    """
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "grouped_id": message.grouped_id,
        "date": message.date.isoformat() if message.date else None,
        "edit_date": message.edit_date.isoformat() if message.edit_date else None,
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "has_media": message.media is not None,
    }


def _to_incoming(message: Message) -> IncomingMessage:
    posted_at: datetime = message.date
    return IncomingMessage(
        chat_id=message.chat_id,
        message_id=message.id,
        posted_at=posted_at,
        text=message.text or "",
        grouped_id=message.grouped_id,
        edited_at=message.edit_date,
        media=_media_of(message),
        raw=_trimmed_raw(message),
        from_self=bool(getattr(message, "out", False)),
    )


def fold_album(messages: list[Message]) -> IncomingMessage:
    """Collapse an album into one :class:`IncomingMessage`.

    The row keeps the first message's id and the caption, which in an album sits
    on exactly one of the messages — usually but not always the first.
    """
    ordered = sorted(messages, key=lambda item: item.id)
    first = ordered[0]
    caption = next((item.text for item in ordered if item.text), "")

    media: list[IncomingMedia] = []
    for item in ordered:
        media.extend(_media_of(item))

    return IncomingMessage(
        chat_id=first.chat_id,
        message_id=first.id,
        posted_at=first.date,
        text=caption,
        grouped_id=first.grouped_id,
        edited_at=first.edit_date,
        media=media,
        raw={**_trimmed_raw(first), "album_size": len(ordered)},
        from_self=bool(getattr(first, "out", False)),
    )


class TelethonGateway:
    """:class:`TelegramGateway` backed by a real Telethon client."""

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def start(self) -> None:
        from uyhub.core.errors import UyHubError

        await self._client.connect()
        if not await self._client.is_user_authorized():
            msg = "Telethon session is missing or expired; run `make login-userbot`"
            raise UyHubError(msg)

    async def stop(self) -> None:
        await self._client.disconnect()

    async def resolve(self, ref: str) -> ResolvedChat:
        from telethon import utils

        entity = await self._client.get_entity(ref)
        return _describe(entity, utils.get_peer_id(entity))

    async def join(self, ref: str) -> ResolvedChat:
        from telethon import utils
        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.tl.functions.messages import ImportChatInviteRequest

        invite_hash = _invite_hash(ref)
        if invite_hash is not None:
            from telethon.errors import UserAlreadyParticipantError

            try:
                await self._client(ImportChatInviteRequest(invite_hash))
            except UserAlreadyParticipantError:
                log.info("collector.join_already_member")
            entity = await self._client.get_entity(ref)
        else:
            entity = await self._client.get_entity(ref)
            await self._client(JoinChannelRequest(entity))

        return _describe(entity, utils.get_peer_id(entity))

    async def leave(self, chat_id: int) -> None:
        from telethon.tl.functions.channels import LeaveChannelRequest

        entity = await self._client.get_entity(chat_id)
        await self._client(LeaveChannelRequest(entity))

    async def fetch_since(
        self, chat_id: int, *, min_id: int = 0, limit: int | None = None
    ) -> list[IncomingMessage]:
        entity = await self._client.get_entity(chat_id)
        collected: list[Message] = []
        async for message in self._client.iter_messages(
            entity, min_id=min_id, reverse=True, limit=limit
        ):
            collected.append(message)
        return _fold_consecutive_albums(collected)

    async def fetch_recent(
        self, chat_id: int, *, since: datetime, limit: int | None = None
    ) -> list[IncomingMessage]:
        entity = await self._client.get_entity(chat_id)
        collected: list[Message] = []
        # Newest first, stopping as soon as we are past the window, so a channel
        # with five years of history costs one page rather than all of it.
        async for message in self._client.iter_messages(entity, limit=limit):
            if message.date is not None and message.date < since:
                break
            collected.append(message)
        collected.reverse()
        return _fold_consecutive_albums(collected)

    async def download_photo(self, chat_id: int, message_id: int) -> bytes | None:
        entity = await self._client.get_entity(chat_id)
        messages = await self._client.get_messages(entity, ids=[message_id])
        message = messages[0] if messages else None
        if message is None or message.photo is None:
            return None

        size = getattr(getattr(message, "file", None), "size", None)
        if size is not None and size > MAX_PHOTO_BYTES:
            log.info(
                "collector.photo_too_large",
                tg_message_id=message_id,
                size_bytes=size,
            )
            return None

        data = await self._client.download_media(message, file=bytes)
        return data if isinstance(data, bytes) else None

    def on_new_message(self, handler: MessageHandler) -> None:
        from telethon import events

        async def callback(event: Any) -> None:
            # Albums arrive once per message here and once as an Album event;
            # only the Album handler should see them (SPEC 4.3).
            if event.message.grouped_id is not None:
                return
            await handler(_to_incoming(event.message))

        self._client.add_event_handler(callback, events.NewMessage())

    def on_album(self, handler: MessageHandler) -> None:
        from telethon import events

        async def callback(event: Any) -> None:
            await handler(fold_album(list(event.messages)))

        self._client.add_event_handler(callback, events.Album())

    def on_edited(self, handler: MessageHandler) -> None:
        from telethon import events

        async def callback(event: Any) -> None:
            await handler(_to_incoming(event.message))

        self._client.add_event_handler(callback, events.MessageEdited())

    def on_deleted(self, handler: DeletionHandler) -> None:
        from telethon import events

        async def callback(event: Any) -> None:
            await handler(
                DeletedMessages(message_ids=list(event.deleted_ids), chat_id=event.chat_id)
            )

        self._client.add_event_handler(callback, events.MessageDeleted())


def _describe(entity: Any, chat_id: int) -> ResolvedChat:
    megagroup = bool(getattr(entity, "megagroup", False))
    broadcast = bool(getattr(entity, "broadcast", False))
    kind: ChatKind
    if megagroup:
        kind = "supergroup"
    elif broadcast:
        kind = "channel"
    else:
        kind = "group"
    return ResolvedChat(
        chat_id=chat_id,
        title=getattr(entity, "title", None),
        username=getattr(entity, "username", None),
        kind=kind,
    )


def _invite_hash(ref: str) -> str | None:
    """Extract the hash from ``t.me/+abc`` or ``t.me/joinchat/abc``, else ``None``."""
    cleaned = ref.strip()
    for marker in ("t.me/joinchat/", "t.me/+"):
        if marker in cleaned:
            return cleaned.split(marker, 1)[1].split("?", 1)[0].strip("/")
    if cleaned.startswith("+"):
        return cleaned[1:]
    return None


def _fold_consecutive_albums(messages: list[Message]) -> list[IncomingMessage]:
    """Group runs of messages that share a ``grouped_id`` into single objects."""
    result: list[IncomingMessage] = []
    buffer: list[Message] = []

    def flush() -> None:
        if buffer:
            result.append(fold_album(buffer) if len(buffer) > 1 else _to_incoming(buffer[0]))
            buffer.clear()

    for message in messages:
        if message.grouped_id is None:
            flush()
            result.append(_to_incoming(message))
            continue
        if buffer and buffer[0].grouped_id != message.grouped_id:
            flush()
        buffer.append(message)

    flush()
    return result
