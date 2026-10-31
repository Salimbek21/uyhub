"""Stage two: cross-check, convert, score (SPEC 6.3).

Extraction says what the post appears to claim. Normalization decides what we
are willing to store: it converts the price to dollars so listings are
comparable, flags readings that cannot be true, cleans the text of personal
data, and produces the Uzbek title the Mini App shows.

Nothing here is thrown away when a sanity rule fires. An implausible listing is
kept with ``needs_review`` set and a reason, because the admin queue is how the
rules get corrected; silently dropping it would hide the mistake.
"""

from __future__ import annotations

import re
from decimal import Decimal

from uyhub.core.config import Settings, get_settings
from uyhub.core.phones import hash_phones, strip_phones
from uyhub.i18n import DISTRICT_NAMES_UZ
from uyhub.models.enums import Currency, DealType, District, PropertyType
from uyhub.parser.schema import TITLE_MAX_LENGTH, Extraction, RawExtraction

# -- Sanity bounds (SPEC 6.3) ----------------------------------------------
APARTMENT_AREA_MIN = Decimal(15)
APARTMENT_AREA_MAX = Decimal(500)
ROOMS_MAX = 12
SALE_PRICE_USD_MIN = Decimal(5_000)
SALE_PRICE_USD_MAX = Decimal(5_000_000)
RENT_PRICE_USD_MIN = Decimal(50)
RENT_PRICE_USD_MAX = Decimal(20_000)

CONFIDENCE_REVIEW_BELOW = 0.35
"""Below this we have read so little of the post that a human should look."""

PROPERTY_NAMES_UZ: dict[PropertyType, str] = {
    PropertyType.APARTMENT: "kvartira",
    PropertyType.HOUSE: "hovli",
    PropertyType.LAND: "yer uchastka",
    PropertyType.COMMERCIAL: "tijorat obyekti",
    PropertyType.ROOM: "xona",
    PropertyType.OTHER: "obyekt",
}

_MENTION_RE = re.compile(r"@[A-Za-z][A-Za-z0-9_]{3,}")
_LINK_RE = re.compile(r"https?://\S+|(?:www\.|t\.me/)\S+")
_EMOJI_RUN_RE = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]{2,}")
_BLANK_RUN_RE = re.compile(r"\n{3,}")
_SPACE_RUN_RE = re.compile(r"[ \t]{2,}")


def clean_description(text: str) -> str:
    """The post with personal data and noise removed, line breaks kept (SPEC 6.3)."""
    without_phones = strip_phones(text)
    without_mentions = _MENTION_RE.sub("", without_phones)
    without_links = _LINK_RE.sub("", without_mentions)
    without_emoji_runs = _EMOJI_RUN_RE.sub("", without_links)

    lines = [_SPACE_RUN_RE.sub(" ", line).strip() for line in without_emoji_runs.splitlines()]
    joined = "\n".join(lines)
    return _BLANK_RUN_RE.sub("\n\n", joined).strip()


def to_usd(
    amount: Decimal | None,
    currency: Currency | None,
    *,
    uzs_per_usd: Decimal | None,
) -> Decimal | None:
    """Convert to USD, or ``None`` when we cannot.

    A UZS price with no exchange rate yields ``None`` rather than a guess: the
    feed sorts and filters on this column, so a wrong number here is worse than
    a missing one.
    """
    if amount is None or currency is None:
        return None
    if currency is Currency.USD:
        return amount.quantize(Decimal("0.01"))
    if not uzs_per_usd or uzs_per_usd <= 0:
        return None
    return (amount / uzs_per_usd).quantize(Decimal("0.01"))


def compose_title(
    *,
    property_type: PropertyType | None,
    rooms: int | None,
    district: District | None,
    landmark: str | None,
    area_m2: Decimal | None,
    land_sotix: Decimal | None,
) -> str:
    """A short Uzbek title, e.g. "3 xonali kvartira, Chilonzor, 75 m²".

    Takes loose fields rather than an extraction so a merge can rebuild the
    title from the listing's current state. A listing created from a terse post
    and completed by a later one would otherwise keep the title it was born
    with — "3 xonali obyekt" long after its type became known.
    """
    parts: list[str] = []

    kind = PROPERTY_NAMES_UZ.get(property_type or PropertyType.OTHER, "obyekt")
    parts.append(f"{rooms} xonali {kind}" if rooms else kind.capitalize())

    if district is not None:
        parts.append(DISTRICT_NAMES_UZ[district])
    elif landmark:
        parts.append(landmark.title())

    if area_m2:
        parts.append(f"{_trim(area_m2)} m²")
    elif land_sotix:
        parts.append(f"{_trim(land_sotix)} sotix")

    return ", ".join(parts)[:TITLE_MAX_LENGTH].rstrip(", ")


