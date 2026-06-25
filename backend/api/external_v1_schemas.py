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

import uuid
from typing import Any
from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    """Base for response models — unbekannte Extras werden ignoriert
    (Vorwaerts-Kompatibilitaet bei Lese-Payloads)."""
    model_config = ConfigDict(extra="ignore")


class _StrictWrite(BaseModel):
    """Base for WRITE input schemas — unbekannte Felder werden mit 422
    abgelehnt. Verhindert dass ein vertippter Feldname (z. B. ``fee_chf``
    statt ``fees_chf``) still verworfen wird und mit Default-0 bucht."""
    model_config = ConfigDict(extra="forbid")


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
    score_display: int | None = None
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
    "buy_date", "is_etf", "count_as_cash", "is_stale",
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
    bucket_id_target: Optional[uuid.UUID] = None

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
    bucket_id_target: Optional[uuid.UUID] = None
    status: Optional[Literal["open", "cancelled"]] = None


class ExternalPendingOrderFill(_Strict):
    price_per_share: float = Field(gt=0)
    fill_date: _date
    fees_chf: float = Field(default=0.0, ge=0)
    taxes_chf: float = Field(default=0.0, ge=0)
    fx_rate_to_chf: float = Field(default=1.0, gt=0)
    currency: Optional[str] = Field(default=None, min_length=1, max_length=10)
    notes: Optional[str] = Field(default=None, max_length=2000)


# --- Transaktionen (Write) ---
#
# Whitelist-Mirror des internen ``TransactionCreate`` (api/transactions.py).
# Bewusst entkoppelt (Vertragsentscheidung 3): interne Felderweiterungen
# werden NICHT automatisch extern akzeptiert.  Entweder ``position_id`` ODER
# ``ticker`` angeben — bei unbekanntem Ticker wird die Position auto-angelegt,
# identisch zum UI.  Duplikat-Prueffung ist Aufgabe des Callers (kein impliziter
# Dedup, damit API-Paritaet zum UI gewahrt bleibt).

class ExternalTransactionCreate(_StrictWrite):
    position_id: Optional[uuid.UUID] = None
    ticker: Optional[str] = Field(default=None, max_length=60)
    asset_type: Optional[str] = Field(default=None, max_length=30)
    bucket_id: Optional[uuid.UUID] = None
    type: Literal[
        "buy", "sell", "dividend", "fee", "tax", "tax_refund",
        "delivery_in", "delivery_out", "deposit", "withdrawal",
        "capital_gain", "interest", "fx_credit", "fx_debit", "fee_correction",
    ]
    date: _date
    shares: float = Field(default=0, ge=0)
    price_per_share: float = Field(default=0, ge=0)
    currency: str = Field(default="CHF", min_length=3, max_length=3)
    fx_rate_to_chf: float = Field(default=1.0, gt=0)
    fees_chf: float = Field(default=0, ge=0)
    taxes_chf: float = Field(default=0, ge=0)
    total_chf: float = Field(default=0, ge=0)
    notes: Optional[str] = Field(default=None, max_length=2000)
    stop_loss_price: Optional[float] = Field(default=None, ge=0)
    stop_loss_method: Optional[str] = Field(default=None, max_length=50)
    stop_loss_confirmed_at_broker: Optional[bool] = None


class ExternalTransactionUpdate(_StrictWrite):
    """Whitelist-Mirror des internen ``TransactionUpdate`` — alle Felder
    optional (``exclude_unset`` greift). Position/Ticker/Typ sind bewusst NICHT
    aenderbar (wie im UI); fuer eine Umbuchung loeschen + neu anlegen."""
    date: Optional[_date] = None
    shares: Optional[float] = Field(default=None, ge=0)
    price_per_share: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    fx_rate_to_chf: Optional[float] = Field(default=None, gt=0)
    fees_chf: Optional[float] = Field(default=None, ge=0)
    taxes_chf: Optional[float] = Field(default=None, ge=0)
    total_chf: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = Field(default=None, max_length=2000)


# --- Positionen (Write) ---
#
# Whitelist-Mirror des internen ``PositionCreate`` / ``PositionUpdate``
# (api/positions.py). Bewusst entkoppelt (Vertragsentscheidung 3): interne
# Felderweiterungen werden NICHT automatisch extern akzeptiert. Enum-Werte
# (type/pricing_mode/style/price_source) werden als String exponiert und vom
# internen Schema gegen die Python-Enums validiert.

