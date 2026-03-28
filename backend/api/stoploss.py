import asyncio
import datetime
import logging
from typing import Optional

from dateutils import utcnow

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.position import Position
from models.user import User
from models.transaction import Transaction
from api.portfolio import invalidate_portfolio_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["stoploss"])


class StopLossUpdate(BaseModel):
    stop_loss_price: Optional[float] = Field(default=None, ge=0)
    confirmed_at_broker: bool = False
    method: Optional[str] = None


class StopLossBatchItem(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    stop_loss_price: float = Field(gt=0)
    confirmed_at_broker: bool = False
    method: Optional[str] = None


class StopLossBatchRequest(BaseModel):
    items: list[StopLossBatchItem]


@router.get("/positions-without-stoploss")
async def positions_without_stoploss(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Return active positions (shares > 0) that have no stop-loss set."""
    result = await db.execute(
        select(Position).where(
            Position.is_active == True,
            Position.user_id == user.id,
            Position.shares > 0,
            Position.stop_loss_price.is_(None),
            Position.type.notin_(["cash", "pension", "real_estate", "crypto", "commodity"]),
        )
    )
    positions = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "ticker": p.ticker,
            "name": p.name,
            "shares": float(p.shares),
            "current_price": float(p.current_price) if p.current_price else None,
            "currency": p.currency,
            "position_type": p.position_type,
        }
        for p in positions
    ]


@router.get("/stop-loss-status")
async def stop_loss_status(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Return stop-loss status for all active tradable positions."""
    from services.utils import get_fx_rates_batch

    result = await db.execute(
        select(Position).where(
            Position.is_active == True,
            Position.user_id == user.id,
            Position.shares > 0,
            Position.type.notin_(["cash", "pension", "real_estate", "crypto", "commodity"]),
        )
    )
    positions = result.scalars().all()
    fx_rates = await asyncio.to_thread(get_fx_rates_batch)
    items = []

    for pos in positions:
        current_price = float(pos.current_price) if pos.current_price else None
        sl_price = float(pos.stop_loss_price) if pos.stop_loss_price is not None else None

        distance_pct = None
        distance_chf = None
        needs_review = False

        is_core = pos.position_type == "core"

        if current_price and sl_price and sl_price > 0:
            distance_pct = round((current_price - sl_price) / sl_price * 100, 2)
            fx = fx_rates.get(pos.currency, 1.0) if pos.currency != "CHF" else 1.0
            distance_chf = round((current_price - sl_price) * float(pos.shares) * (fx or 1.0), 2)

            # Core: warn if distance > 30%, Satellite: warn if distance > 15%
            distance_threshold = 30 if is_core else 15
            if distance_pct > distance_threshold:
                needs_review = True

        days_since_update = None
        if pos.stop_loss_updated_at:
            days_since_update = (datetime.datetime.now() - pos.stop_loss_updated_at).days
            # Core: quarterly (90 days), Satellite: biweekly (14 days)
            days_threshold = 90 if is_core else 14
            if days_since_update > days_threshold:
                needs_review = True

        items.append({
            "ticker": pos.ticker,
            "current_price": current_price,
            "stop_loss_price": sl_price,
            "currency": pos.currency,
            "distance_pct": distance_pct,
            "distance_chf": distance_chf,
            "position_type": pos.position_type,
            "confirmed_at_broker": pos.stop_loss_confirmed_at_broker,
            "days_since_update": days_since_update,
            "method": pos.stop_loss_method,
            "needs_review": needs_review,
        })

    return items


@router.patch("/positions/{position_id}/stop-loss")
@limiter.limit("30/minute")
async def update_stop_loss(request: Request, position_id: str, data: StopLossUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Update stop-loss for a position by ID."""
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.is_active == True, Position.user_id == user.id)
    )
    pos = result.scalars().first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")

    # Allow removing stop-loss (price=0 or None) for Core positions
    is_removing = not data.stop_loss_price or data.stop_loss_price == 0

    if is_removing:
        if pos.position_type != "core":
            raise HTTPException(status_code=422, detail="Stop-Loss ist Pflicht für Satellite-Positionen")
        pos.stop_loss_price = None
        pos.stop_loss_confirmed_at_broker = False
        pos.stop_loss_method = None
        pos.stop_loss_updated_at = utcnow()
        await db.commit()
        await db.refresh(pos)
        invalidate_portfolio_cache(str(user.id))
        return {"ok": True, "ticker": pos.ticker, "stop_loss_price": None}

    current_price = float(pos.current_price) if pos.current_price else None
    if current_price and data.stop_loss_price >= current_price:
        raise HTTPException(status_code=422, detail="Stop-Loss muss unter dem aktuellen Kurs liegen")

    old_sl = float(pos.stop_loss_price) if pos.stop_loss_price is not None else None

    # Trailing stop: warn if lowered without a recent buy, but allow override
    warning = None
    if old_sl is not None and data.stop_loss_price < old_sl:
        has_recent_buy = False
        if pos.stop_loss_updated_at:
            txn_result = await db.execute(
                select(Transaction).where(
                    Transaction.position_id == pos.id,
                    Transaction.type == "buy",
                    Transaction.date > pos.stop_loss_updated_at.date(),
                )
            )
            if txn_result.scalars().first():
                has_recent_buy = True

        if not has_recent_buy:
            warning = "Ein Trailing Stop darf nur nach oben verschoben werden. Nach einem Nachkauf darf der Stop tiefer gesetzt werden."

    pos.stop_loss_price = data.stop_loss_price
    pos.stop_loss_confirmed_at_broker = data.confirmed_at_broker
    pos.stop_loss_method = data.method
    pos.stop_loss_updated_at = utcnow()

    await db.commit()
    await db.refresh(pos)
    invalidate_portfolio_cache(str(user.id))
    result = {"ok": True, "ticker": pos.ticker, "stop_loss_price": float(pos.stop_loss_price)}
    if warning:
        result["warning"] = warning
    return result


@router.post("/stop-loss/batch")
@limiter.limit("30/minute")
async def batch_stop_loss(request: Request, data: StopLossBatchRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Set stop-loss for multiple positions at once (post-import wizard)."""
    results = []
    errors = []

    for item in data.items:
        result = await db.execute(
            select(Position).where(Position.ticker == item.ticker, Position.is_active == True, Position.user_id == user.id)
        )
        pos = result.scalars().first()
        if not pos:
            errors.append({"ticker": item.ticker, "error": "Position not found"})
            continue

        current_price = float(pos.current_price) if pos.current_price else None
        if current_price and item.stop_loss_price >= current_price:
            errors.append({"ticker": item.ticker, "error": "Stop-Loss muss unter aktuellem Kurs liegen"})
            continue

        if item.stop_loss_price <= 0:
            errors.append({"ticker": item.ticker, "error": "Stop-Loss muss grösser als 0 sein"})
            continue

        pos.stop_loss_price = item.stop_loss_price
        pos.stop_loss_confirmed_at_broker = item.confirmed_at_broker
        pos.stop_loss_method = item.method
        pos.stop_loss_updated_at = utcnow()
        results.append({"ticker": item.ticker, "stop_loss_price": item.stop_loss_price})

    await db.commit()
    if results:
        invalidate_portfolio_cache(str(user.id))
    return {"updated": results, "errors": errors}
