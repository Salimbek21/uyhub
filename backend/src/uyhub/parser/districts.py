"""Mapping free text to one of the twelve Tashkent districts (SPEC 6.5).

The table itself lives in ``data/districts.yaml`` so a person who knows the city
can correct it without touching code. This module only loads it and matches.

Two rules keep the result honest. A landmark is weaker evidence than the
district's own name, so names win. And when two different districts both match,
the answer is ``None`` rather than a guess — an unlabelled listing is merely
less filterable, while a mislabelled one is wrong in the user's face.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from uyhub.models.enums import District

DATA_FILE = Path(__file__).parent / "data" / "districts.yaml"

_APOSTROPHES = str.maketrans({"ʻ": "", "ʼ": "", "'": "", "’": "", "`": "", "´": ""})
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def fold(text: str) -> str:
    """Normalise text for matching.

    Case, the four apostrophes Uzbek Latin is written with, and punctuation all
    vary between posts and none of them carry meaning here. ``Mirzo Ulug'bek``,
    ``mirzo ulugbek`` and ``Мирзо-Улугбек`` must all reach the same key.
    """
    lowered = unicodedata.normalize("NFC", text).lower()
    without_apostrophes = lowered.translate(_APOSTROPHES)
    without_punctuation = _NON_WORD.sub(" ", without_apostrophes)
    return _SPACES.sub(" ", without_punctuation).strip()


@dataclass(frozen=True, slots=True)
class DistrictMatch:
    """Which district the text points at, and how strongly."""

    district: District
    matched: str
    by_landmark: bool


@lru_cache(maxsize=1)
def _table() -> tuple[dict[str, District], dict[str, District]]:
    """``(names, landmarks)``, each mapping a folded alias to its district."""
    raw: dict[str, Any] = yaml.safe_load(DATA_FILE.read_text(encoding="utf-8"))
    names: dict[str, District] = {}
    landmarks: dict[str, District] = {}

    for key, entry in raw["districts"].items():
        district = District(key)
        # The canonical id itself is a valid alias once underscores are spaces.
        names[fold(key.replace("_", " "))] = district
        for alias in entry.get("aliases") or []:
            names[fold(alias)] = district
        for landmark in entry.get("landmarks") or []:
            landmarks[fold(landmark)] = district

    return names, landmarks


def _find(text_folded: str, table: dict[str, District]) -> list[DistrictMatch]:
    """Every alias in ``table`` that appears in the text, longest alias first.

    Matching is by prefix, not whole word. Both languages here inflect the
    district name: `Chilonzorda`, `Чиланзаре`, `Яшнабадском`, `Бектемире`.
    Requiring a word boundary at the end would miss most real posts, and these
    names are distinctive enough that a prefix match has nothing to collide
    with.
    """
    found: list[DistrictMatch] = []
    for alias in sorted(table, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(alias)}", text_folded):
            found.append(DistrictMatch(district=table[alias], matched=alias, by_landmark=False))
    return found


def detect_district(text: str) -> DistrictMatch | None:
    """The district this text refers to, or ``None`` when it is not clear."""
    folded = fold(text)
    names, landmarks = _table()

    by_name = _find(folded, names)
    if by_name:
        return _single(by_name)

    by_landmark = [
        DistrictMatch(district=m.district, matched=m.matched, by_landmark=True)
        for m in _find(folded, landmarks)
    ]
    return _single(by_landmark)


def _single(matches: list[DistrictMatch]) -> DistrictMatch | None:
    """One district, or ``None`` if the text names more than one."""
    if not matches:
        return None
    districts = {match.district for match in matches}
    if len(districts) > 1:
        return None
    return matches[0]


def all_aliases() -> dict[str, District]:
    """Every name and landmark, for the eval report and for tests."""
    names, landmarks = _table()
    return {**landmarks, **names}