class ExternalPositionCreate(_StrictWrite):
    ticker: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    type: Literal[
        "stock", "etf", "crypto", "commodity", "cash",
        "real_estate", "private_equity", "pension",
    ]
    sector: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    currency: str = Field(default="CHF", min_length=3, max_length=3)
    pricing_mode: Optional[Literal["auto", "manual"]] = None
    style: Optional[str] = Field(default=None, max_length=50)
    bucket_id: Optional[uuid.UUID] = None
    yfinance_ticker: Optional[str] = Field(default=None, max_length=60)
    coingecko_id: Optional[str] = Field(default=None, max_length=100)
    gold_org: bool = False
    price_source: Optional[Literal["yahoo", "coingecko", "manual", "gold_org"]] = None
    isin: Optional[str] = Field(default=None, max_length=20)
    shares: float = Field(default=0, ge=0)
    cost_basis_chf: float = Field(default=0, ge=0)
    current_price: Optional[float] = Field(default=None, ge=0)
    count_as_cash: bool = False
    notes: Optional[str] = Field(default=None, max_length=2000)
    bank_name: Optional[str] = Field(default=None, max_length=200)
    iban: Optional[str] = Field(default=None, max_length=34)


class ExternalPositionUpdate(_StrictWrite):
    ticker: Optional[str] = Field(default=None, min_length=1, max_length=60)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    type: Optional[Literal[
        "stock", "etf", "crypto", "commodity", "cash",
        "real_estate", "private_equity", "pension",
    ]] = None
    sector: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    pricing_mode: Optional[Literal["auto", "manual"]] = None
    style: Optional[str] = Field(default=None, max_length=50)
    yfinance_ticker: Optional[str] = Field(default=None, max_length=60)
    coingecko_id: Optional[str] = Field(default=None, max_length=100)
    gold_org: Optional[bool] = None
    price_source: Optional[Literal["yahoo", "coingecko", "manual", "gold_org"]] = None
    isin: Optional[str] = Field(default=None, max_length=20)
    shares: Optional[float] = Field(default=None, ge=0)
    cost_basis_chf: Optional[float] = Field(default=None, ge=0)
    current_price: Optional[float] = Field(default=None, ge=0)
    count_as_cash: Optional[bool] = None
    manual_resistance: Optional[float] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    bank_name: Optional[str] = Field(default=None, max_length=200)
    iban: Optional[str] = Field(default=None, max_length=34)
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


# --- Report-Vault ---
#
# Upload-Schema fuer den Claude-Finance-Workspace (POST /reports, write-Scope).
# `source_path` ist der natuerliche Upsert-Key (ein Report pro Quelldatei).
# `category` ist bewusst KEIN strikter Enum — neue Brief-Typen sollen nicht
# am Schema scheitern; Normalisierung/Whitelisting passiert nicht hier.

class ReportUpload(_Strict):
    category: str = Field(default="other", max_length=50)
    title: str = Field(min_length=1, max_length=300)
    report_date: Optional[_date] = None
    body: str = Field(min_length=1, max_length=200_000)
    tags: Optional[list[str]] = Field(default=None)
    source: Optional[str] = Field(default=None, max_length=100)
    source_path: Optional[str] = Field(default=None, max_length=500)


class ReportPrune(_Strict):
    """Reconciliation: loescht Vault-Waisen einer Sync-Quelle.

    `source_paths` = die vollstaendige Menge der aktuell existierenden
    Quelldateien. Der Server loescht user-scoped alle Reports mit passendem
    `source`, deren `source_path` NICHT in dieser Menge ist (= geloeschte/
    umbenannte Briefe). Strikt auf `source` gescoped, damit nie fremde oder
    manuell angelegte Eintraege getroffen werden.

    SICHERHEIT: eine leere `source_paths`-Liste ist KEIN "loesche alles" —
    der Endpoint macht dann bewusst nichts (siehe upload_reports_prune).
    """
    source: str = Field(min_length=1, max_length=100)
    source_paths: list[str] = Field(default_factory=list, max_length=20_000)


class ReportPatch(_Strict):
    """Partielle Aenderung eines Reports per ID (PATCH /reports/{id}, write-Scope).

    Nur uebergebene Felder werden geaendert (``exclude_unset``-Semantik):
    - Feld weggelassen → unveraendert
    - ``tags: []`` → Tags bewusst leeren (vs. weggelassen = unveraendert)
    - ``body`` geaendert → ``content_hash`` wird serverseitig neu berechnet
    Mindestens ein Feld muss gesetzt sein, sonst No-op (``unchanged``).
    """
    category: Optional[str] = Field(default=None, max_length=50)
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    report_date: Optional[_date] = None
    body: Optional[str] = Field(default=None, min_length=1, max_length=200_000)
    tags: Optional[list[str]] = Field(default=None)


