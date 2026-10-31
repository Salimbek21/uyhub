"""Turning stored object keys into URLs a browser can load.

Two buckets, and the difference is the point (SPEC 9.3): derivatives live in a
public bucket Caddy serves directly with long cache headers, while originals —
which carry whatever the photographer's camera put in them — stay private and
are only ever read by our own workers through signed S3 calls.

So this module maps ``s3_key_large`` and ``s3_key_thumb`` and deliberately has
no way to address ``s3_key_original``.
"""

from __future__ import annotations

from uyhub.core.config import Settings


def public_url(key: str | None, *, settings: Settings) -> str | None:
    """A browser-loadable URL for a derivative, or ``None`` if it has none.

    A missing key is normal rather than exceptional: a photo is recorded as
    soon as it is downloaded, and processing writes the derivatives after.
    """
    if not key:
        return None
    return f"{settings.media_public_base_url.rstrip('/')}/{key.lstrip('/')}"
