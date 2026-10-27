"""Test doubles for everything the collector talks to outside the database.

``FakeGateway`` implements the whole ``TelegramGateway`` protocol in memory, so
the ingest path — albums, edits, deletions, gap recovery, flood waits — is
exercised end to end without a single network call (CLAUDE.md: no test may call
real Telegram).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from uyhub.collector.gateway import DeletionHandler, MessageHandler
from uyhub.collector.types import DeletedMessages, IncomingMedia, IncomingMessage, ResolvedChat
from uyhub.core.clock import now_utc


def make_message(
    *,
    chat_id: int = -100123,
    message_id: int = 1,
    text: str = "3 xonali kvartira sotiladi. Narxi 65 000$",
    photos: int = 0,
    grouped_id: int | None = None,
    posted_at: datetime | None = None,
    edited_at: datetime | None = None,
    from_self: bool = False,
    video: bool = False,
) -> IncomingMessage:
    """Build an :class:`IncomingMessage` with sensible defaults."""
    media = [
        IncomingMedia(kind="photo", message_id=message_id + index, size_bytes=1024)
        for index in range(photos)
    ]
    if video:
        media.append(IncomingMedia(kind="video", message_id=message_id, size_bytes=5_000_000))

    return IncomingMessage(
        chat_id=chat_id,
        message_id=message_id,
        posted_at=posted_at or now_utc() - timedelta(minutes=1),
        text=text,
        grouped_id=grouped_id,
        edited_at=edited_at,
        media=media,
        raw={"id": message_id, "chat_id": chat_id},
        from_self=from_self,
    )


class FakeGateway:
    """In-memory :class:`~uyhub.collector.gateway.TelegramGateway`."""

    def __init__(self, *, photo_bytes: bytes = b"\xff\xd8\xff-fake-jpeg") -> None:
        self.history: dict[int, list[IncomingMessage]] = {}
        self.photo_bytes = photo_bytes
        self.started = False
        self.stopped = False

        # Scripted behaviour for the failure paths.
        self.join_error: Exception | None = None
        self.join_result: ResolvedChat | None = None
        self.missing_photos: set[tuple[int, int]] = set()

        self.joined: list[str] = []
        self.downloads: list[tuple[int, int]] = []

        self._on_new: list[MessageHandler] = []
        self._on_album: list[MessageHandler] = []
        self._on_edited: list[MessageHandler] = []
        self._on_deleted: list[DeletionHandler] = []

    # -- test helpers -------------------------------------------------------

    def seed(self, chat_id: int, *messages: IncomingMessage) -> None:
        self.history.setdefault(chat_id, []).extend(messages)

    async def emit_new(self, message: IncomingMessage) -> None:
        for handler in self._on_new:
            await handler(message)

    async def emit_album(self, message: IncomingMessage) -> None:
        for handler in self._on_album:
            await handler(message)

    async def emit_edited(self, message: IncomingMessage) -> None:
        for handler in self._on_edited:
            await handler(message)

    async def emit_deleted(self, deletion: DeletedMessages) -> None:
        for handler in self._on_deleted:
            await handler(deletion)

    # -- TelegramGateway ----------------------------------------------------

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def resolve(self, ref: str) -> ResolvedChat:
        return self.join_result or ResolvedChat(chat_id=-100123, title=ref, kind="supergroup")

    async def join(self, ref: str) -> ResolvedChat:
        if self.join_error is not None:
            raise self.join_error
        self.joined.append(ref)
        return self.join_result or ResolvedChat(
            chat_id=-100123, title=ref, username=ref.lstrip("@"), kind="supergroup"
        )

    async def leave(self, chat_id: int) -> None:
        self.history.pop(chat_id, None)

    async def fetch_since(
        self, chat_id: int, *, min_id: int = 0, limit: int | None = None
    ) -> list[IncomingMessage]:
        messages = [
            message
            for message in sorted(self.history.get(chat_id, []), key=lambda m: m.message_id)
            if message.message_id > min_id
        ]
        return messages[:limit] if limit is not None else messages

    async def fetch_recent(
        self, chat_id: int, *, since: datetime, limit: int | None = None
    ) -> list[IncomingMessage]:
        messages = [
            message
            for message in sorted(self.history.get(chat_id, []), key=lambda m: m.message_id)
            if message.posted_at >= since
        ]
        return messages[-limit:] if limit is not None else messages

    async def download_photo(self, chat_id: int, message_id: int) -> bytes | None:
        self.downloads.append((chat_id, message_id))
        if (chat_id, message_id) in self.missing_photos:
            return None
        return self.photo_bytes

    def on_new_message(self, handler: MessageHandler) -> None:
        self._on_new.append(handler)

    def on_album(self, handler: MessageHandler) -> None:
        self._on_album.append(handler)

    def on_edited(self, handler: MessageHandler) -> None:
        self._on_edited.append(handler)

    def on_deleted(self, handler: DeletionHandler) -> None:
        self._on_deleted.append(handler)


class FakePhotoStore:
    """Collects uploads instead of talking to MinIO."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data