# --- Immobilien (Write) ---
#
# Whitelist-Mirror der internen Schemas in api/real_estate.py. Enums werden als
# Literal exponiert und vom internen Schema validiert.

class ExternalPropertyCreate(_StrictWrite):
    name: str = Field(min_length=1, max_length=200)
    address: Optional[str] = Field(default=None, max_length=500)
    property_type: Literal["efh", "mfh", "stockwerk", "grundstueck"]
    purchase_date: Optional[_date] = None
    purchase_price: float = Field(ge=0)
    estimated_value: Optional[float] = Field(default=None, ge=0)
    estimated_value_date: Optional[_date] = None
    land_area_m2: Optional[float] = Field(default=None, ge=0)
    living_area_m2: Optional[float] = Field(default=None, ge=0)
    rooms: Optional[float] = Field(default=None, ge=0, le=100)
    year_built: Optional[int] = Field(default=None, ge=1800, le=2100)
    canton: Optional[str] = Field(default=None, max_length=2)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ExternalPropertyUpdate(_StrictWrite):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    address: Optional[str] = Field(default=None, max_length=500)
    property_type: Optional[Literal["efh", "mfh", "stockwerk", "grundstueck"]] = None
    purchase_date: Optional[_date] = None
    purchase_price: Optional[float] = Field(default=None, ge=0)
    estimated_value: Optional[float] = Field(default=None, ge=0)
    estimated_value_date: Optional[_date] = None
    land_area_m2: Optional[float] = Field(default=None, ge=0)
    living_area_m2: Optional[float] = Field(default=None, ge=0)
    rooms: Optional[float] = Field(default=None, ge=0, le=100)
    year_built: Optional[int] = Field(default=None, ge=1800, le=2100)
    canton: Optional[str] = Field(default=None, max_length=2)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ExternalMortgageCreate(_StrictWrite):
    name: str = Field(min_length=1, max_length=200)
    type: Literal["fixed", "saron", "variable"]
    amount: float = Field(gt=0)
    interest_rate: float = Field(ge=0, le=100)
    margin_rate: Optional[float] = Field(default=None, ge=0, le=100)
    start_date: Optional[_date] = None
    end_date: Optional[_date] = None
    monthly_payment: Optional[float] = Field(default=None, ge=0)
    annual_payment: Optional[float] = Field(default=None, ge=0)
    amortization_monthly: Optional[float] = Field(default=None, ge=0)
    amortization_annual: Optional[float] = Field(default=None, ge=0)
    bank: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ExternalMortgageUpdate(_StrictWrite):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    type: Optional[Literal["fixed", "saron", "variable"]] = None
    amount: Optional[float] = Field(default=None, gt=0)
    interest_rate: Optional[float] = Field(default=None, ge=0, le=100)
    margin_rate: Optional[float] = Field(default=None, ge=0, le=100)
    start_date: Optional[_date] = None
    end_date: Optional[_date] = None
    monthly_payment: Optional[float] = Field(default=None, ge=0)
    annual_payment: Optional[float] = Field(default=None, ge=0)
    amortization_monthly: Optional[float] = Field(default=None, ge=0)
    amortization_annual: Optional[float] = Field(default=None, ge=0)
    bank: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ExternalPropertyExpenseCreate(_StrictWrite):
    date: _date
    category: Literal["insurance", "utilities", "maintenance", "repair", "tax", "other"]
    description: Optional[str] = Field(default=None, max_length=500)
    amount: float = Field(gt=0)
    recurring: bool = False
    frequency: Optional[Literal["monthly", "quarterly", "yearly", "once"]] = None


class ExternalPropertyExpenseUpdate(_StrictWrite):
    date: Optional[_date] = None
    category: Optional[Literal["insurance", "utilities", "maintenance", "repair", "tax", "other"]] = None
    description: Optional[str] = Field(default=None, max_length=500)
    amount: Optional[float] = Field(default=None, gt=0)
    recurring: Optional[bool] = None
    frequency: Optional[Literal["monthly", "quarterly", "yearly", "once"]] = None


class ExternalPropertyIncomeCreate(_StrictWrite):
    date: _date
    description: Optional[str] = Field(default=None, max_length=500)
    amount: float = Field(gt=0)
    tenant: Optional[str] = Field(default=None, max_length=200)
    recurring: bool = False
    frequency: Optional[Literal["monthly", "quarterly", "yearly", "once"]] = None


