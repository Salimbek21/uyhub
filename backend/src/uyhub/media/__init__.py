"""Photo processing (SPEC 7.3).

Originals stay private in ``uyhub-raw`` exactly as Telegram sent them. This
package produces the public ``large`` and ``thumb`` webp derivatives and the
two fingerprints dedup matches on.
"""

from uyhub.media.phash import hamming_distance, phash
from uyhub.media.process import ProcessedImage, StoredPhoto, process_and_store, process_image

__all__ = [
    "ProcessedImage",
    "StoredPhoto",
    "hamming_distance",
    "phash",
    "process_and_store",
    "process_image",
]
