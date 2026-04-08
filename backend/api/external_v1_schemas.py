"""Pydantic response schemas for the external read-only API.

These schemas exist to:
1. Pin a stable contract for external consumers (versioned via /v1/).
2. Filter sensitive fields (bank_name, iban) — even if internal services
   add them, they can never accidentally leak through here.
"""

from typing import Any
from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    """Base for response models — forbid unknown extras to fail loudly in tests."""
    model_config = ConfigDict(extra="ignore")


# --- Position ---

class ExternalPosition(_Strict):
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
    weight_pct: float
    position_type: str | None = None
    style: str | None = None
    mansfield_rs: float | None = None
    ma_status: str | None = None
    buy_date: str | None = None
    is_etf: bool = False


class ExternalAllocationItem(_Strict):
    label: str | None = None
    name: str | None = None
    value_chf: float | None = None
    weight_pct: float | None = None


class ExternalPortfolioSummary(_Strict):
    total_invested_chf: float
    total_market_value_chf: float
    total_pnl_chf: float
    total_pnl_pct: float
    total_fees_chf: float
    positions: list[ExternalPosition]
    allocations: dict[str, list[dict[str, Any]]]
    fx_rates: dict[str, float] | None = None


# --- Performance ---

class ExternalHistoryPoint(_Strict):
    date: str | None = None
    value_chf: float | None = None
    invested_chf: float | None = None
    benchmark: float | None = None


class ExternalHistoryResponse(_Strict):
    history: list[dict[str, Any]] | None = None
    benchmark: str | None = None


class ExternalMonthlyReturn(_Strict):
    month: str | None = None
    return_pct: float | None = None


# --- Screening ---

class ExternalScreeningResult(_Strict):
    ticker: str
    name: str | None = None
    sector: str | None = None
    score: int
    signals: dict[str, Any] | None = None
    price_usd: float | None = None


class ExternalScreeningResponse(_Strict):
    scan_id: str | None = None
    scanned_at: str | None = None
    total: int
    results: list[ExternalScreeningResult]


# --- Helpers used by the router ---

# Whitelist of position fields exposed externally — explicitly excludes
# bank_name, iban, notes, and any internal stop-loss/risk metadata.
EXTERNAL_POSITION_FIELDS = {
    "id", "ticker", "name", "type", "sector", "industry", "currency",
    "shares", "cost_basis_chf", "market_value_chf", "current_price",
    "price_currency", "pnl_chf", "pnl_pct", "weight_pct",
    "position_type", "style", "mansfield_rs", "ma_status", "ma_detail",
    "buy_date", "is_etf", "is_stale",
}


def filter_position(pos: dict) -> dict:
    """Strip sensitive fields from a position dict."""
    return {k: v for k, v in pos.items() if k in EXTERNAL_POSITION_FIELDS}
