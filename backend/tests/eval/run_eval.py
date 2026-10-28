#!/usr/bin/env python
"""`make eval-parser` — parser accuracy on the golden set (SPEC 6.4).

Prints per-field accuracy, the listing/non-listing confusion matrix and the
first few mistakes per field, which is what makes the number actionable rather
than merely depressing.

Exits non-zero when a field falls below its threshold, so CI can gate on it.
Thresholds are supplied on the command line rather than hardcoded: SPEC 1.5's
90% was written for an LLM parser, and holding a regex-only parser to it would
mean either a permanently red build or a quietly weakened golden set.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run as a script, not as part of the test package: `make eval-parser` is a
# report an operator runs, and pytest's collection should not import it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from golden import (
    EXTRA_FIELDS,
    SPEC_FIELDS,
    EvalReport,
    load_golden_set,
    score,
)

from uyhub.core.config import Settings

MISTAKES_SHOWN = 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-field-accuracy",
        type=float,
        default=0.0,
        help="Fail if any SPEC 1.5 field scores below this (0-1).",
    )
    parser.add_argument(
        "--min-rejection-precision",
        type=float,
        default=0.0,
        help="Fail if rejection precision falls below this (0-1).",
    )
    args = parser.parse_args()

    posts = load_golden_set()
    if not posts:
        print("no fixtures found")  # noqa: T201 - this script is a report
        return 1

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        PHONE_HASH_KEY="eval-only-not-a-real-key",
    )
    report = score(posts, settings)
    _print(report, posts_by_file=_counts(posts))

    return _verdict(report, args.min_field_accuracy, args.min_rejection_precision)


def _counts(posts: list) -> dict[str, int]:  # type: ignore[type-arg]
    counts: dict[str, int] = {}
    for post in posts:
        counts[post.source_file] = counts.get(post.source_file, 0) + 1
    return counts


def _print(report: EvalReport, *, posts_by_file: dict[str, int]) -> None:
    out = print

    out(f"\nGolden set: {report.total_posts} posts")
    for name, count in sorted(posts_by_file.items()):
        out(f"  {count:>4}  {name}")

    out("\nIs it a listing?")
    confusion = report.listing_confusion
    out(f"  kept correctly      {confusion['true_positive']:>4}")
    out(f"  dropped correctly   {confusion['true_negative']:>4}")
    out(f"  wrongly kept        {confusion['false_positive']:>4}")
    out(f"  wrongly dropped     {confusion['false_negative']:>4}")
    out(f"  rejection precision {report.rejection_precision:>7.1%}")
    out(f"  listing recall      {report.listing_recall:>7.1%}")

    if report.reject_reasons:
        out("\nRejection reasons")
        for reason, count in report.reject_reasons.most_common():
            out(f"  {count:>4}  {reason}")

    out("\nField accuracy (SPEC 1.5 measures the first five)")
    for name in (*SPEC_FIELDS, "reject_reason", *EXTRA_FIELDS):
        entry = report.fields.get(name)
        if entry is None or entry.total == 0:
            continue
        marker = "*" if name in SPEC_FIELDS else " "
        out(f" {marker}{name:<16} {entry.accuracy:>6.1%}  ({entry.correct}/{entry.total})")

    worst = [(name, entry) for name, entry in report.fields.items() if entry.mistakes]
    if worst:
        out("\nMistakes (first few per field)")
        for name, entry in worst:
            out(f"  {name}")
            for post_id, expected, actual in entry.mistakes[:MISTAKES_SHOWN]:
                out(f"    {post_id:<16} expected {expected!r}, got {actual!r}")
            if len(entry.mistakes) > MISTAKES_SHOWN:
                out(f"    ... and {len(entry.mistakes) - MISTAKES_SHOWN} more")

    out("")


def _verdict(report: EvalReport, min_field: float, min_precision: float) -> int:
    failures: list[str] = []

    for name in SPEC_FIELDS:
        entry = report.fields[name]
        if entry.total and entry.accuracy < min_field:
            failures.append(f"{name} {entry.accuracy:.1%} < {min_field:.1%}")

    if report.rejection_precision < min_precision:
        failures.append(
            f"rejection precision {report.rejection_precision:.1%} < {min_precision:.1%}"
        )

    if failures:
        print("FAILED thresholds:")  # noqa: T201
        for failure in failures:
            print(f"  {failure}")  # noqa: T201
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
