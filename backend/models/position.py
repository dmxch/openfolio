import enum
import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

STOP_LOSS_METHODS = ("trailing_pct", "higher_low", "ma_based", "structural")
CORE_STOP_METHODS = ("structural", "ma_based")
SATELLITE_STOP_METHODS = ("trailing_pct", "higher_low", "ma_based")

from models.base import Base


class AssetType(str, enum.Enum):
    stock = "stock"
    etf = "etf"
    crypto = "crypto"
    commodity = "commodity"
    cash = "cash"
    pension = "pension"
    real_estate = "real_estate"


class PricingMode(str, enum.Enum):
    auto = "auto"
    manual = "manual"


class PriceSource(str, enum.Enum):
    yahoo = "yahoo"
    coingecko = "coingecko"
    gold_org = "gold_org"
    manual = "manual"


class Style(str, enum.Enum):
    defensive = "defensive"
    compounder = "compounder"
    core = "core"
    opportunistic = "opportunistic"
    cash = "cash"


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_position_user_ticker"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CHF")
    pricing_mode: Mapped[PricingMode] = mapped_column(Enum(PricingMode), nullable=False, default=PricingMode.auto)
    risk_class: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    style: Mapped[Style | None] = mapped_column(Enum(Style))
    position_type: Mapped[str | None] = mapped_column(String(10))  # 'core' or 'satellite'
    yfinance_ticker: Mapped[str | None] = mapped_column(String(30))
    coingecko_id: Mapped[str | None] = mapped_column(String(100))
    gold_org: Mapped[bool] = mapped_column(Boolean, default=False)
    price_source: Mapped[PriceSource] = mapped_column(Enum(PriceSource), nullable=False, default=PriceSource.yahoo)
    isin: Mapped[str | None] = mapped_column(String(20))
    shares: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    cost_basis_chf: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    current_price: Mapped[float | None] = mapped_column(Numeric(14, 4))
    manual_resistance: Mapped[float | None] = mapped_column(Numeric(12, 4))
    stop_loss_price: Mapped[float | None] = mapped_column(Numeric(14, 4))
    stop_loss_confirmed_at_broker: Mapped[bool] = mapped_column(Boolean, default=False)
    stop_loss_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    stop_loss_method: Mapped[str | None] = mapped_column(String(30))
    next_earnings_date: Mapped[datetime | None] = mapped_column(DateTime)
    is_etf: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(Text)
    iban: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
