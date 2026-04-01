import uuid
from datetime import timedelta

from dateutils import utcnow
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.price_alert import PriceAlert
from models.user import User
from sqlalchemy import func

router = APIRouter(prefix="/api/price-alerts", tags=["price-alerts"])


class AlertCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=60)
    alert_type: str = Field(min_length=1, max_length=30)
    target_value: float
    currency: Optional[str] = Field(default=None, max_length=3)
    notify_in_app: bool = True
    notify_email: bool = False
    note: Optional[str] = Field(default=None, max_length=500)


class AlertUpdate(BaseModel):
    target_value: Optional[float] = None
    note: Optional[str] = Field(default=None, max_length=500)
    notify_in_app: Optional[bool] = None
    notify_email: Optional[bool] = None


@router.post("")
@limiter.limit("30/minute")
async def create_alert(request: Request, data: AlertCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if data.alert_type not in ("price_above", "price_below", "pct_change_day"):
        raise HTTPException(status_code=400, detail="Ungültiger Alarm-Typ")

    # Per-user limit: max 100 active alerts
    count_result = await db.execute(
        select(func.count()).select_from(PriceAlert).where(
            PriceAlert.user_id == user.id, PriceAlert.is_active == True
        )
    )
    if (count_result.scalar() or 0) >= 100:
        raise HTTPException(status_code=400, detail="Alarm-Limit erreicht (max. 100 aktive Alarme)")

    alert = PriceAlert(
        user_id=user.id,
        ticker=data.ticker.upper(),
        alert_type=data.alert_type,
        target_value=data.target_value,
        currency=data.currency,
        notify_in_app=data.notify_in_app,
        notify_email=data.notify_email,
        note=data.note,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return _alert_to_dict(alert)


@router.get("")
async def list_alerts(
    active: Optional[bool] = None,
    triggered: Optional[bool] = None,
    ticker: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(PriceAlert).where(PriceAlert.user_id == user.id)
    if active is not None:
        query = query.where(PriceAlert.is_active == active)
    if triggered is not None:
        query = query.where(PriceAlert.is_triggered == triggered)
    if ticker:
        query = query.where(PriceAlert.ticker == ticker.upper())
    query = query.order_by(PriceAlert.created_at.desc())

    result = await db.execute(query)
    return [_alert_to_dict(a) for a in result.scalars().all()]


@router.get("/triggered")
async def triggered_alerts(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Recently triggered alerts (last 7 days)."""
    cutoff = utcnow() - timedelta(days=7)
    result = await db.execute(
        select(PriceAlert).where(
            PriceAlert.user_id == user.id,
            PriceAlert.is_triggered == True,
            PriceAlert.triggered_at >= cutoff,
        ).order_by(PriceAlert.triggered_at.desc())
    )
    return [_alert_to_dict(a) for a in result.scalars().all()]


@router.patch("/{alert_id}")
@limiter.limit("30/minute")
async def update_alert(request: Request, alert_id: uuid.UUID, data: AlertUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    alert = await db.get(PriceAlert, alert_id)
    if not alert or alert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alarm nicht gefunden")
    if alert.is_triggered:
        raise HTTPException(status_code=400, detail="Alarm wurde bereits ausgelöst")

    if data.target_value is not None:
        alert.target_value = data.target_value
    if data.note is not None:
        alert.note = data.note
    if data.notify_in_app is not None:
        alert.notify_in_app = data.notify_in_app
    if data.notify_email is not None:
        alert.notify_email = data.notify_email

    await db.commit()
    await db.refresh(alert)
    return _alert_to_dict(alert)


@router.delete("/{alert_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_alert(request: Request, alert_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    alert = await db.get(PriceAlert, alert_id)
    if not alert or alert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alarm nicht gefunden")
    await db.delete(alert)
    await db.commit()


def _alert_to_dict(a: PriceAlert) -> dict:
    return {
        "id": str(a.id),
        "ticker": a.ticker,
        "alert_type": a.alert_type,
        "target_value": float(a.target_value),
        "currency": a.currency,
        "is_active": a.is_active,
        "is_triggered": a.is_triggered,
        "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
        "trigger_price": float(a.trigger_price) if a.trigger_price else None,
        "notify_in_app": a.notify_in_app,
        "notify_email": a.notify_email,
        "note": a.note,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
    }
