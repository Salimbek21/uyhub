"""Operational tables: suppression list, LLM accounting, exchange rates."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from uyhub.models.base import Base, IdMixin, enum_column
from uyhub.models.enums import Currency, SuppressionReason


class SuppressedPhone(IdMixin, Base):
    """Phones whose listings must never be shown or posted (SPEC 3, SPEC 13).

    Stored as the same keyed hash as ``listings.phone_hashes``, so a seller can be
    honoured without us keeping their number.
    """

    __tablename__ = "suppressed_phones"

    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    reason: Mapped[SuppressionReason] = mapped_column(
        enum_column(SuppressionReason, "suppression_reason"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LlmCall(IdMixin, Base):
    """One Anthropic API call, for cost tracking and the daily budget guard."""

    __tablename__ = "llm_calls"

    raw_message_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("raw_messages.id", ondelete="SET NULL")
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # "What have we spent today" — the budget guard's only query.
        Index("ix_llm_calls_created_at", "created_at"),
    )


class ExchangeRate(IdMixin, Base):
    """Daily CBU rate used to derive ``listings.price_usd`` from a UZS price."""

    __tablename__ = "exchange_rates"

    date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[Currency] = mapped_column(enum_column(Currency, "currency"), nullable=False)
    rate_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    __table_args__ = (UniqueConstraint("date", "currency", name="uq_exchange_rates_date_currency"),)
