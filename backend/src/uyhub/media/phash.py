"""Perceptual hashing of photos (SPEC 7.3).

A perceptual hash is what lets dedup rule 4 recognise the same flat reposted by
a different realtor with a different phone number. It must survive the things
Telegram does to a photo — recompression, resizing, a change of format — while
still differing for a genuinely different room.

SPEC names ``imagehash``. This is the same algorithm written out, because that
library depends on scipy and PyWavelets, which is roughly 150 MB of container
for one function (docs/DECISIONS.md 3.2). The properties that matter are tested
directly rather than taken on trust: identical images hash identically, a
resized copy stays within a couple of bits, and different photographs do not.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

HASH_SIZE = 8
"""Side of the low-frequency block kept, so 8x8 = 64 bits."""

SAMPLE_SIZE = 32
"""Side the image is reduced to before the transform. Four times the hash size
is the usual ratio: enough detail for the DCT to be meaningful, small enough
that the transform is trivial."""


def _dct_matrix(size: int) -> np.ndarray:
    """Orthonormal DCT-II basis, so the transform is one matrix product.

    At 32x32 this is faster to build than to import scipy for, and being an
    explicit matrix makes the implementation inspectable.
    """
    rows = np.arange(size).reshape(-1, 1)
    cols = np.arange(size).reshape(1, -1)
    basis = np.cos(np.pi * (2 * cols + 1) * rows / (2 * size))
    basis *= np.sqrt(2.0 / size)
    basis[0] /= np.sqrt(2.0)
    return basis


_DCT = _dct_matrix(SAMPLE_SIZE)


def phash(image: Image.Image) -> int:
    """64-bit perceptual hash of an image.

    Greyscale, reduced to 32x32, 2-D DCT, keep the top-left 8x8 block of low
    frequencies, and set each bit by whether its coefficient is above the
    median. Using the median rather than the mean is what stops one very bright
    or dark region from dominating the hash.
    """
    prepared = image.convert("L").resize((SAMPLE_SIZE, SAMPLE_SIZE), Image.Resampling.LANCZOS)
    pixels = np.asarray(prepared, dtype=np.float64)

    transformed = _DCT @ pixels @ _DCT.T
    low_frequencies = transformed[:HASH_SIZE, :HASH_SIZE]

    # The DC term is the average brightness of the whole image. It carries no
    # structure and would skew the median, so it is excluded from the decision.
    without_dc = low_frequencies.flatten()[1:]
    median = float(np.median(without_dc))

    bits = (low_frequencies.flatten() > median).astype(np.uint8)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming_distance(left: int, right: int) -> int:
    """How many bits differ. Zero means the images are perceptually identical."""
    return int((left ^ right).bit_count())


def to_signed_64(value: int) -> int:
    """Fit a 64-bit hash into a Postgres ``bigint``, which is signed.

    The top bit is set about half the time, so storing the raw value overflows.
    The mapping is reversible and order-free — only equality and Hamming
    distance are ever asked of it, and both survive the reinterpretation.
    """
    return value - (1 << 64) if value >= (1 << 63) else value


def from_signed_64(value: int) -> int:
    """Undo :func:`to_signed_64`."""
    return value + (1 << 64) if value < 0 else value
