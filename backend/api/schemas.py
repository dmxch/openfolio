"""Shared Pydantic models used across multiple API routers."""

from datetime import date, datetime
from pydantic import BaseModel, Field


class RecalculateRequest(BaseModel):
    tickers: list[str] | None = None


class ValidateTokenRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=500)


# --- Position Response ---

class PositionResponse(BaseModel):
    id: str
    ticker: str
    name: str
    type: str
    sector: str | None = None
    industry: str | None = None
    currency: str
    pricing_mode: str
    risk_class: int
    style: str | None = None
    position_type: str | None = None
    yfinance_ticker: str | None = None
    coingecko_id: str | None = None
    gold_org: bool | None = None
    price_source: str
    isin: str | None = None
    shares: float
    cost_basis_chf: float
    current_price: float | None = None
    manual_resistance: float | None = None
    stop_loss_price: float | None = None
    stop_loss_confirmed_at_broker: bool | None = None
    stop_loss_updated_at: str | None = None
    stop_loss_method: str | None = None
    next_earnings_date: str | None = None
    is_etf: bool
    is_active: bool
    notes: str | None = None
    bank_name: str | None = None
    iban: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"from_attributes": True}


# --- Transaction Response ---

class TransactionResponse(BaseModel):
    id: str
    position_id: str
    type: str
    date: str
    shares: float
    price_per_share: float
    currency: str
    fx_rate_to_chf: float
    fees_chf: float
    taxes_chf: float
    total_chf: float
    notes: str | None = None
    created_at: str | None = None
    ticker: str | None = None
    position_name: str | None = None

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    page: int
    per_page: int
    pages: int


# --- Portfolio Summary Response ---

class AllocationItem(BaseModel):
    name: str
    value_chf: float
    pct: float


class PortfolioPositionResponse(BaseModel):
    id: str
    ticker: str
    name: str
    type: str
    sector: str | None = None
    industry: str | None = None
    currency: str
    shares: float
    cost_basis_chf: float
    market_value_chf: float
    current_price: float | None = None
    price_currency: str | None = None
    pnl_chf: float
    pnl_pct: float
    risk_class: int | None = None
    position_type: str | None = None
    style: str | None = None
    weight_pct: float
    mansfield_rs: float | None = None
    ma_status: str | None = None
    ma_detail: dict | None = None
    buy_date: str | None = None
    stop_loss_price: float | None = None
    stop_loss_confirmed_at_broker: bool | None = None
    stop_loss_updated_at: str | None = None
    stop_loss_method: str | None = None
    next_earnings_date: str | None = None
    is_etf: bool | None = None
    is_multi_sector: bool | None = None
    has_sector_weights: bool | None = None
    is_stale: bool = False

    model_config = {"from_attributes": True}


class AllocationsResponse(BaseModel):
    by_type: list[AllocationItem]
    by_risk_class: list[AllocationItem]
    by_style: list[AllocationItem]
    by_sector: list[AllocationItem]
    by_currency: list[AllocationItem]
    by_core_satellite: list[AllocationItem]


class PortfolioSummaryResponse(BaseModel):
    total_invested_chf: float
    total_market_value_chf: float
    total_pnl_chf: float
    total_pnl_pct: float
    total_fees_chf: float
    positions: list[PortfolioPositionResponse]
    allocations: AllocationsResponse
    fx_rates: dict[str, float]
