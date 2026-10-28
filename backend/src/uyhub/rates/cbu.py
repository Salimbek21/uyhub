"""Exchange rates from the Central Bank of Uzbekistan.

The parser needs these to express a so'm price in dollars, which is the only
unit the feed can sort and filter on when half the posts quote one currency and
half the other.

The API is public, unauthenticated and occasionally slow, so every call has a
timeout and bounded retries, and it sits behind a protocol the tests replace
(CLAUDE.md "Code rules").
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from uyhub.core.config import Settings, get_settings
from uyhub.core.errors import DependencyUnavailableError
from uyhub.core.logging import get_logger
from uyhub.models.enums import Currency

log = get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 15.0
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class Rate:
    """One currency's rate against the so'm on one day."""

    currency: Currency
    rate_uzs: Decimal
    on_date: date


class RateProvider(Protocol):
    """Where today's rates come from."""

    async def fetch(self, currency: Currency = Currency.USD) -> Rate: ...


class CbuRateProvider:
    """:class:`RateProvider` backed by cbu.uz."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def fetch(self, currency: Currency = Currency.USD) -> Rate:
        url = f"{self._settings.cbu_api_url.rstrip('/')}/{currency.value}/"
        payload = await self._get(url)
        return _parse(payload, currency)

    async def _get(self, url: str) -> list[dict[str, Any]]:
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    body: list[dict[str, Any]] = response.json()
                    return body
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    break
                # Jittered backoff so several workers do not retry in lockstep.
                delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                await asyncio.sleep(delay + random.uniform(0, delay / 2))  # noqa: S311

        raise DependencyUnavailableError("cbu", type(last_error).__name__)


def _parse(payload: list[dict[str, Any]], currency: Currency) -> Rate:
    """Read the one entry cbu.uz returns for a single currency."""
    if not payload:
        raise DependencyUnavailableError("cbu", "empty response")

    entry = payload[0]
    try:
        rate = Decimal(str(entry["Rate"]))
        nominal = Decimal(str(entry.get("Nominal", "1")) or "1")
        on_date = _parse_date(str(entry["Date"]))
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise DependencyUnavailableError("cbu", f"unexpected payload: {exc}") from exc

    if rate <= 0 or nominal <= 0:
        raise DependencyUnavailableError("cbu", "non-positive rate")

    # `Nominal` is how many units the rate is quoted for; it is 1 for USD but
    # 100 or 1000 for some currencies, and ignoring it would be off by that factor.
    return Rate(currency=currency, rate_uzs=rate / nominal, on_date=on_date)


def _parse_date(raw: str) -> date:
    """cbu.uz formats dates as ``DD.MM.YYYY``."""
    day, month, year = (int(part) for part in raw.split("."))
    return date(year, month, day)