def build_title(extraction: RawExtraction) -> str:
    """The title for one extraction."""
    return compose_title(
        property_type=extraction.property_type,
        rooms=extraction.rooms,
        district=extraction.district,
        landmark=extraction.landmark,
        area_m2=extraction.area_m2,
        land_sotix=extraction.land_sotix,
    )


def _trim(value: Decimal) -> str:
    """Drop a trailing `.00` so titles read `75 m²`, not `75.00 m²`."""
    normalised = value.normalize()
    text = format(normalised, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def sanity_check(extraction: RawExtraction, price_usd: Decimal | None) -> list[str]:
    """Which SPEC 6.3 bounds this reading violates. Empty means plausible."""
    reasons: list[str] = []

    if (
        extraction.property_type is PropertyType.APARTMENT
        and extraction.area_m2
        and not APARTMENT_AREA_MIN <= extraction.area_m2 <= APARTMENT_AREA_MAX
    ):
        reasons.append("area_out_of_range")

    if extraction.rooms and extraction.rooms > ROOMS_MAX:
        reasons.append("too_many_rooms")

    if extraction.floor and extraction.floors_total and extraction.floor > extraction.floors_total:
        reasons.append("floor_above_total")

    if price_usd is not None and extraction.deal_type is not None:
        if extraction.deal_type is DealType.SALE:
            low, high = SALE_PRICE_USD_MIN, SALE_PRICE_USD_MAX
        else:
            low, high = RENT_PRICE_USD_MIN, RENT_PRICE_USD_MAX
        if not low <= price_usd <= high:
            reasons.append("price_out_of_range")

    if extraction.confidence < CONFIDENCE_REVIEW_BELOW:
        reasons.append("low_confidence")

    return reasons


def quality_score(
    extraction: RawExtraction,
    *,
    photo_count: int,
    source_trust: float,
) -> int:
    """0–100, from how complete and how trustworthy the listing is (SPEC 6.3).

    Drives the feed's default ordering and the channel poster's threshold, so
    it rewards the fields a buyer actually filters on.
    """
    score = 0.0
    if extraction.price_amount is not None:
        score += 25
    if extraction.district is not None:
        score += 15
    if extraction.rooms is not None or extraction.area_m2 is not None:
        score += 15
    score += min(photo_count, 5) * 4  # up to 20
    score += extraction.confidence * 15
    score += max(0.0, min(source_trust, 1.0)) * 10

    return int(max(0, min(100, round(score))))


def normalize(
    extraction: RawExtraction,
    *,
    text: str,
    photo_count: int = 0,
    source_trust: float = 1.0,
    uzs_per_usd: Decimal | None = None,
    settings: Settings | None = None,
) -> Extraction:
    """Turn one extractor's reading into what gets stored."""
    cfg = settings or get_settings()

    if not extraction.is_listing:
        return Extraction(
            parser_version=cfg.parser_version,
            is_listing=False,
            reject_reason=extraction.reject_reason,
            confidence=extraction.confidence,
        )

    price_usd = to_usd(extraction.price_amount, extraction.price_currency, uzs_per_usd=uzs_per_usd)
    review_reasons = sanity_check(extraction, price_usd)

    return Extraction(
        parser_version=cfg.parser_version,
        is_listing=True,
        deal_type=extraction.deal_type,
        property_type=extraction.property_type,
        rooms=extraction.rooms,
        area_m2=extraction.area_m2,
        land_sotix=extraction.land_sotix,
        floor=extraction.floor,
        floors_total=extraction.floors_total,
        building_type=extraction.building_type,
        renovation=extraction.renovation,
        price_amount=extraction.price_amount,
        price_currency=extraction.price_currency,
        price_usd=price_usd,
        price_period=extraction.price_period,
        negotiable=extraction.negotiable,
        district=extraction.district,
        landmark=extraction.landmark,
        address_text=extraction.address_text,
        title=build_title(extraction),
        description=clean_description(text),
        phone_hashes=hash_phones(extraction.phones, cfg) if extraction.phones else [],
        quality_score=quality_score(extraction, photo_count=photo_count, source_trust=source_trust),
        confidence=extraction.confidence,
        needs_review=bool(review_reasons),
        review_reasons=review_reasons,
    )
