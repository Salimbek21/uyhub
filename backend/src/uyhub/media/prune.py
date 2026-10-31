"""Deleting the stored photos nobody will ever read again.

Measured on the first 120 collected posts, object storage was 655 MB against a
10 MB database, and **84% of it was originals** — full-size files downloaded
from Telegram, converted to webp once, and then never touched again. They are
never served: the Mini App only ever loads the derivatives. At the collection
rate those 2 sources implied, 30 sources would add roughly 4 GB of originals a
day, which fills any affordable disk in weeks.

So originals are kept for `MEDIA_ORIGINAL_RETENTION_DAYS` and then deleted.
The window exists for one reason: if the conversion pipeline turns out to be
wrong — bad dimensions, a stripped colour profile, a bug in the hash — there is
a week in which it can be rerun. After that nobody is going to.

Two things are deliberately careful here, because this is the only code in the
system that destroys data irreversibly:

* an original whose derivatives were never written is **never** deleted, no
  matter how old. That is the one case where the original is still the only
  copy of the picture.
* deletion is driven by what the database says, not by what is in the bucket,
  so a listing that still points at a file cannot have it pulled away.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.core.clock import now_utc
from uyhub.core.config import Settings
from uyhub.core.logging import get_logger
from uyhub.core.s3 import s3_client
from uyhub.models.listing import ListingPhoto

log = get_logger(__name__)

DELETE_BATCH = 1000
"""S3 `delete_objects` takes at most a thousand keys per call."""

SCAN_LIMIT = 5_000
"""How many photos one run will consider. A cap rather than a full sweep so a
first run on a large backlog cannot hold a transaction open for minutes; the
job runs every few hours and will catch up across several passes."""


@dataclass(frozen=True, slots=True)
class PruneResult:
    deleted: int
    skipped_unprocessed: int


async def prune_originals(session: AsyncSession, *, settings: Settings) -> PruneResult:
    """Delete originals older than the retention window. Returns what happened."""
    cutoff = now_utc() - timedelta(days=settings.media_original_retention_days)

    # `original_pruned_at` is what stops a second run from trying to delete the
    # same keys again: the column, not the bucket, is the record of what has
    # been reclaimed.
    rows = (
        await session.execute(
            select(ListingPhoto.id, ListingPhoto.s3_key_original, ListingPhoto.s3_key_large)
            .where(
                ListingPhoto.original_pruned_at.is_(None),
                ListingPhoto.created_at < cutoff,
            )
            .limit(SCAN_LIMIT)
        )
    ).all()

    if not rows:
        return PruneResult(deleted=0, skipped_unprocessed=0)

    # The derivative is the copy we keep. Without one, the original is the only
    # copy of the photograph and is left alone however old it is.
    ready = [(photo_id, key) for photo_id, key, large in rows if large and key]
    skipped = len(rows) - len(ready)

    if skipped:
        log.warning(
            "media.prune_skipped_unprocessed",
            count=skipped,
            detail="originals with no derivative are never deleted",
        )

    if not ready:
        return PruneResult(deleted=0, skipped_unprocessed=skipped)

    deleted = await _delete_keys([key for _, key in ready], settings=settings)

    await session.execute(
        update(ListingPhoto)
        .where(ListingPhoto.id.in_([photo_id for photo_id, _ in ready]))
        .values(original_pruned_at=now_utc())
    )

    log.info(
        "media.originals_pruned",
        deleted=deleted,
        retention_days=settings.media_original_retention_days,
    )
    return PruneResult(deleted=deleted, skipped_unprocessed=skipped)


async def prune_orphans(session: AsyncSession, *, settings: Settings) -> PruneResult:
    """Delete originals that no listing ever claimed.

    This is the larger half of the problem and is easy to miss. The collector
    downloads every photo of every message it ingests, but a photo only gets a
    `listing_photos` row if its message became a listing *and* the photo
    survived deduplication and the per-listing cap. Measured on the first 120
    posts: 934 originals downloaded, 229 attached. **Three quarters of the
    bytes belonged to nothing** — cross-posts of the same flat, posts the
    prefilter rejected, photos past the cap.

    Driven by the bucket rather than the database, because by definition these
    objects have no row to find them by. The age check is on the object's own
    `LastModified`, so a photo downloaded moments ago cannot be deleted in the
    window between its upload and its row being written.
    """
    cutoff = now_utc() - timedelta(days=settings.media_original_retention_days)

    # Everything a listing still points at. Rows already pruned are excluded:
    # their objects are gone, so protecting them would only waste memory.
    claimed = set(
        (
            await session.execute(
                select(ListingPhoto.s3_key_original).where(
                    ListingPhoto.original_pruned_at.is_(None)
                )
            )
        ).scalars()
    )

    orphans: list[str] = []
    async with s3_client(settings) as s3:
        token: str | None = None
        while len(orphans) < SCAN_LIMIT:
            kwargs: dict[str, object] = {"Bucket": settings.s3_bucket_raw, "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            page = await s3.list_objects_v2(**kwargs)  # type: ignore[arg-type]

            for obj in page.get("Contents", []):
                key = str(obj["Key"])
                if key not in claimed and obj["LastModified"] < cutoff:
                    orphans.append(key)

            if not page.get("IsTruncated"):
                break
            token = str(page["NextContinuationToken"])

    if not orphans:
        return PruneResult(deleted=0, skipped_unprocessed=0)

    deleted = await _delete_keys(orphans, settings=settings)
    log.info("media.orphans_pruned", deleted=deleted)
    return PruneResult(deleted=deleted, skipped_unprocessed=0)


async def _delete_keys(keys: list[str], *, settings: Settings) -> int:
    """Remove objects from the private bucket, a thousand at a time."""
    removed = 0
    async with s3_client(settings) as s3:
        for start in range(0, len(keys), DELETE_BATCH):
            batch = keys[start : start + DELETE_BATCH]
            response = await s3.delete_objects(
                Bucket=settings.s3_bucket_raw,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )
            # A key that is already gone is not an error — it means a previous
            # run deleted the object and failed before recording it.
            errors = [e for e in response.get("Errors", []) if e.get("Code") != "NoSuchKey"]
            if errors:
                log.warning("media.prune_partial_failure", count=len(errors))
            removed += len(batch) - len(errors)
    return removed
