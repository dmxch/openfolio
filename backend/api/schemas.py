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


# --- Auth Responses ---

class UserInfo(BaseModel):
    id: str
    email: str
    mfa_enabled: bool
    mfa_setup_required: bool | None = None
    is_admin: bool
    force_password_change: bool


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    mfa_setup_required: bool
    user: UserInfo


class MfaRequiredResponse(BaseModel):
    mfa_required: bool = True


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    created_at: str


class MeResponse(BaseModel):
    id: str
    email: str
    mfa_enabled: bool
    is_admin: bool
    force_password_change: bool
    created_at: str
    backup_codes_remaining: int


class SessionResponse(BaseModel):
    id: str
    user_agent: str | None = None
    ip_address: str | None = None
    created_at: str | None = None


class MfaSetupResponse(BaseModel):
    secret: str
    qr_code_uri: str


class MfaVerifyResponse(BaseModel):
    mfa_enabled: bool
    backup_codes: list[str]


class BackupCodesResponse(BaseModel):
    backup_codes: list[str]


class MessageResponse(BaseModel):
    message: str


class OkResponse(BaseModel):
    ok: bool


# --- Admin Responses ---

class AdminUserResponse(BaseModel):
    id: str
    email: str
    is_active: bool
    is_admin: bool
    mfa_enabled: bool
    force_password_change: bool
    created_at: str | None = None
    last_login_at: str | None = None


class AdminUserListResponse(BaseModel):
    users: list[AdminUserResponse]
    total: int


class AdminResetPasswordResponse(BaseModel):
    ok: bool
    message: str


class AdminTempPasswordResponse(BaseModel):
    ok: bool
    temp_password: str


class AdminSettingsResponse(BaseModel):
    registration_mode: str


class InviteCodeResponse(BaseModel):
    id: str
    code: str
    created_at: str | None = None
    used_by_email: str | None = None
    used_at: str | None = None
    is_active: bool


class InviteCodeListResponse(BaseModel):
    codes: list[InviteCodeResponse]


class AuditLogEntry(BaseModel):
    id: str
    admin_id: str | None = None
    admin_email: str | None = None
    action: str
    target_user_id: str | None = None
    details: str | None = None
    ip_address: str | None = None
    created_at: str | None = None


class AuditLogResponse(BaseModel):
    entries: list[AuditLogEntry]
    total: int
    page: int
    per_page: int
    pages: int


# --- Portfolio Performance Responses ---

class TotalReturnResponse(BaseModel):
    unrealized_pnl_chf: float
    realized_pnl_chf: float
    dividends_net_chf: float
    dividends_gross_chf: float
    dividends_tax_chf: float
    capital_gains_dist_chf: float
    interest_chf: float
    trading_fees_chf: float
    other_fees_chf: float
    total_fees_chf: float
    total_return_chf: float
    total_invested_chf: float
    total_return_pct: float
    ytd_chf: float | None = None
    ytd_pct: float | None = None
    ytd_year: int | None = None
    ytd_unrealized_chf: float | None = None
    ytd_realized_chf: float | None = None
    ytd_dividends_chf: float | None = None


class DailyChangePosition(BaseModel):
    ticker: str
    name: str
    change_chf: float
    change_pct: float
    market_value_chf: float


class DailyChangeResponse(BaseModel):
    total_change_chf: float
    total_change_pct: float
    positions: list[DailyChangePosition]
    as_of: str | None = None


class MonthCell(BaseModel):
    month: int
    return_pct: float | None = None
    method: str | None = None


class MonthlyReturnYear(BaseModel):
    year: int
    months: list[MonthCell]


class MonthlyReturnsResponse(BaseModel):
    months: list[MonthlyReturnYear]
    annual_totals: dict[str, float]


class RealizedGainItem(BaseModel):
    ticker: str
    name: str | None = None
    cost_basis_chf: float
    proceeds_chf: float
    fees_chf: float
    realized_pnl_chf: float
    realized_pnl_pct: float


class RealizedGainsResponse(BaseModel):
    items: list[RealizedGainItem]
    total_realized_pnl_chf: float


class FeeSummaryResponse(BaseModel):
    trading_fees_chf: float
    other_fees_chf: float
    total_fees_chf: float
    fee_ratio_pct: float | None = None