class ExternalPropertyIncomeUpdate(_StrictWrite):
    date: Optional[_date] = None
    description: Optional[str] = Field(default=None, max_length=500)
    amount: Optional[float] = Field(default=None, gt=0)
    tenant: Optional[str] = Field(default=None, max_length=200)
    recurring: Optional[bool] = None
    frequency: Optional[Literal["monthly", "quarterly", "yearly", "once"]] = None


# --- Private Equity (Write) ---

class ExternalPEHoldingCreate(_StrictWrite):
    company_name: str = Field(min_length=1, max_length=200)
    num_shares: int = Field(gt=0)
    nominal_value: float = Field(ge=0)
    purchase_price_per_share: Optional[float] = Field(default=None, ge=0)
    purchase_date: Optional[_date] = None
    currency: str = Field(default="CHF", max_length=3)
    uid_number: Optional[str] = Field(default=None, max_length=50)
    register_nr: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=1000)


class ExternalPEHoldingUpdate(_StrictWrite):
    company_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    num_shares: Optional[int] = Field(default=None, gt=0)
    nominal_value: Optional[float] = Field(default=None, ge=0)
    purchase_price_per_share: Optional[float] = Field(default=None, ge=0)
    purchase_date: Optional[_date] = None
    currency: Optional[str] = Field(default=None, max_length=3)
    uid_number: Optional[str] = Field(default=None, max_length=50)
    register_nr: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=1000)


class ExternalPEValuationCreate(_StrictWrite):
    valuation_date: _date
    gross_value_per_share: float = Field(ge=0)
    discount_pct: float = Field(default=30.0, ge=0, le=100)
    source: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=500)


class ExternalPEValuationUpdate(_StrictWrite):
    valuation_date: Optional[_date] = None
    gross_value_per_share: Optional[float] = Field(default=None, ge=0)
    discount_pct: Optional[float] = Field(default=None, ge=0, le=100)
    source: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=500)


class ExternalPEDividendCreate(_StrictWrite):
    payment_date: _date
    dividend_per_share: float = Field(ge=0)
    withholding_tax_pct: float = Field(default=35.0, ge=0, le=100)
    fiscal_year: int = Field(ge=1900, le=2100)
    notes: Optional[str] = Field(default=None, max_length=500)


class ExternalPEDividendUpdate(_StrictWrite):
    payment_date: Optional[_date] = None
    dividend_per_share: Optional[float] = Field(default=None, ge=0)
    withholding_tax_pct: Optional[float] = Field(default=None, ge=0, le=100)
    fiscal_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    notes: Optional[str] = Field(default=None, max_length=500)


EXTERNAL_PE_VALUATION_FIELDS = {
    "id", "valuation_date", "gross_value_per_share", "discount_pct",
    "net_value_per_share", "source", "notes",
}
EXTERNAL_PE_DIVIDEND_FIELDS = {
    "id", "payment_date", "dividend_per_share", "gross_amount",
    "withholding_tax_pct", "withholding_tax_amount", "net_amount",
    "fiscal_year", "notes",
}
EXTERNAL_PE_HOLDING_FIELDS = {
    "id", "company_name", "num_shares", "nominal_value",
    "purchase_price_per_share", "purchase_date", "currency", "uid_number",
    "register_nr", "notes", "is_active", "latest_valuation",
    "gross_value_per_share", "net_value_per_share", "total_gross_value",
    "total_net_value", "total_dividends_net", "dividend_yield_pct",
    "created_at", "valuations", "dividends",
}


def filter_pe_holding(h: dict) -> dict:
    """Whitelist-Filter für PE-Holding-Dicts (rekursiv für valuations/dividends).
    PII (company_name/uid_number/register_nr/notes) bleibt — Daten des
    Token-Eigentümers (v0.38-Vertrag)."""
    out = {k: v for k, v in h.items() if k in EXTERNAL_PE_HOLDING_FIELDS}
    if isinstance(out.get("valuations"), list):
        out["valuations"] = [
            {k: v for k, v in val.items() if k in EXTERNAL_PE_VALUATION_FIELDS}
            for val in out["valuations"]
        ]
    if isinstance(out.get("dividends"), list):
        out["dividends"] = [
            {k: v for k, v in d.items() if k in EXTERNAL_PE_DIVIDEND_FIELDS}
            for d in out["dividends"]
        ]
    if isinstance(out.get("latest_valuation"), dict):
        out["latest_valuation"] = {
            k: v for k, v in out["latest_valuation"].items()
            if k in EXTERNAL_PE_VALUATION_FIELDS
        }
    return out


# --- Edelmetalle (Write) ---

class ExternalMetalCreate(_StrictWrite):
    metal_type: Literal["gold", "silver", "platinum", "palladium"]
    form: Literal["bar", "coin", "other"]
    manufacturer: Optional[str] = Field(default=None, max_length=200)
    weight_grams: float = Field(gt=0)
    serial_number: Optional[str] = Field(default=None, max_length=100)
    fineness: Optional[str] = Field(default=None, max_length=10)
    purchase_date: _date
    purchase_price_chf: float = Field(ge=0)
    storage_location: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ExternalMetalUpdate(_StrictWrite):
    metal_type: Optional[Literal["gold", "silver", "platinum", "palladium"]] = None
    form: Optional[Literal["bar", "coin", "other"]] = None
    manufacturer: Optional[str] = Field(default=None, max_length=200)
    weight_grams: Optional[float] = Field(default=None, gt=0)
    serial_number: Optional[str] = Field(default=None, max_length=100)
    fineness: Optional[str] = Field(default=None, max_length=10)
    purchase_date: Optional[_date] = None
    purchase_price_chf: Optional[float] = Field(default=None, ge=0)
    storage_location: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)
    is_sold: Optional[bool] = None
    sold_date: Optional[_date] = None
    sold_price_chf: Optional[float] = Field(default=None, ge=0)


class ExternalMetalExpenseCreate(_StrictWrite):
    metal_type: Optional[Literal["gold", "silver", "platinum", "palladium"]] = None
    date: _date
    category: Literal["storage", "insurance", "other"]
    description: Optional[str] = Field(default=None, max_length=300)
    amount: float = Field(gt=0)
    recurring: bool = False
    frequency: Optional[Literal["monthly", "quarterly", "yearly", "once"]] = None


class ExternalMetalExpenseUpdate(_StrictWrite):
    metal_type: Optional[Literal["gold", "silver", "platinum", "palladium"]] = None
    date: Optional[_date] = None
    category: Optional[Literal["storage", "insurance", "other"]] = None
    description: Optional[str] = Field(default=None, max_length=300)
    amount: Optional[float] = Field(default=None, gt=0)
    recurring: Optional[bool] = None
    frequency: Optional[Literal["monthly", "quarterly", "yearly", "once"]] = None


EXTERNAL_METAL_ITEM_FIELDS = {
    "id", "metal_type", "form", "manufacturer", "weight_grams", "weight_oz",
    "serial_number", "fineness", "purchase_date", "purchase_price_chf",
    "storage_location", "is_sold", "sold_date", "sold_price_chf", "notes",
    "created_at",
}
EXTERNAL_METAL_EXPENSE_FIELDS = {
    "id", "metal_type", "date", "category", "description", "amount",
    "recurring", "frequency", "created_at",
}


def filter_metal_item(d: dict) -> dict:
    """Whitelist-Filter für Edelmetall-Item-Dicts (PII des Eigentümers bleibt)."""
    return {k: v for k, v in d.items() if k in EXTERNAL_METAL_ITEM_FIELDS}


def filter_metal_expense(d: dict) -> dict:
    """Whitelist-Filter für Edelmetall-Ausgaben-Dicts."""
    return {k: v for k, v in d.items() if k in EXTERNAL_METAL_EXPENSE_FIELDS}


# --- Dividenden (Write) ---

class ExternalDividendConfirm(_StrictWrite):
    date: _date
    total_chf: float = Field(ge=0)
    gross_amount: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=10)
    fx_rate_to_chf: float = Field(default=1.0, gt=0)
    withholding_pct: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ExternalDividendDismiss(_StrictWrite):
    reason: Optional[str] = Field(default=None, max_length=500)


# --- Analyse / ETF / EPS / Onboarding (Write) ---

class ExternalResistanceUpdate(_StrictWrite):
    manual_resistance: Optional[float] = Field(default=None, ge=0)


class ExternalTagCreate(_StrictWrite):
    name: str = Field(min_length=1, max_length=30)
    color: Optional[str] = Field(default=None, max_length=7)


class ExternalEtfSectorWeight(_StrictWrite):
    sector: str = Field(min_length=1, max_length=100)
    weight_pct: float = Field(ge=0, le=100)


class ExternalEtfSectorWeights(_StrictWrite):
    sectors: list[ExternalEtfSectorWeight] = Field(min_length=1, max_length=20)


class ExternalEpsThresholds(_StrictWrite):
    super_quarter_yoy_pct: Optional[float] = Field(default=None, gt=0, le=200)
    acceleration_margin_pp: Optional[float] = Field(default=None, gt=0, le=200)
    outlier_multiplier: Optional[float] = Field(default=None, gt=0, le=20)


class ExternalOnboardingStep(_StrictWrite):
    step: str = Field(min_length=1, max_length=100)
