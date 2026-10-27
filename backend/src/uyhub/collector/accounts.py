"""Userbot account state: the daily join budget and flood-wait bookkeeping.

The budget lives in the database rather than in process memory so that a restart
cannot hand the account a fresh allowance — which is exactly the behaviour that
gets a userbot banned (SPEC 4.2).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from uyhub.core.clock import now_utc
from uyhub.core.logging import get_logger
from uyhub.models.enums import AccountStatus
from uyhub.models.telegram import TgAccount

log = get_logger(__name__)

JOIN_BUDGET_WINDOW = timedelta(days=1)


def mask_phone(phone: str) -> str:
    """Keep the last four digits only. The full number is never stored (SPEC 13)."""
    digits = [char for char in phone if char.isdigit()]
    tail = "".join(digits[-4:])
    return f"***{tail}" if tail else "***"


async def ensure_account(session: AsyncSession, *, label: str, phone: str) -> TgAccount:
    """Create or update the row describing a logged-in userbot account."""
    existing = (
        await session.execute(select(TgAccount).where(TgAccount.label == label))
    ).scalar_one_or_none()

    masked = mask_phone(phone)
    if existing is not None:
        existing.phone_masked = masked
        existing.status = AccountStatus.ACTIVE
        await session.flush()
        return existing

    account = TgAccount(label=label, phone_masked=masked, status=AccountStatus.ACTIVE)
    session.add(account)
    await session.flush()
    log.info("account.created", account_id=account.id, label=label)
    return account


async def default_account(session: AsyncSession) -> TgAccount | None:
    """The account the MVP runs on: the first active one, by id."""
    stmt = (
        select(TgAccount)
        .where(TgAccount.status == AccountStatus.ACTIVE)
        .order_by(TgAccount.id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def claim_join_slot(session: AsyncSession, account_id: int, *, max_per_day: int) -> bool:
    """Consume one of today's joins. Returns False when the budget is spent.

    The row is locked for the duration so two collector processes cannot both
    see the last remaining slot.
    """
    account = (
        await session.execute(select(TgAccount).where(TgAccount.id == account_id).with_for_update())
    ).scalar_one_or_none()
    if account is None:
        return False

    now = now_utc()
    if account.joins_reset_at is None or now - account.joins_reset_at >= JOIN_BUDGET_WINDOW:
        account.joins_today = 0
        account.joins_reset_at = now

    if account.joins_today >= max_per_day:
        return False

    account.joins_today += 1
    await session.flush()
    return True


async def start_flood_wait(session: AsyncSession, account_id: int, until: datetime) -> None:
    """Park the account until Telegram says we may talk to it again."""
    await session.execute(
        update(TgAccount)
        .where(TgAccount.id == account_id)
        .values(status=AccountStatus.FLOOD_WAIT, flood_until=until)
    )
    log.warning("account.flood_wait", account_id=account_id, until=until.isoformat())


async def clear_flood_wait(session: AsyncSession, account_id: int) -> None:
    await session.execute(
        update(TgAccount)
        .where(TgAccount.id == account_id, TgAccount.status == AccountStatus.FLOOD_WAIT)
        .values(status=AccountStatus.ACTIVE, flood_until=None)
    )
