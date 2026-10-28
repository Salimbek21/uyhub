"""Loading and scoring the golden set (SPEC 6.4).

Scoring rule: only the fields a fixture actually states are counted. A post
that genuinely does not name its district should not drag the district
accuracy down — the parser was right to leave it null, and padding every
fixture with explicit nulls would make the files unreadable.

The exchange rate is fixed here rather than read from the database, so the
score moves when the parser changes and not when the so'm does.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from uyhub.core.config import Settings
from uyhub.parser.normalize import to_usd
from uyhub.parser.pipeline import ParseResult, parse
from uyhub.parser.schema import Extraction

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "posts"

EVAL_RATE = Decimal(12_000)
"""A round, fixed UZS/USD rate. Its only job is to be the same on both sides."""

SPEC_FIELDS = ("deal_type", "property_type", "rooms", "price_usd", "district")
"""The five SPEC 1.5 measures accuracy on."""

EXTRA_FIELDS = (
    "area_m2",
    "land_sotix",
    "floor",
    "floors_total",
    "building_type",
    "renovation",
    "price_period",
    "negotiable",
)


@dataclass(frozen=True, slots=True)
class GoldenPost:
    """One fixture line."""

    id: str
    text: str
    photos: int
    expected: dict[str, Any]
    source_file: str


def load_golden_set(directory: Path = FIXTURES_DIR) -> list[GoldenPost]:
    """Every fixture, in filename then file order."""
    posts: list[GoldenPost] = []
    for path in sorted(directory.glob("*.jsonl")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:  # pragma: no cover - a broken fixture
                msg = f"{path.name}:{line_number}: {exc}"
                raise ValueError(msg) from exc
            posts.append(
                GoldenPost(
                    id=raw["id"],
                    text=raw["text"],
                    photos=int(raw.get("photos", 0)),
                    expected=raw["expected"],
                    source_file=path.name,
                )
            )
    return posts


@dataclass
class FieldScore:
    """Right / wrong counts for one field."""

    correct: int = 0
    total: int = 0
    mistakes: list[tuple[str, str, str]] = field(default_factory=list)
    """(post id, expected, actual) — the first few are printed in the report."""

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 1.0


@dataclass
class EvalReport:
    """The whole run."""

    fields: dict[str, FieldScore] = field(default_factory=dict)
    listing_confusion: Counter[str] = field(default_factory=Counter)
    reject_reasons: Counter[str] = field(default_factory=Counter)
    total_posts: int = 0

    @property
    def rejection_precision(self) -> float:
        """Of the posts we rejected, how many were really not listings.

        This is the number that matters for trust: a listing wrongly rejected
        is inventory the user never sees, and nobody ever finds out.
        """
        rejected = (
            self.listing_confusion["true_negative"] + self.listing_confusion["false_negative"]
        )
        if not rejected:
            return 1.0
        return self.listing_confusion["true_negative"] / rejected

    @property
    def listing_recall(self) -> float:
        """Of the real listings, how many we kept."""
        actual = self.listing_confusion["true_positive"] + self.listing_confusion["false_negative"]
        if not actual:
            return 1.0
        return self.listing_confusion["true_positive"] / actual


def _actual(extraction: Extraction | None, name: str) -> object | None:
    if extraction is None:
        return None
    value = getattr(extraction, name, None)
    if hasattr(value, "value"):  # StrEnum
        return value.value
    return value


def _expected_price_usd(expected: dict[str, Any]) -> Decimal | None:
    amount = expected.get("price_amount")
    currency = expected.get("price_currency")
    if amount is None or currency is None:
        return None
    from uyhub.models.enums import Currency

    return to_usd(Decimal(str(amount)), Currency(currency), uzs_per_usd=EVAL_RATE)


def _comparable(value: object | None) -> str:
    if value is None:
        return "null"
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def score(posts: list[GoldenPost], settings: Settings) -> EvalReport:
    """Run the real pipeline over every fixture and tally the result."""
    report = EvalReport(total_posts=len(posts))

    for name in (*SPEC_FIELDS, *EXTRA_FIELDS):
        report.fields[name] = FieldScore()

    for post in posts:
        result = parse(
            post.text,
            photo_count=post.photos,
            uzs_per_usd=EVAL_RATE,
            settings=settings,
        )
        _score_one(post, result, report)

    return report


def _score_one(post: GoldenPost, result: ParseResult, report: EvalReport) -> None:
    expected_listing = bool(post.expected.get("is_listing", True))
    actual_listing = result.status.value == "parsed"

    report.listing_confusion[_confusion_key(expected_listing, actual_listing)] += 1
    if not actual_listing and result.reject_reason:
        report.reject_reasons[result.reject_reason] += 1

    if not expected_listing:
        # Nothing else is meaningful about a post that should have been dropped.
        expected_reason = post.expected.get("reject_reason")
        if expected_reason is not None:
            entry = report.fields.setdefault("reject_reason", FieldScore())
            entry.total += 1
            if result.reject_reason == expected_reason:
                entry.correct += 1
            else:
                entry.mistakes.append((post.id, expected_reason, str(result.reject_reason)))
        return

    if not actual_listing:
        # A missed listing counts as wrong for every field it stated.
        for name in (*SPEC_FIELDS, *EXTRA_FIELDS):
            if _is_stated(post.expected, name):
                entry = report.fields[name]
                entry.total += 1
                entry.mistakes.append((post.id, _stated(post.expected, name), "rejected"))
        return

    for name in (*SPEC_FIELDS, *EXTRA_FIELDS):
        if not _is_stated(post.expected, name):
            continue
        entry = report.fields[name]
        entry.total += 1

        expected_value = _comparable(_expected_value(post.expected, name))
        actual_value = _comparable(_actual(result.extraction, name))
        if expected_value == actual_value:
            entry.correct += 1
        else:
            entry.mistakes.append((post.id, expected_value, actual_value))


def _confusion_key(expected: bool, actual: bool) -> str:
    if expected and actual:
        return "true_positive"
    if expected and not actual:
        return "false_negative"
    if not expected and not actual:
        return "true_negative"
    return "false_positive"


def _is_stated(expected: dict[str, Any], name: str) -> bool:
    if name == "price_usd":
        return "price_amount" in expected and "price_currency" in expected
    return name in expected


def _expected_value(expected: dict[str, Any], name: str) -> object | None:
    if name == "price_usd":
        return _expected_price_usd(expected)
    value = expected[name]
    if name in {"area_m2", "land_sotix"} and value is not None:
        return Decimal(str(value))
    return value


def _stated(expected: dict[str, Any], name: str) -> str:
    return _comparable(_expected_value(expected, name))
