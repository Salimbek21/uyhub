"""Turning a downloaded original into what the Mini App can show (SPEC 7.3).

The collector stores exactly what Telegram sent, in the private ``uyhub-raw``
bucket. Nothing serves that: the files are large, they carry whatever metadata
the photographer's phone attached, and the bucket is deliberately unreadable.

This module makes the two public derivatives — a 1280px ``large`` and a 400px
``thumb``, both webp — and computes the two fingerprints dedup needs. The
transform is deliberately split from the storage: the image work is a pure
function over bytes, so it can be tested without a bucket.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from hashlib import sha256 as _sha256

from PIL import Image

from uyhub.core.config import Settings, get_settings
from uyhub.core.logging import get_logger
from uyhub.core.s3 import s3_client
from uyhub.media.phash import phash, to_signed_64

log = get_logger(__name__)

LARGE_MAX_PX = 1280
THUMB_MAX_PX = 400
WEBP_QUALITY_LARGE = 82
WEBP_QUALITY_THUMB = 75
CONTENT_TYPE = "image/webp"

MAX_PHOTOS_PER_LISTING = 15
"""SPEC 7.2. Past this a listing is a slideshow, not a listing."""


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    """The result of the pure image work."""

    sha256: str
    phash: int
    """Already mapped into the signed range a Postgres ``bigint`` accepts."""

    width: int
    height: int
    large: bytes
    thumb: bytes


@dataclass(frozen=True, slots=True)
class StoredPhoto:
    """A processed image, once its derivatives are in the public bucket."""

    sha256: str
    phash: int
    width: int
    height: int
    s3_key_large: str
    s3_key_thumb: str


def large_key(listing_id: str, position: int) -> str:
    return f"listings/{listing_id}/{position}_large.webp"


def thumb_key(listing_id: str, position: int) -> str:
    return f"listings/{listing_id}/{position}_thumb.webp"


def _fit(image: Image.Image, longest_side: int) -> Image.Image:
    """Scale down so the longest side is at most ``longest_side``.

    Never scales up: a small original stays small rather than being blurred
    into a larger file.
    """
    width, height = image.size
    longest = max(width, height)
    if longest <= longest_side:
        return image.copy()
    scale = longest_side / longest
    return image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS
    )


def process_image(data: bytes) -> ProcessedImage:
    """Fingerprint an original and produce its two derivatives.

    Pure and synchronous; callers run it off the event loop. Metadata is
    dropped by rebuilding the pixels into a fresh image — a photograph's EXIF
    routinely carries GPS coordinates, and SPEC 13 has no room for those.
    """
    digest = _sha256(data).hexdigest()

    with Image.open(io.BytesIO(data)) as opened:
        opened.load()
        fingerprint = to_signed_64(phash(opened))
        width, height = opened.size

        # A new image from the pixel data alone: no EXIF, no ICC profile, no
        # orientation tag. `convert("RGB")` also flattens any alpha, which webp
        # would otherwise keep as a needlessly large file.
        stripped = Image.new("RGB", opened.size)
        stripped.paste(opened.convert("RGB"))

    return ProcessedImage(
        sha256=digest,
        phash=fingerprint,
        width=width,
        height=height,
        large=_encode(_fit(stripped, LARGE_MAX_PX), WEBP_QUALITY_LARGE),
        thumb=_encode(_fit(stripped, THUMB_MAX_PX), WEBP_QUALITY_THUMB),
    )


def _encode(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=quality, method=4)
    return buffer.getvalue()


async def fetch_and_process(
    raw_key: str, *, settings: Settings | None = None
) -> ProcessedImage | None:
    """Download an original and process it, without storing anything.

    Split from storage because dedup needs the perceptual hash *before* it
    knows which listing the photo belongs to — and the public object key
    contains the listing id. Processing once and storing later avoids
    downloading and decoding the same photo twice.

    Returns ``None`` when the original is missing or unreadable: a listing with
    one broken photo is still a listing, and failing the whole merge over it
    would lose the text as well.
    """
    cfg = settings or get_settings()

    try:
        async with s3_client(cfg) as client:
            response = await client.get_object(Bucket=cfg.s3_bucket_raw, Key=raw_key)
            data = await response["Body"].read()
    except Exception as exc:
        log.warning("media.original_unavailable", key=raw_key, error=type(exc).__name__)
        return None

    try:
        # Decoding and resizing are CPU-bound and would stall every other
        # coroutine on this worker (CLAUDE.md "no blocking calls").
        return await asyncio.to_thread(process_image, data)
    except Exception as exc:
        log.warning("media.unreadable_image", key=raw_key, error=type(exc).__name__)
        return None


async def store_derivatives(
    processed: ProcessedImage,
    *,
    listing_id: str,
    position: int,
    settings: Settings | None = None,
) -> StoredPhoto:
    """Publish the two derivatives into the public bucket."""
    cfg = settings or get_settings()
    keys = (large_key(listing_id, position), thumb_key(listing_id, position))

    async with s3_client(cfg) as client:
        for key, body in zip(keys, (processed.large, processed.thumb), strict=True):
            await client.put_object(
                Bucket=cfg.s3_bucket_media, Key=key, Body=body, ContentType=CONTENT_TYPE
            )

    log.info(
        "media.stored",
        listing_id=listing_id,
        position=position,
        bytes_large=len(processed.large),
        bytes_thumb=len(processed.thumb),
    )
    return StoredPhoto(
        sha256=processed.sha256,
        phash=processed.phash,
        width=processed.width,
        height=processed.height,
        s3_key_large=keys[0],
        s3_key_thumb=keys[1],
    )


async def process_and_store(
    raw_key: str,
    *,
    listing_id: str,
    position: int,
    settings: Settings | None = None,
) -> StoredPhoto | None:
    """Fetch, process and publish in one step, for callers that need no hash first."""
    processed = await fetch_and_process(raw_key, settings=settings)
    if processed is None:
        return None
    return await store_derivatives(
        processed, listing_id=listing_id, position=position, settings=settings
    )
