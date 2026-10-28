"""Storing and reading exchange rates.

The parser asks for "the current rate" on every so'm-priced post, so the lookup
is the hot path and the refresh is a once-a-day job. The latest stored rate is
used even when it is a few days old: a stale rate moves a price by a fraction
of a percent, while no rate at all drops ``price_usd`` entirely and takes the
listing out of every price filter.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.core.clock import today_utc
from uyhub.core.logging import get_logger
from uyhub.models.enums import Currency
from uyhub.models.ops import ExchangeRate
from uyhub.rates.cbu import Rate

log = get_logger(__name__)

MAX_RATE_AGE_DAYS = 14
"""Older than this and we would rather have no number than a wrong one."""


async def save_rate(session: AsyncSession, rate: Rate) -> None:
    """Upsert one day's rate. Re-running the job is harmless."""
    await session.execute(
        insert(ExchangeRate)
        .values(
            date=rate.on_date,
            currency=rate.currency,
            rate_uzs=rate.rate_uzs,
        )
        .on_conflict_do_update(
            constraint="uq_exchange_rates_date_currency",
            set_={"rate_uzs": rate.rate_uzs},
        )
    )
    log.info(
        "rates.stored",
        currency=rate.currency.value,
        date=rate.on_date.isoformat(),
        rate=str(rate.rate_uzs),
    )


async def latest_rate(
    session: AsyncSession,
    currency: Currency = Currency.USD,
    *,
    on: date | None = None,
) -> Decimal | None:
    """The most recent rate not older than :data:`MAX_RATE_AGE_DAYS`."""
    cutoff = (on or today_utc()) - timedelta(days=MAX_RATE_AGE_DAYS)
    stmt = (
        select(ExchangeRate.rate_uzs)
        .where(ExchangeRate.currency == currency, ExchangeRate.date >= cutoff)
        .order_by(ExchangeRate.date.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
