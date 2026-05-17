"""Pydantic response schemas + Filter-Helfer für die externe REST-API.

Vertragsentscheidungen (v0.38+):
1. Stabiler Vertrag pro `/v1/`-Major-Version.
2. PII-Felder werden vom Token-Eigentümer ausgeliefert (es sind seine eigenen
   Daten). Einzige Ausnahme: ``iban`` ist immer maskiert (letzte 4 Stellen),
   identisch zum internen UI-Verhalten via ``decrypt_and_mask_iban``.
3. Schreib-Endpoints sind bewusst von den internen Schemas entkoppelt
   (Whitelist), damit interne Erweiterungen nicht versehentlich extern
   akzeptiert werden.
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
    style: str | None = None
    bucket_id: str | None = None
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

# Whitelist of position fields exposed externally.
# IBAN wird vom Router pre-maskiert — der Mask-Helper läuft im Enrichment,
# nicht hier.  Ändert sich der Whitelist, müssen Tests in
# ``test_external_api.py`` (PII-Sichtbarkeit / IBAN-Maskierung) mitgezogen
# werden.
EXTERNAL_POSITION_FIELDS = {
    "id", "ticker", "name", "type", "sector", "industry", "currency",
    "shares", "cost_basis_chf", "market_value_chf", "current_price",
    "price_currency", "pnl_chf", "pnl_pct", "weight_pct",
    "style", "mansfield_rs", "ma_status", "ma_detail",
    "buy_date", "is_etf", "is_stale",
    # PII / Konto-Metadaten (v0.38: Token-Eigentümer darf eigene Daten lesen)
    "bank_name", "iban", "notes",
    # Stop-Loss-Felder
    "stop_loss_price", "stop_loss_method", "stop_loss_confirmed_at_broker",
    "stop_loss_updated_at", "manual_resistance",
    # UI-Annotationen
    "active_alerts", "change_pct_24h",
    # Bucket-Feature (v0.39)
    "bucket_id", "risk_rules",
}


def filter_position(pos: dict) -> dict:
    """Whitelist-Filter für externe Position-Dicts."""
    return {k: v for k, v in pos.items() if k in EXTERNAL_POSITION_FIELDS}


# --- Bucket-Feature (v0.39) ---

EXTERNAL_BUCKET_FIELDS = {
    "id", "name", "kind", "system_role", "color", "benchmark",
    "target_pct", "target_chf", "description", "sort_order",
    "risk_rules", "deleted_at",
}


def filter_bucket(bucket: dict) -> dict:
    """Whitelist-Filter für externe Bucket-Dicts."""
    return {k: v for k, v in bucket.items() if k in EXTERNAL_BUCKET_FIELDS}


# --- Real Estate (Immobilien) ---

# Property-Whitelist inkl. Klartext-Adresse und Notes (v0.38).
EXTERNAL_PROPERTY_FIELDS = {
    "id", "name", "property_type", "purchase_date", "purchase_price",
    "estimated_value", "estimated_value_date", "land_area_m2", "living_area_m2",
    "rooms", "year_built", "canton", "is_active",
    "address", "notes",
    "total_mortgage_original", "total_amortized", "current_mortgage",
    "total_monthly", "equity", "equity_pct", "ltv", "ltv_status",
    "annual_interest", "annual_amortization", "annual_expenses",
    "annual_income", "total_annual_cost", "net_annual",
    "next_maturity", "days_until_maturity",
    "unrealized_gain", "unrealized_gain_pct",
}

# Mortgage-Whitelist inkl. bank/notes (v0.38).
EXTERNAL_MORTGAGE_FIELDS = {
    "id", "property_id", "name", "type", "amount", "current_amount",
    "total_amortized", "interest_rate", "margin_rate", "effective_rate",
    "start_date", "end_date", "monthly_payment", "monthly_total",
    "annual_payment", "amortization_monthly", "amortization_annual",
    "is_active", "days_until_maturity",
    "bank", "notes",
}

EXTERNAL_PROPERTY_EXPENSE_FIELDS = {
    "id", "property_id", "date", "category", "description",
    "amount", "recurring", "frequency",
}

# Income-Whitelist inkl. Mieter-Klartext (v0.38).
EXTERNAL_PROPERTY_INCOME_FIELDS = {
    "id", "property_id", "date", "description",
    "amount", "recurring", "frequency",
    "tenant",
}


def filter_mortgage(m: dict) -> dict:
    """Whitelist-Filter für Mortgage-Dicts."""
    return {k: v for k, v in m.items() if k in EXTERNAL_MORTGAGE_FIELDS}


def filter_property_expense(e: dict) -> dict:
    """Whitelist-Filter für Property-Expense-Dicts."""
    return {k: v for k, v in e.items() if k in EXTERNAL_PROPERTY_EXPENSE_FIELDS}


def filter_property_income(i: dict) -> dict:
    """Whitelist-Filter für Property-Income-Dicts (inkl. tenant)."""
    return {k: v for k, v in i.items() if k in EXTERNAL_PROPERTY_INCOME_FIELDS}


def filter_property(p: dict) -> dict:
    """Whitelist-Filter für Property-Dict, rekursiv für mortgages/expenses/income."""
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

# Pension-Whitelist inkl. bank_name/iban (maskiert)/notes (v0.38).
EXTERNAL_PENSION_FIELDS = {
    "id", "ticker", "name", "type", "currency",
    "cost_basis_chf", "market_value_chf", "buy_date", "is_active",
    "bank_name", "iban", "notes",
}


def filter_pension_position(p: dict) -> dict:
    """Whitelist-Filter für Pension-Position-Dicts."""
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


# --- Settings-Filter (Secrets entfernen) ---

# Felder, die bei `/settings` NIEMALS exponiert werden — egal ob im Klartext
# oder verschlüsselt. Ersatz: Boolean ``has_<feld>`` bzw. ``<feld>_configured``.
SETTINGS_SECRET_FIELDS = {
    "fred_api_key", "fmp_api_key", "finnhub_api_key",
}


def filter_settings(settings: dict) -> dict:
    """Maskiere alle Secret-Felder im Settings-Dict.

    Behält boolean-Indikatoren (`has_fred_api_key` etc.), entfernt rohe Schlüssel
    und maskierte Schlüssel (sonst leakt Substring der Maskierung).  Internes
    Settings-Endpoint liefert bereits keine Klartext-Schlüssel — die Filterung
    hier ist ein zweiter Riegel.
    """
    out = {k: v for k, v in settings.items() if k not in SETTINGS_SECRET_FIELDS}
    # Falls das interne Endpoint maskierte Varianten exponiert (`*_masked`),
    # werden sie hier entfernt — der Konsument soll nur das Boolean sehen.
    for f in list(out.keys()):
        if f.endswith("_api_key_masked"):
            out.pop(f, None)
    return out


# --- Schreib-Schemas (X-API-Key + scope=write) ---
#
# Diese Schemas sind bewusst entkoppelt von den internen ``AlertCreate`` /
# ``AlertUpdate`` Schemas in ``api/alerts.py``. Vererbung oder Re-Export wuerde
# bedeuten, dass jede zukuenftige interne Erweiterung (z.B. ``is_admin_override``)
# automatisch auch durch die externe API akzeptiert wird. Whitelist hier,
# damit der externe Vertrag stabil bleibt.

from pydantic import Field
from typing import Literal, Optional
from datetime import datetime

NOTES_MAX_LEN = 10_000

# Hard-Cap für Stop-Loss-Batch-Operationen.  Internal API hat kein explizites
# Limit; extern bewusst strenger, um Skript-Bugs (z.B. fehlerhafte 16k-Loops)
# abzufangen, bevor sie das System belasten.
STOP_LOSS_BATCH_MAX_ITEMS = 100


class ExternalNotesUpdate(_Strict):
    content: str = Field(
        max_length=NOTES_MAX_LEN,
        description="Notiz-Text (max. 10 000 Zeichen). Leerstring loescht die Notiz.",
    )
    mode: Literal["replace", "append"] = "replace"


class ExternalAlertCreate(_Strict):
    ticker: str = Field(min_length=1, max_length=30)
    alert_type: Literal["price_above", "price_below", "pct_change_day"]
    target_value: float = Field(gt=0)
    currency: Optional[str] = Field(default=None, max_length=3)
    notify_in_app: bool = True
    notify_email: bool = False
    note: Optional[str] = Field(default=None, max_length=200)
    expires_at: Optional[datetime] = None


class ExternalAlertUpdate(_Strict):
    target_value: Optional[float] = Field(default=None, gt=0)
    note: Optional[str] = Field(default=None, max_length=200)
    notify_in_app: Optional[bool] = None
    notify_email: Optional[bool] = None
    expires_at: Optional[datetime] = None


class ExternalWatchlistAdd(_Strict):
    ticker: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    sector: Optional[str] = Field(default=None, max_length=100)


# --- Pending Orders ---
#
# Bewusst entkoppelt von ``api/orders.py`` — dort liegt das interne Schema mit
# ``Decimal`` und ``model_validator``, hier wird per ``float`` exponiert (alle
# externen Konsumenten serialisieren Numbers als JSON-float). Whitelist:
# jede zukuenftige interne Erweiterung (z.B. ein ``risk_score``) wird NICHT
# automatisch ueber die externe API akzeptiert.

from datetime import date as _date
from pydantic import model_validator


class ExternalPendingOrderCreate(_Strict):
    ticker: str = Field(min_length=1, max_length=30)
    side: Literal["buy", "sell"]
    shares: float = Field(gt=0)
    limit_price: float = Field(gt=0)
    stop_price: Optional[float] = Field(default=None, gt=0)
    currency: str = Field(default="USD", min_length=1, max_length=10)
    expiry_type: Literal["gtc", "day", "gtd"] = "gtc"
    expiry_date: Optional[_date] = None
    broker: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _gtd_requires_date(self):
        if self.expiry_type == "gtd" and self.expiry_date is None:
            raise ValueError("expiry_date ist bei expiry_type='gtd' Pflicht")
        if self.expiry_type != "gtd" and self.expiry_date is not None:
            raise ValueError("expiry_date nur bei expiry_type='gtd' erlaubt")
        return self


class ExternalPendingOrderUpdate(_Strict):
    """PATCH-Body. Status-Wechsel auf ``filled`` laeuft nur ueber /fill."""

    side: Optional[Literal["buy", "sell"]] = None
    shares: Optional[float] = Field(default=None, gt=0)
    limit_price: Optional[float] = Field(default=None, gt=0)
    stop_price: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = Field(default=None, min_length=1, max_length=10)
    expiry_type: Optional[Literal["gtc", "day", "gtd"]] = None
    expiry_date: Optional[_date] = None
    broker: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[Literal["open", "cancelled"]] = None


class ExternalPendingOrderFill(_Strict):
    price_per_share: float = Field(gt=0)
    fill_date: _date
    fees_chf: float = Field(default=0.0, ge=0)
    taxes_chf: float = Field(default=0.0, ge=0)
    fx_rate_to_chf: float = Field(default=1.0, gt=0)
    notes: Optional[str] = Field(default=None, max_length=2000)


# --- Stop-Loss ---
#
# Whitelist-Schemas analog zum internen ``StopLossUpdate`` /
# ``StopLossBatchRequest`` (api/stoploss.py).  Wichtig:
# ``stop_loss_confirmed_at_broker`` hat **explizit** Default ``False`` —
# ein API-Aufruf ohne dieses Feld darf KEINE Broker-Bestätigung impliziert
# setzen.

class ExternalStopLossUpdate(_Strict):
    stop_loss_price: Optional[float] = Field(default=None, ge=0)
    confirmed_at_broker: bool = False
    method: Optional[str] = Field(default=None, max_length=50)


class ExternalStopLossBatchItem(_Strict):
    ticker: str = Field(min_length=1, max_length=30)
    stop_loss_price: float = Field(gt=0)
    confirmed_at_broker: bool = False
    method: Optional[str] = Field(default=None, max_length=50)


class ExternalStopLossBatchRequest(_Strict):
    items: list[ExternalStopLossBatchItem] = Field(
        min_length=1, max_length=STOP_LOSS_BATCH_MAX_ITEMS,
    )
