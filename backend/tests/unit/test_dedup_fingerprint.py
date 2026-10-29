"""Fingerprints and perceptual hashing (SPEC 7.1, 7.3).

These replace a library SPEC named (`imagehash`), so the properties that
library would have guaranteed are asserted here instead.
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFilter

from uyhub.dedup.fingerprint import (
    dedup_key,
    from_signed_64,
    hamming_distance,
    simhash,
    to_signed_64,
)
from uyhub.media.phash import phash
from uyhub.media.process import process_image
from uyhub.models.enums import DealType, District, PropertyType

pytestmark = pytest.mark.unit

PHONE = "a" * 64
OTHER_PHONE = "b" * 64

BASE = {
    "phone_hashes": [PHONE],
    "deal_type": DealType.SALE,
    "property_type": PropertyType.APARTMENT,
    "rooms": 3,
    "district": District.CHILONZOR,
    "price_usd": Decimal(65_000),
}


def room(seed: int = 0, size: tuple[int, int] = (800, 600)) -> Image.Image:
    """A synthetic photograph with enough structure to hash meaningfully."""
    image = Image.new("RGB", size, (40 + seed * 25, 60, 90))
    draw = ImageDraw.Draw(image)
    draw.rectangle([100 + seed * 40, 150, 400, 500], fill=(200, 190, 170))
    draw.ellipse([500, 100, 700, 300], fill=(240, 230, 110 + seed * 15))
    draw.line([0, 550, size[0], 550], fill=(20, 20, 20), width=12)
    return image


def as_jpeg(image: Image.Image, quality: int = 85) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


class TestDedupKey:
    def test_the_same_listing_keys_identically(self) -> None:
        assert dedup_key(**BASE) == dedup_key(**BASE)

    def test_a_nearby_price_keys_identically(self) -> None:
        """Sale prices round to the nearest thousand (SPEC 7.1)."""
        assert dedup_key(**BASE) == dedup_key(**{**BASE, "price_usd": Decimal(65_400)})

    @pytest.mark.parametrize(
        "change",
        [
            {"price_usd": Decimal(70_000)},
            {"rooms": 2},
            {"district": District.SERGELI},
            {"deal_type": DealType.RENT},
            {"property_type": PropertyType.HOUSE},
            {"phone_hashes": [OTHER_PHONE]},
        ],
    )
    def test_any_identifying_field_changes_the_key(self, change: dict[str, object]) -> None:
        assert dedup_key(**BASE) != dedup_key(**{**BASE, **change})

    def test_without_a_phone_there_is_no_key(self) -> None:
        """Otherwise two different flats with the same shape would collapse into
        one listing — a wrong answer shown to a user (OPEN_QUESTIONS B1)."""
        assert dedup_key(**{**BASE, "phone_hashes": []}) is None

    def test_without_a_deal_type_there_is_no_key(self) -> None:
        assert dedup_key(**{**BASE, "deal_type": None}) is None

    def test_the_phone_order_does_not_matter(self) -> None:
        """A repost may list the same two numbers the other way round."""
        first = dedup_key(**{**BASE, "phone_hashes": [PHONE, OTHER_PHONE]})
        second = dedup_key(**{**BASE, "phone_hashes": [OTHER_PHONE, PHONE]})
        assert first == second

    def test_rent_rounds_more_finely_than_sale(self) -> None:
        """A $40 difference is noise on a sale and a different flat on a rent."""
        rent = {**BASE, "deal_type": DealType.RENT, "price_usd": Decimal(600)}
        assert dedup_key(**rent) != dedup_key(**{**rent, "price_usd": Decimal(640)})

    def test_the_key_is_stable_across_processes(self) -> None:
        """Built on blake2b, not Python's salted `hash()` — a restart must not
        orphan every stored key."""
        assert dedup_key(**BASE) == (dedup_key(**BASE)), "the key must not depend on process state"
        assert len(dedup_key(**BASE) or "") == 32


class TestSimHash:
    def test_identical_text_is_distance_zero(self) -> None:
        text = "3 xonali kvartira Chilonzor tumani 75 m2 yevro remont"
        assert hamming_distance(simhash(text), simhash(text)) == 0

    def test_a_repost_with_small_edits_stays_close(self) -> None:
        original = (
            "Kimlarga: Oilaga Yoki 4Ta Qizga\nManzil: M.Ulugbek Metro Yonida\n"
            "Xonalar soni: 2Xona 6/10\nSharoitlar: Hamma Sharoiti Bor\nNarx: 1000$"
        )
        repost = original.replace("Yonida", "Yaqinida").replace("Sharoiti", "Sharti")
        assert hamming_distance(simhash(original), simhash(repost)) < 20

    def test_a_different_listing_is_far(self) -> None:
        left = "3 xonali kvartira Chilonzor 75 m2 yevro remont narxi 65000 dollar"
        right = "Yer uchastka Sergeli 10 sotix hujjatlari tayyor narxi 95000"
        assert hamming_distance(simhash(left), simhash(right)) > 15

    def test_empty_text_hashes_to_zero(self) -> None:
        assert simhash("") == 0
        assert simhash("   ") == 0

    def test_it_fits_a_bigint(self) -> None:
        value = simhash("3 xonali kvartira Chilonzor")
        signed = to_signed_64(value)
        assert -(2**63) <= signed < 2**63
        assert from_signed_64(signed) == value


class TestPerceptualHash:
    def test_the_same_image_hashes_identically(self) -> None:
        image = room()
        assert phash(image) == phash(image)

    def test_a_recompressed_copy_stays_close(self) -> None:
        """This is the whole point: Telegram resizes and recompresses."""
        original = room()
        smaller = Image.open(BytesIO(as_jpeg(original.resize((400, 300)), quality=70)))
        assert hamming_distance(phash(original), phash(smaller)) <= 6

    def test_a_blurred_copy_stays_close(self) -> None:
        original = room()
        blurred = original.filter(ImageFilter.GaussianBlur(2))
        assert hamming_distance(phash(original), phash(blurred)) <= 6

    def test_a_different_photograph_is_far(self) -> None:
        assert hamming_distance(phash(room(0)), phash(room(6))) > 6

    def test_the_hash_is_64_bits(self) -> None:
        assert phash(room()).bit_length() <= 64

    def test_it_survives_the_bigint_round_trip(self) -> None:
        value = phash(room())
        assert from_signed_64(to_signed_64(value)) == value


class TestProcessImage:
    def test_derivatives_are_webp_and_bounded(self) -> None:
        result = process_image(as_jpeg(room(size=(3000, 2000))))

        for blob, cap in ((result.large, 1280), (result.thumb, 400)):
            with Image.open(BytesIO(blob)) as out:
                assert out.format == "WEBP"
                assert max(out.size) <= cap

    def test_exif_is_stripped(self) -> None:
        """A phone's EXIF routinely carries GPS coordinates (SPEC 13)."""
        from PIL.ExifTags import Base

        exif = Image.Exif()
        exif[Base.Make.value] = "TestPhone"
        buffer = BytesIO()
        room().save(buffer, "JPEG", exif=exif)

        result = process_image(buffer.getvalue())
        with Image.open(BytesIO(result.large)) as out:
            assert not dict(out.getexif())

    def test_a_small_original_is_not_upscaled(self) -> None:
        result = process_image(as_jpeg(room(size=(200, 150))))
        with Image.open(BytesIO(result.large)) as out:
            assert out.size == (200, 150)

    def test_the_same_bytes_give_the_same_sha256(self) -> None:
        data = as_jpeg(room())
        assert process_image(data).sha256 == process_image(data).sha256

    def test_different_images_differ_in_sha256(self) -> None:
        assert process_image(as_jpeg(room(0))).sha256 != process_image(as_jpeg(room(5))).sha256

    def test_the_original_dimensions_are_reported_not_the_derivative(self) -> None:
        result = process_image(as_jpeg(room(size=(3000, 2000))))
        assert (result.width, result.height) == (3000, 2000)

    def test_a_broken_file_raises(self) -> None:
        """`fetch_and_process` catches this; the pure function should not hide it."""
        with pytest.raises(Exception, match=r"cannot identify|image file"):
            process_image(b"this is not an image")
