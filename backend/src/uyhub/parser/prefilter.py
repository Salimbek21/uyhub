"""Stage one: decide whether a post is worth extracting from (SPEC 5.1).

Most of what lands in a property group is not a listing — greetings, questions,
renovation ads, "looking for a flat" posts. Rejecting them here costs a few
regex passes instead of an LLM call, and the counters say why each one went.

The decision order matters. A stopword beats a signal, because a renovation ad
contains every signal word a real listing does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from uyhub.parser.districts import fold

DATA_DIR = Path(__file__).parent / "data"

KEYWORD_FILES = (
    "keywords_uz_latin.txt",
    "keywords_uz_cyrillic.txt",
    "keywords_ru.txt",
)
STOPWORD_FILE = "stopwords.txt"

MIN_TEXT_LENGTH = 25
"""Below this, and with no photos, there is nothing to extract (SPEC 5.1)."""

QUESTION_MAX_LENGTH = 80
"""A question shorter than this, with no price and no rooms/floor/total, is
conversation. Real listings that contain a question mark run longer."""

_ROOMS_FLOOR_TOTAL_RE = re.compile(r"(?<!\d)\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{1,2}(?!\d)")
"""`3/5/9` — rooms/floor/total. The single most reliable signal in Tashkent posts."""

_PRICE_HINT_RE = re.compile(
    r"\d[\d\s.,]*\s*(?:\$|s[ou]['’ʻ`]?m|сум|сўм|y\.?\s?e\.?|у\.?\s?е\.?|usd|"
    r"ming|минг|mln|млн|mlrd|млрд)",
    re.IGNORECASE,
)

_LINK_RE = re.compile(r"https?://\S+|t\.me/\S+|@[A-Za-z][A-Za-z0-9_]{3,}")
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_DIGIT_RE = re.compile(r"\d")

_GREETING_RE = re.compile(
    r"^(?:assalomu\s+alaykum|salom|salam|здравствуйте|привет|добрый\s+день|"
    r"доброе\s+утро|добрый\s+вечер|rahmat|спасибо|hello|hi)\b",
    re.IGNORECASE,
)


class RejectReason(StrEnum):
    """Why the prefilter said no. Counted so the funnel is measurable."""

    TOO_SHORT = "too_short"
    LINKS_ONLY = "links_only"
    CHAT = "chat"
    STOPWORD = "stopword"
    NO_SIGNAL = "no_signal"


@dataclass(frozen=True, slots=True)
class PrefilterResult:
    """Whether to continue, and why not when the answer is no."""

    accepted: bool
    reason: RejectReason | None = None
    matched: str | None = None
    """The stopword or signal that decided it — useful when tuning the lists."""


@lru_cache(maxsize=1)
def _signals() -> tuple[str, ...]:
    terms: list[str] = []
    for name in KEYWORD_FILES:
        terms.extend(_load(DATA_DIR / name))
    return tuple(terms)


@lru_cache(maxsize=1)
def _stopwords() -> tuple[str, ...]:
    return tuple(_load(DATA_DIR / STOPWORD_FILE))


def _load(path: Path) -> list[str]:
    """Folded, non-empty, non-comment lines."""
    lines = path.read_text(encoding="utf-8").splitlines()
    terms = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        folded = fold(stripped)
        if folded:
            terms.append(folded)
    return terms


def _contains(folded_text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", folded_text) is not None


def prefilter(text: str, *, has_photos: bool = False) -> PrefilterResult:
    """Decide whether this post should go to extraction."""
    stripped = (text or "").strip()

    if len(stripped) < MIN_TEXT_LENGTH and not has_photos:
        return PrefilterResult(accepted=False, reason=RejectReason.TOO_SHORT)

    without_links = _LINK_RE.sub(" ", stripped).strip()
    if not _WORD_RE.search(without_links):
        return PrefilterResult(accepted=False, reason=RejectReason.LINKS_ONLY)

    folded = fold(stripped)

    for stopword in _stopwords():
        if _contains(folded, stopword):
            return PrefilterResult(accepted=False, reason=RejectReason.STOPWORD, matched=stopword)

    # Structural signals are stronger than any word: `3/5/9` or `65 000 $`
    # identify a listing even in a post written entirely in slang.
    if _ROOMS_FLOOR_TOTAL_RE.search(stripped):
        return PrefilterResult(accepted=True, matched="rooms/floor/total")
    if _PRICE_HINT_RE.search(stripped):
        return PrefilterResult(accepted=True, matched="price")

    # Checked before the keyword list, not after: "bu uy qancha turadi?" contains
    # a signal word and is still someone asking a question.
    if _is_chat(stripped):
        return PrefilterResult(accepted=False, reason=RejectReason.CHAT)

    for signal in _signals():
        if _contains(folded, signal):
            return PrefilterResult(accepted=True, matched=signal)

    return PrefilterResult(accepted=False, reason=RejectReason.NO_SIGNAL)


def _is_chat(text: str) -> bool:
    """Conversation rather than inventory.

    Only reached once the structural checks have failed, so there is no price
    and no rooms/floor/total in the text. A short question with neither is
    someone talking; a real listing that happens to contain a question mark is
    longer than this and has already been accepted above.
    """
    if _GREETING_RE.match(text):
        return True
    if "?" in text and len(text) < QUESTION_MAX_LENGTH:
        return True
    return "?" in text and not _DIGIT_RE.search(text)
