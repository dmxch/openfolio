import enum
import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

# JSONB in Production (PostgreSQL), JSON-Fallback fuer SQLite-Tests.
_POSITION_RISK_RULES_TYPE = JSON().with_variant(JSONB(), "postgresql")

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
    private_equity = "private_equity"


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
        # F-17: Partial UNIQUE auf (user_id, ticker, bucket_id) WHERE is_active.
        # Erlaubt zwei aktive Positions desselben Tickers in unterschiedlichen
        # Buckets (Teil-Wechsel). Geschlossene Positions sind ausgenommen.
        Index(
            "uq_position_user_ticker_bucket_active",
            "user_id",
            "ticker",
            "bucket_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
            sqlite_where=text("is_active IS TRUE"),
        ),
        Index("ix_positions_user_active", "user_id", "is_active"),
        Index("idx_positions_bucket_id", "bucket_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bucket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("buckets.id", ondelete="SET NULL"),
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CHF")
    pricing_mode: Mapped[PricingMode] = mapped_column(Enum(PricingMode), nullable=False, default=PricingMode.auto)
    style: Mapped[Style | None] = mapped_column(Enum(Style))
    # Position-Level Risk-Override (Phase 2, Plan §7.7). Wenn gesetzt, hat es
    # Vorrang vor bucket.risk_rules. None = Bucket-Rules greifen.
    risk_rules: Mapped[dict | None] = mapped_column(_POSITION_RISK_RULES_TYPE)
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
    # Cash-Klassifikation fuer Geldmarkt-/T-Bill-ETFs: die Position bleibt eine
    # echte, live-bepreiste Wertschrift (shares × price × fx, Performance laeuft
    # normal), wird aber in Allokation/Cash-Quote/Snapshots als Cash gezaehlt.
    count_as_cash: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(Text)
    iban: Mapped[str | None] = mapped_column(Text)
    # Sticky-Override fuer den Dividenden-Tracker (R1). NULL = nutze die
    # Auflösungsreihenfolge: ISIN-Country-Map → user_settings.dividend_withholding_default.
    # Wird vom Confirm-Modal gesetzt, wenn der User den Vorschlag editiert.
    dividend_withholding_pct: Mapped[float | None] = mapped_column(Numeric(5, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
