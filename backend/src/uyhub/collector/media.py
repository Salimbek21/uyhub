"""Photo storage for the collector (SPEC 4.5).

Originals go to the private ``uyhub-raw`` bucket exactly as Telegram sent them.
Resizing, webp conversion and perceptual hashing happen later, in the parser,
when a listing is actually created — doing it here would burn CPU on the 70% of
posts that turn out not to be listings at all.
"""

from __future__ import annotations

from typing import Protocol

from uyhub.core.config import Settings, get_settings
from uyhub.core.logging import get_logger
from uyhub.core.s3 import s3_client

log = get_logger(__name__)

CONTENT_TYPE = "image/jpeg"


def raw_key(source_id: int, tg_message_id: int, index: int) -> str:
    """Object key for one original photo (SPEC 4.5)."""
    return f"raw/{source_id}/{tg_message_id}/{index}.jpg"


class PhotoStore(Protocol):
    """Where downloaded originals are put. Faked in tests."""

    async def put(self, key: str, data: bytes) -> None: ...


class S3PhotoStore:
    """:class:`PhotoStore` backed by MinIO."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def put(self, key: str, data: bytes) -> None:
        async with s3_client(self._settings) as client:
            await client.put_object(
                Bucket=self._settings.s3_bucket_raw,
                Key=key,
                Body=data,
                ContentType=CONTENT_TYPE,
            )
