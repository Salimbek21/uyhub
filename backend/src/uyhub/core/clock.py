"""Time access behind one function so tests can freeze it.

Every timestamp in this system is timezone-aware UTC (SPEC.md section 3). Code must
never call ``datetime.now()`` directly; ruff's DTZ rules enforce that.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

TASHKENT_TZ_OFFSET_HOURS = 5
"""Asia/Tashkent is UTC+5 year-round (no DST). Used for daily digests, SPEC 11."""


def now_utc() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def today_utc() -> date:
    """Current UTC calendar date."""
    return now_utc().date()
