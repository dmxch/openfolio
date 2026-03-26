"""Private Equity / Direktbeteiligungen models."""

import uuid
from datetime import date, datetime

from dateutils import utcnow
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class PrivateEquityHolding(Base):
    __tablename__ = "private_equity_holdings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet-encrypted
    num_shares: Mapped[int] = mapped_column(Integer, nullable=False)
    nominal_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    purchase_price_per_share: Mapped[float | None] = mapped_column(Numeric(10, 2))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CHF")
    uid_number: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted (UID des Unternehmens)
    register_nr: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted
    notes: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    valuations: Mapped[list["PrivateEquityValuation"]] = relationship(
        back_populates="holding", cascade="all, delete-orphan", order_by="PrivateEquityValuation.valuation_date.desc()"
    )
    dividends: Mapped[list["PrivateEquityDividend"]] = relationship(
        back_populates="holding", cascade="all, delete-orphan", order_by="PrivateEquityDividend.payment_date.desc()"
    )


class PrivateEquityValuation(Base):
    __tablename__ = "private_equity_valuations"
    __table_args__ = (
        UniqueConstraint("holding_id", "valuation_date", name="uq_pe_valuation_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    holding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("private_equity_holdings.id", ondelete="CASCADE"), nullable=False, index=True)
    valuation_date: Mapped[date] = mapped_column(Date, nullable=False)
    gross_value_per_share: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    discount_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=30.0)
    net_value_per_share: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    source: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    holding: Mapped["PrivateEquityHolding"] = relationship(back_populates="valuations")


class PrivateEquityDividend(Base):
    __tablename__ = "private_equity_dividends"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    holding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("private_equity_holdings.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    dividend_per_share: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    gross_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    withholding_tax_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=35.0)
    withholding_tax_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    net_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    holding: Mapped["PrivateEquityHolding"] = relationship(back_populates="dividends")
