"""User settings, SMTP, onboarding, alert preferences, and data export endpoints."""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.user import User
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


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=3650)


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


# --- FMP API Key (Financial Modeling Prep) ---

@router.put("/fmp-api-key")
@limiter.limit("30/minute")
async def save_fmp_api_key(request: Request, data: FredApiKeyUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.save_fmp_api_key(db, user.id, data.api_key)


@router.delete("/fmp-api-key", status_code=204)
@limiter.limit("30/minute")
async def delete_fmp_api_key(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await svc.delete_fmp_api_key(db, user.id)


@router.post("/fmp-api-key/test")
@limiter.limit("5/minute")
async def test_fmp_api_key(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Test the saved FMP API key with an AAPL quote."""
    return await svc.test_fmp_api_key(db, user.id)


# --- Finnhub API Key ---

@router.put("/finnhub-api-key")
@limiter.limit("30/minute")
async def save_finnhub_api_key(request: Request, data: FredApiKeyUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await svc.save_finnhub_api_key(db, user.id, data.api_key)


@router.delete("/finnhub-api-key", status_code=204)
@limiter.limit("30/minute")
async def delete_finnhub_api_key(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await svc.delete_finnhub_api_key(db, user.id)


@router.post("/finnhub-api-key/test")
@limiter.limit("5/minute")
async def test_finnhub_api_key(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Test the saved Finnhub API key with an AAPL quote."""
    return await svc.test_finnhub_api_key(db, user.id)


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


# --- External API Tokens ---

@router.get("/api-tokens")
async def list_api_tokens(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all active external API tokens for the current user."""
    from services.api_token_service import list_tokens
    return await list_tokens(db, user.id)


@router.post("/api-tokens", status_code=201)
@limiter.limit("10/minute")
async def create_api_token(
    request: Request,
    data: ApiTokenCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new external API token. The plaintext is returned ONCE."""
    from services.api_token_service import create_token
    try:
        token, plaintext = await create_token(db, user.id, data.name, data.expires_in_days)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "id": str(token.id),
        "name": token.name,
        "prefix": token.token_prefix,
        "token": plaintext,  # only returned here
        "created_at": token.created_at.isoformat() if token.created_at else None,
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
    }


@router.delete("/api-tokens/{token_id}", status_code=204)
@limiter.limit("30/minute")
async def revoke_api_token(
    request: Request,
    token_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an external API token."""
    from services.api_token_service import revoke_token
    revoked = await revoke_token(db, user.id, token_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Token nicht gefunden")


# --- Export ---

export_router = APIRouter(prefix="/api/export", tags=["export"])


@export_router.get("/portfolio")
async def export_portfolio(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    csv_data = await svc.export_portfolio_csv(db, user.id)
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
    )


@export_router.get("/transactions")
async def export_transactions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    csv_data = await svc.export_transactions_csv(db, user.id)
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )
