"""User settings, SMTP, onboarding, alert preferences, and data export endpoints."""

import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.user import User
from models.position import Position
from models.transaction import Transaction
from services import settings_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# --- Pydantic Models ---

class SettingsUpdate(BaseModel):
    base_currency: Optional[str] = None
    broker: Optional[str] = None
    default_stop_loss_method: Optional[str] = None
    stop_loss_review_distance_pct: Optional[float] = None
    stop_loss_review_max_days: Optional[int] = None
    number_format: Optional[str] = None
    date_format: Optional[str] = None
    # Alert toggles
    alert_stop_missing: Optional[bool] = None
    alert_stop_unconfirmed: Optional[bool] = None
    alert_stop_proximity: Optional[bool] = None
    alert_stop_review: Optional[bool] = None
    alert_ma_critical: Optional[bool] = None
    alert_ma_warning: Optional[bool] = None
    alert_position_limit: Optional[bool] = None
    alert_sector_limit: Optional[bool] = None
    alert_loss: Optional[bool] = None
    alert_market_climate: Optional[bool] = None
    alert_vix: Optional[bool] = None
    alert_earnings: Optional[bool] = None
    alert_allocation: Optional[bool] = None
    alert_position_type_missing: Optional[bool] = None
    # Alert thresholds
    alert_satellite_loss_pct: Optional[float] = None
    alert_core_loss_pct: Optional[float] = None
    alert_stop_proximity_pct: Optional[float] = None


class FredApiKeyUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=100)


class AlertPrefUpdate(BaseModel):
    category: str = Field(min_length=1, max_length=50)
    is_enabled: Optional[bool] = None
    notify_in_app: Optional[bool] = None
    notify_email: Optional[bool] = None


class SmtpConfigCreate(BaseModel):
    provider: Optional[str] = Field(default=None, max_length=50)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=500)
    from_email: Optional[str] = Field(default=None, max_length=255)
    use_tls: bool = True


class SmtpConfigUpdate(BaseModel):
    provider: Optional[str] = Field(default=None, max_length=50)
    host: Optional[str] = Field(default=None, max_length=255)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, max_length=500)
    from_email: Optional[str] = Field(default=None, max_length=255)
    use_tls: Optional[bool] = None


class StepCompleteRequest(BaseModel):
    step: str


# --- Settings CRUD ---

@router.get("")
async def get_settings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.get_settings(db, user.id)


@router.patch("")
@limiter.limit("30/minute")
async def update_settings(request: Request, data: SettingsUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.update_settings(db, user.id, data.model_dump(exclude_unset=True))


# --- FRED API Key ---

@router.put("/fred-api-key")
@limiter.limit("30/minute")
async def save_fred_api_key(request: Request, data: FredApiKeyUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.save_fred_api_key(db, user.id, data.api_key)


@router.delete("/fred-api-key", status_code=204)
@limiter.limit("30/minute")
async def delete_fred_api_key(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await svc.delete_fred_api_key(db, user.id)


@router.post("/fred-api-key/test")
@limiter.limit("5/minute")
async def test_fred_api_key(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Test the saved FRED API key by fetching UNRATE."""
    return await svc.test_fred_api_key(db, user.id)


# --- Alert Preferences ---

@router.get("/alert-preferences")
async def get_alert_preferences(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.get_alert_preferences(db, user.id)


@router.put("/alert-preferences")
@limiter.limit("30/minute")
async def update_alert_preference(request: Request, data: AlertPrefUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.update_alert_preference(db, user.id, data.category, data.is_enabled, data.notify_in_app, data.notify_email)


# --- SMTP Config ---

@router.get("/smtp")
async def get_smtp_config(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.get_smtp_config(db, user.id)


@router.put("/smtp")
@limiter.limit("30/minute")
async def save_smtp_config(request: Request, data: SmtpConfigCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.save_smtp_config(db, user.id, data.provider, data.host, data.port, data.username, data.password, data.from_email, data.use_tls)


@router.delete("/smtp", status_code=204)
@limiter.limit("30/minute")
async def delete_smtp_config(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await svc.delete_smtp_config(db, user.id)


@router.post("/smtp/test")
@limiter.limit("5/minute")
async def test_smtp(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Send a test email using the user's SMTP config."""
    return await svc.test_smtp_config(db, user)


# --- Onboarding ---

@router.get("/onboarding/status")
async def get_onboarding_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.get_onboarding_status(db, user)


@router.post("/onboarding/tour-complete")
@limiter.limit("30/minute")
async def mark_tour_complete(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.mark_tour_complete(db, user.id)


@router.post("/onboarding/hide-checklist")
@limiter.limit("30/minute")
async def hide_checklist(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.hide_checklist(db, user.id)


@router.post("/onboarding/step-complete")
@limiter.limit("30/minute")
async def mark_step_complete(request: Request, data: StepCompleteRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.mark_step_complete(db, user.id, data.step)


# --- Export ---

_CSV_INJECTION_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_cell(value) -> str:
    """Prevent CSV formula injection by prefixing dangerous characters."""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_CHARS:
        return "'" + value
    return value


export_router = APIRouter(prefix="/api/export", tags=["export"])


@export_router.get("/portfolio")
async def export_portfolio(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Position).where(Position.user_id == user.id, Position.is_active == True))
    positions = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Ticker", "Name", "Typ", "Sektor", "Waehrung", "Stueck", "Einstandswert CHF", "Aktueller Kurs", "Stop-Loss"])

    for p in positions:
        writer.writerow([
            _sanitize_csv_cell(p.ticker), _sanitize_csv_cell(p.name),
            p.type.value, _sanitize_csv_cell(p.sector or ""), p.currency,
            float(p.shares), float(p.cost_basis_chf),
            float(p.current_price) if p.current_price else "",
            float(p.stop_loss_price) if p.stop_loss_price else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
    )


@export_router.get("/transactions")
async def export_transactions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    txn_result = await db.execute(
        select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date.desc())
    )
    transactions = txn_result.scalars().all()

    if not transactions:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Datum", "Typ", "Ticker", "Stueck", "Kurs", "Waehrung", "FX", "Gebuehren", "Steuern", "Total CHF"])
        output.seek(0)
        return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=transactions.csv"})

    pos_ids = list({t.position_id for t in transactions})
    pos_map_result = await db.execute(select(Position.id, Position.ticker).where(Position.id.in_(pos_ids)))
    ticker_map = {row[0]: row[1] for row in pos_map_result}

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Datum", "Typ", "Ticker", "Stueck", "Kurs", "Waehrung", "FX", "Gebuehren", "Steuern", "Total CHF"])

    for t in transactions:
        writer.writerow([
            t.date.isoformat(), t.type.value, _sanitize_csv_cell(ticker_map.get(t.position_id, "")),
            float(t.shares), float(t.price_per_share), t.currency,
            float(t.fx_rate_to_chf), float(t.fees_chf), float(t.taxes_chf), float(t.total_chf),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )
