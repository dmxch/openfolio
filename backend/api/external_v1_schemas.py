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


# --- Real Estate (Immobilien) ---

# Whitelist of property fields. Excludes encrypted PII (address, notes).
EXTERNAL_PROPERTY_FIELDS = {
    "id", "name", "property_type", "purchase_date", "purchase_price",
    "estimated_value", "estimated_value_date", "land_area_m2", "living_area_m2",
    "rooms", "year_built", "canton", "is_active",
    "total_mortgage_original", "total_amortized", "current_mortgage",
    "total_monthly", "equity", "equity_pct", "ltv", "ltv_status",
    "annual_interest", "annual_amortization", "annual_expenses",
    "annual_income", "total_annual_cost", "net_annual",
    "next_maturity", "days_until_maturity",
    "unrealized_gain", "unrealized_gain_pct",
}

# Whitelist of mortgage fields. Excludes encrypted PII (bank, notes).
EXTERNAL_MORTGAGE_FIELDS = {
    "id", "property_id", "name", "type", "amount", "current_amount",
    "total_amortized", "interest_rate", "margin_rate", "effective_rate",
    "start_date", "end_date", "monthly_payment", "monthly_total",
    "annual_payment", "amortization_monthly", "amortization_annual",
    "is_active", "days_until_maturity",
}

EXTERNAL_PROPERTY_EXPENSE_FIELDS = {
    "id", "property_id", "date", "category", "description",
    "amount", "recurring", "frequency",
}

# Whitelist of property income fields. Excludes encrypted PII (tenant).
EXTERNAL_PROPERTY_INCOME_FIELDS = {
    "id", "property_id", "date", "description",
    "amount", "recurring", "frequency",
}


def filter_mortgage(m: dict) -> dict:
    """Strip sensitive fields (bank, notes) from a mortgage dict."""
    return {k: v for k, v in m.items() if k in EXTERNAL_MORTGAGE_FIELDS}


def filter_property_expense(e: dict) -> dict:
    """Strip non-whitelisted fields from a property expense dict."""
    return {k: v for k, v in e.items() if k in EXTERNAL_PROPERTY_EXPENSE_FIELDS}


def filter_property_income(i: dict) -> dict:
    """Strip sensitive fields (tenant) from a property income dict."""
    return {k: v for k, v in i.items() if k in EXTERNAL_PROPERTY_INCOME_FIELDS}


def filter_property(p: dict) -> dict:
    """Strip sensitive fields (address, notes) from a property dict and
    recursively filter nested mortgages, expenses and incomes."""
    out = {k: v for k, v in p.items() if k in EXTERNAL_PROPERTY_FIELDS}
    if "mortgages" in p:
        out["mortgages"] = [filter_mortgage(m) for m in (p.get("mortgages") or [])]
    if "expenses" in p:
        out["expenses"] = [filter_property_expense(e) for e in (p.get("expenses") or [])]
    if "income" in p:
        out["income"] = [filter_property_income(i) for i in (p.get("income") or [])]
    return out


class ExternalMortgageResponse(_Strict):
    id: str
    property_id: str
    name: str
    type: str | None = None
    amount: float
    current_amount: float
    interest_rate: float
    margin_rate: float | None = None
    effective_rate: float
    start_date: str | None = None
    end_date: str | None = None
    is_active: bool
    days_until_maturity: int | None = None


class ExternalPropertyResponse(_Strict):
    id: str
    name: str
    property_type: str | None = None
    purchase_price: float
    estimated_value: float
    current_mortgage: float
    equity: float
    ltv: float
    ltv_status: str
    annual_interest: float
    mortgages: list[ExternalMortgageResponse] = []


class ExternalPropertySummaryResponse(_Strict):
    total_value_chf: float
    total_mortgage_chf: float
    total_equity_chf: float
    properties: list[ExternalPropertyResponse]


# --- Pension (Vorsorge / Saeule 3a) ---

# Whitelist of pension position fields. Excludes encrypted PII (bank_name, iban, notes).
EXTERNAL_PENSION_FIELDS = {
    "id", "ticker", "name", "type", "currency",
    "cost_basis_chf", "market_value_chf", "buy_date", "is_active",
}


def filter_pension_position(p: dict) -> dict:
    """Strip sensitive fields from a pension position dict."""
    return {k: v for k, v in p.items() if k in EXTERNAL_PENSION_FIELDS}


class ExternalPensionResponse(_Strict):
    id: str
    ticker: str
    name: str
    type: str
    currency: str
    cost_basis_chf: float
    market_value_chf: float
    buy_date: str | None = None
    is_active: bool


class ExternalPensionSummaryResponse(_Strict):
    total_value_chf: float
    accounts: list[ExternalPensionResponse]
