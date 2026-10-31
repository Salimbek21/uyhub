"""Stage one extraction: what regular expressions can read reliably (SPEC 5.2).

Tashkent property posts are messy free text, but a few things in them are
almost formulaic — `3/5/9` for rooms/floor/total, a price with a currency word,
`75 m2`, `6 sotix`. Those are what this module reads. Everything subtler is the
LLM's job (docs/DECISIONS.md P.4).

The hardest single problem here is the number itself. `65 000`, `65.000` and
`65,000` are all sixty-five thousand, while `1,2 mlrd` is one and a fifth
billion, and the same post may contain both forms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from uyhub.models.enums import (
    BuildingType,
    Currency,
    DealType,
    PricePeriod,
    PropertyType,
    Renovation,
)
from uyhub.parser.districts import fold

SOTIX_IN_M2 = Decimal(100)
"""1 sotix = 100 m² (SPEC 5.2)."""

_NUMBER = r"\d{1,3}(?:[  .,]\d{3})+|\d+(?:[.,]\d+)?"

_MULTIPLIERS: dict[str, Decimal] = {
    "k": Decimal(1_000),
    "ming": Decimal(1_000),
    "минг": Decimal(1_000),
    "mln": Decimal(1_000_000),
    "млн": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "миллион": Decimal(1_000_000),
    "mlrd": Decimal(1_000_000_000),
    "млрд": Decimal(1_000_000_000),
    "milliard": Decimal(1_000_000_000),
    "миллиард": Decimal(1_000_000_000),
}

_MULTIPLIER_PATTERN = "|".join(sorted(_MULTIPLIERS, key=len, reverse=True))

_USD_PATTERN = r"\$|usd|у\.?\s?е\.?|y\.?\s?e\.?|dollar|доллар"
_UZS_PATTERN = r"s[ou]['’ʻ`]?m|сум|сўм"

_PRICE_RE = re.compile(
    rf"""
    (?P<leading_currency>\$)?\s*
    (?P<amount>{_NUMBER})
    \s*
    # The boundary belongs inside the optional group: without it the `k`
    # multiplier matches the `k` in `75 kv`, and outside it the whole match
    # fails on `50000ye`, where no multiplier is present at all.
    (?:(?P<multiplier>{_MULTIPLIER_PATTERN})(?!\w))?
    \s*
    (?P<currency>{_USD_PATTERN}|{_UZS_PATTERN})?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_PERIOD_RE = re.compile(
    r"""(?:
        /\s*(?P<month_slash>oy|мес|месяц|ой)
      | /\s*(?P<day_slash>kun|сут|сутки|день|кун)
      | \b(?P<month_word>oyiga|ойига|в\s*месяц|ежемесячно|per\s*month)\b
      | \b(?P<day_word>kuniga|кунига|в\s*сутки|посуточно|per\s*day)\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

_ROOMS_FLOOR_TOTAL_RE = re.compile(
    r"(?<!\d)(?P<rooms>\d{1,2})\s*/\s*(?P<floor>\d{1,2})\s*/\s*(?P<total>\d{1,2})(?!\d)"
)
_FLOOR_TOTAL_RE = re.compile(r"(?<!\d)(?P<floor>\d{1,2})\s*/\s*(?P<total>\d{1,2})(?!\s*/)(?!\d)")

# "3/12 qavat", "5/9 этаж" — a pair that names itself. This has to be tried
# before `_FLOOR_RE`, which would otherwise match the `12 qavat` at the end and
# report a third-floor flat as being on the twelfth.
_FLOOR_TOTAL_LABELLED_RE = re.compile(
    r"(?<!\d)(?P<floor>\d{1,2})\s*/\s*(?P<total>\d{1,2})(?!\s*/)(?!\d)"
    r"[ \t]*[-–—]?[ \t]*(?:qavat|қават|этаж|эт\.?)",
    re.IGNORECASE,
)

# `комнат` is left open-ended: Russian declines it through комната, комнаты,
# комнат, комнатная, комнатную. `xonali` is not, because `xonadon` is a
# different word.
_ROOMS_RE = re.compile(
    r"(?<!\d)(\d{1,2})[ \t]*[-–—]?[ \t]*(?:xonali|xona\b|хонали|хона\b|комнат\w*|комн\.?|к\b)",
    re.IGNORECASE,
)

# The other common shape: a labelled list, where the number follows the label.
#   Xonalar: 2      Комнат: 2      Количество комнат: 2
_ROOMS_LABELLED_RE = re.compile(
    r"(?:xonalar(?:\s*soni)?|хоналар|комнат\w*|количество\s+комнат)\s*[:\-–—]\s*(\d{1,2})(?!\d)",
    re.IGNORECASE,
)

_FLOOR_RE = re.compile(
    r"(?<!\d)(\d{1,2})[ \t]*[-–—]?[ \t]*(?:qavat|қават|этаж|этажа|эт\.?)\b", re.IGNORECASE
)
_FLOORS_TOTAL_RE = re.compile(
    r"(?:jami|всего)?[ \t]*(\d{1,2})[ \t]*[-–—]?[ \t]*(?:qavatli|қаватли|этажн\w*)",
    re.IGNORECASE,
)
# "6 этаж из 12" / "6-qavat, 12 qavatdan" — the total stated after the floor.
_FLOORS_OUT_OF_RE = re.compile(
    r"(?:этаж\w*|qavat\w*|қават\w*)[ \t,]*(?:из|iz|dan)[ \t]*(\d{1,2})(?!\d)",
    re.IGNORECASE,
)

# `100² Metr` and `100 metr kv` turn up in real posts alongside the textbook
# forms, and the `²` can sit on either side of the unit.
_AREA_RE = re.compile(
    rf"""(?<!\d)(?P<value>{_NUMBER})\s*
        (?: kv\.?\s?m | кв\.?\s?м | m\s?2 | м\s?2 | m² | м²
          | ²\s*(?:metr|метр) | (?:metr|метр)\s*(?:kv|кв) | кв | kv )(?!\w)""",
    re.IGNORECASE | re.VERBOSE,
)
_SOTIX_RE = re.compile(
    rf"(?<!\d)(?P<value>{_NUMBER})\s*(?:sotix|sotiq|сотих|соток|сотки|сотка|сот\.?)(?!\w)",
    re.IGNORECASE,
)

_LIST_ITEM_RE = re.compile(r"^[ \t]*(\d{1,2})[).\-][ \t]", re.MULTILINE)

_NEGOTIABLE_RE = re.compile(
    r"\b(?:kelishiladi|kelishamiz|kelishilgan holda|келишилади|келишамиз|"
    r"договорная|договорной|договорн\w*|торг(?:\s*уместен)?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PriceCandidate:
    """One price found in the text."""

    amount: Decimal
    currency: Currency
    explicit_currency: bool
    """False when the currency was inferred from the magnitude rather than read."""

    span: tuple[int, int]


def parse_number(raw: str) -> Decimal | None:
    """Read a number written the way Uzbek and Russian posts write them.

    `65 000`, `65.000` and `65,000` are sixty-five thousand; `1,2` and `1.2`
    are one point two. The rule is positional: a separator followed by exactly
    three digits, with nothing but more such groups after it, is a thousands
    separator. Anything else is a decimal point.
    """
    cleaned = raw.replace(" ", " ").strip()
    if not cleaned:
        return None

    compact = cleaned.replace(" ", "")
    if re.fullmatch(r"\d+", compact):
        return _to_decimal(compact)

    # Every separator followed by exactly three digits -> thousands separators.
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", compact):
        return _to_decimal(compact.replace(".", "").replace(",", ""))

    # A single separator with one or two digits after it -> decimal.
    decimal_match = re.fullmatch(r"(\d+)[.,](\d{1,2})", compact)
    if decimal_match:
        return _to_decimal(f"{decimal_match.group(1)}.{decimal_match.group(2)}")

    # Mixed, e.g. `1.234,5`: the last separator is the decimal one.
    mixed = re.fullmatch(r"([\d.,]+)[.,](\d{1,2})", compact)
    if mixed:
        whole = re.sub(r"[.,]", "", mixed.group(1))
        return _to_decimal(f"{whole}.{mixed.group(2)}")

    return _to_decimal(re.sub(r"[.,]", "", compact))


def _to_decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _classify_currency(token: str | None) -> Currency | None:
    if not token:
        return None
    if re.fullmatch(_USD_PATTERN, token, re.IGNORECASE):
        return Currency.USD
    if re.fullmatch(_UZS_PATTERN, token, re.IGNORECASE):
        return Currency.UZS
    return None


def find_prices(text: str) -> list[PriceCandidate]:
    """Every price in the text, in order.

    A number with no currency word is read by magnitude: anything at or above
    a million is so'm, anything below is dollars. That is simply how Tashkent
    posts are written — a flat is `65 000` in dollars or `780 000 000` in so'm,
    and the two ranges do not overlap.
    """
    candidates: list[PriceCandidate] = []

    for match in _PRICE_RE.finditer(text):
        amount = parse_number(match.group("amount"))
        if amount is None or amount <= 0:
            continue

        multiplier_token = (match.group("multiplier") or "").lower()
        currency_token = match.group("currency")
        leading = match.group("leading_currency")

        if not multiplier_token and not currency_token and not leading:
            continue

        if multiplier_token:
            amount *= _MULTIPLIERS[multiplier_token]

        currency = _classify_currency(currency_token)
        explicit = currency is not None
        if currency is None and leading:
            currency, explicit = Currency.USD, True
        if currency is None:
            currency = Currency.UZS if amount >= 1_000_000 else Currency.USD

        candidates.append(
            PriceCandidate(
                amount=amount,
                currency=currency,
                explicit_currency=explicit,
                span=match.span(),
            )
        )

    return candidates


def best_price(text: str) -> PriceCandidate | None:
    """The price most likely to be *the* price.

    An explicitly stated currency beats an inferred one; after that the largest
    wins, because the small numbers in a post are floors, rooms and areas that
    slipped through, not the asking price.
    """
    candidates = find_prices(text)
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c.explicit_currency, c.amount))


def find_period(text: str) -> PricePeriod | None:
    """Rent period, when the post says one (SPEC 6.2)."""
    match = _PERIOD_RE.search(text)
    if match is None:
        return None
    if match.group("day_slash") or match.group("day_word"):
        return PricePeriod.DAY
    return PricePeriod.MONTH


@dataclass(frozen=True, slots=True)
class RoomsFloors:
    rooms: int | None = None
    floor: int | None = None
    floors_total: int | None = None


def find_rooms_and_floors(text: str) -> RoomsFloors:
    """Rooms, floor and total floors, from `3/5/9` or from words.

    When a post says both — "3 xonali ... 8/9/9" — the word wins for the room
    count. A writer who spelled it out meant it; the triple in that case is
    usually floor and total with something else stuck on the front.
    """
    spelled_rooms = _first_int(_ROOMS_RE, text) or _first_int(_ROOMS_LABELLED_RE, text)

    triple = _ROOMS_FLOOR_TOTAL_RE.search(text)
    if triple:
        return RoomsFloors(
            rooms=spelled_rooms if spelled_rooms is not None else int(triple.group("rooms")),
            floor=int(triple.group("floor")),
            floors_total=int(triple.group("total")),
        )

    rooms = spelled_rooms

    # A pair that labels itself — "3/12 qavat" — says both numbers at once, so
    # it is read before the single-floor patterns. Sale posts use this format
    # constantly, and without it the total was being read as the floor.
    labelled = _FLOOR_TOTAL_LABELLED_RE.search(text)
    if labelled:
        return RoomsFloors(
            rooms=rooms,
            floor=int(labelled.group("floor")),
            floors_total=int(labelled.group("total")),
        )

    floor = _first_int(_FLOOR_RE, text)
    floors_total = _first_int(_FLOORS_TOTAL_RE, text) or _first_int(_FLOORS_OUT_OF_RE, text)

    if floor is None and floors_total is None:
        pair = _FLOOR_TOTAL_RE.search(text)
        if pair:
            floor = int(pair.group("floor"))
            floors_total = int(pair.group("total"))

    return RoomsFloors(rooms=rooms, floor=floor, floors_total=floors_total)


def _first_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return int(match.group(1)) if match else None


def find_all_room_counts(text: str) -> set[int]:
    """Every distinct room count the post states.

    More than one is the clearest sign a post is describing more than one
    property (SPEC 6.6). Counts outside what a flat can plausibly have are
    dropped, so a phone fragment or a year cannot masquerade as a room count.
    """
    found = {int(match.group(1)) for match in _ROOMS_RE.finditer(text)}
    found |= {int(match.group(1)) for match in _ROOMS_LABELLED_RE.finditer(text)}
    return {rooms for rooms in found if 1 <= rooms <= 12}


def count_list_items(text: str) -> int:
    """Numbered list markers at the start of a line: `1)`, `2.`, `3 -`."""
    return len(_LIST_ITEM_RE.findall(text))


def find_area_m2(text: str) -> Decimal | None:
    match = _AREA_RE.search(text)
    return parse_number(match.group("value")) if match else None


def find_land_sotix(text: str) -> Decimal | None:
    match = _SOTIX_RE.search(text)
    return parse_number(match.group("value")) if match else None


def is_negotiable(text: str) -> bool:
    return _NEGOTIABLE_RE.search(text) is not None


# ---------------------------------------------------------------------------
# Keyword-driven categories
# ---------------------------------------------------------------------------

# A term ending in `*` matches any suffix. Uzbek is agglutinative — `gisht`
# turns up as `gishtli`, `gishtdan`, `gishtli uy` — so most Uzbek stems need it.
# Russian terms mostly do not, and `дом*` would swallow `домашний`.

_SALE_TERMS = (
    "sotiladi",
    "sotil*",
    "sotuvda",
    "sotaman",
    "sotamiz",
    "сотилади",
    "сотувда",
    "сотаман",
    "продается",
    "продаётся",
    "продаю",
    "продам",
    "продажа",
    "срочно продается",
)
_RENT_TERMS = (
    "ijaraga",
    "ijara*",
    "arenda",
    "ижарага",
    "ижара",
    "сдается",
    "сдаётся",
    "сдаю",
    "сдам",
    "аренда",
    "в аренду",
    "посуточно",
    "kunlik",
    "oylik",
)

_PROPERTY_STRONG: tuple[tuple[PropertyType, tuple[str, ...]], ...] = (
    # `участок` and `участка` have different stems, so both are listed.
    (PropertyType.LAND, ("uchastka*", "участк*", "участок", "yer maydoni", "tomorqa")),
    (
        PropertyType.COMMERCIAL,
        (
            "ofis*",
            "офис*",
            "dokon*",
            "дўкон*",
            "магазин*",
            "помещени*",
            "tijorat*",
            "тижорат*",
            "sklad*",
            "склад*",
        ),
    ),
    (PropertyType.HOUSE, ("hovli*", "ҳовли*", "коттедж*", "частный дом", "свой дом")),
    (PropertyType.ROOM, ("койко место", "комната в")),
)
"""Checked first: these identify the property regardless of what else is said.
`панельный дом` must not make an apartment a house, so the generic `дом` is
not here."""

_PROPERTY_APARTMENT: tuple[tuple[PropertyType, tuple[str, ...]], ...] = (
    (
        PropertyType.APARTMENT,
        (
            "kvartira*",
            "квартира",
            "квартиру",
            "квартире",
            "xonali",
            "хонали",
            "комнатная",
            "комнатную",
            "новостройка",
        ),
    ),
)

_PROPERTY_WEAK: tuple[tuple[PropertyType, tuple[str, ...]], ...] = (
    (PropertyType.HOUSE, ("дом", "дома", "uy joy", "turar joy")),
    (PropertyType.ROOM, ("комната", "комнату")),
)
"""Only consulted when nothing above matched."""

# `ремонт` declines too: евроремонта, после евроремонта, косметическим ремонтом.
_RENOVATION_TERMS: tuple[tuple[Renovation, tuple[str, ...]], ...] = (
    (
        Renovation.EURO,
        ("evro remont*", "yevro remont*", "evroremont*", "евроремонт*", "евро ремонт*"),
    ),
    (Renovation.NEEDS_REPAIR, ("tamirtalab", "remont talab*", "требует ремонт*", "под ремонт")),
    (Renovation.NONE, ("remontsiz", "без ремонт*", "черновая отделка", "qora suvoq")),
    (Renovation.COSMETIC, ("kosmetik remont*", "косметическ* ремонт*", "косметика")),
    (Renovation.GOOD, ("yaxshi remont*", "яхши ремонт*", "хорош* ремонт*", "свеж* ремонт*")),
)

# Russian adjectives decline through six cases; a prefix match covers them all
# and these three stems are distinctive enough that nothing else collides.
_BUILDING_TERMS: tuple[tuple[BuildingType, tuple[str, ...]], ...] = (
    (BuildingType.BRICK, ("gisht*", "ғишт*", "кирпич*")),
    (BuildingType.PANEL, ("panel*", "панел*")),
    (BuildingType.MONOLITH, ("monolit*", "монолит*")),
)


def _term_pattern(term: str) -> str:
    """Turn a term into a regex. `*` stands for "any word ending".

    `кирпич*` matches кирпичный and кирпичном; `хорош* ремонт*` matches
    хороший ремонт and хорошим ремонтом. A term with no `*` must match a whole
    word, which is what keeps `дом` out of `домашний`.
    """
    if "*" not in term:
        return rf"(?<!\w){re.escape(fold(term))}(?!\w)"

    # Fold each segment separately: `fold` drops punctuation, which would eat
    # the `*` itself, and it strips spaces, which would weld two words together.
    pieces: list[str] = []
    for part in term.split("*"):
        prefix = " " if part[:1].isspace() else ""
        suffix = " " if part[-1:].isspace() else ""
        pieces.append(prefix + fold(part) + suffix)

    body = r"\w*".join(re.escape(piece) for piece in pieces)
    return rf"(?<!\w){body}"


def _any_term(folded_text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(_term_pattern(term), folded_text) for term in terms)


def _match_terms[T](folded_text: str, table: tuple[tuple[T, tuple[str, ...]], ...]) -> T | None:
    """The first value in ``table`` whose terms appear. Table order is priority."""
    for value, terms in table:
        if _any_term(folded_text, terms):
            return value
    return None


def find_deal_type(text: str) -> DealType | None:
    """Sale or rent. A post offering both ("sotiladi yoki ijaraga") is a sale."""
    folded = fold(text)
    if _any_term(folded, _SALE_TERMS):
        return DealType.SALE
    if _any_term(folded, _RENT_TERMS):
        return DealType.RENT
    return None


def find_property_type(text: str) -> PropertyType | None:
    folded = fold(text)
    for table in (_PROPERTY_STRONG, _PROPERTY_APARTMENT, _PROPERTY_WEAK):
        match = _match_terms(folded, table)
        if match is not None:
            return match
    return None


def find_renovation(text: str) -> Renovation:
    return _match_terms(fold(text), _RENOVATION_TERMS) or Renovation.UNKNOWN


def find_building_type(text: str) -> BuildingType:
    return _match_terms(fold(text), _BUILDING_TERMS) or BuildingType.UNKNOWN
