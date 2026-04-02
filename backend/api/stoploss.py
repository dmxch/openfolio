import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.user import User
from api.portfolio import invalidate_portfolio_cache
from services.stoploss_service import (
    get_positions_without_stoploss,
    get_stop_loss_status,
    update_stop_loss as service_update_stop_loss,
    batch_update_stop_loss as service_batch_update_stop_loss,
)

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
    return await get_positions_without_stoploss(db, str(user.id))


@router.get("/stop-loss-status")
async def stop_loss_status(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Return stop-loss status for all active tradable positions."""
    return await get_stop_loss_status(db, str(user.id))


@router.patch("/positions/{position_id}/stop-loss")
@limiter.limit("30/minute")
async def update_stop_loss(request: Request, position_id: str, data: StopLossUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Update stop-loss for a position by ID."""
    result = await service_update_stop_loss(
        db,
        str(user.id),
        position_id,
        data.stop_loss_price,
        data.confirmed_at_broker,
        data.method,
    )
    invalidate_portfolio_cache(str(user.id))
    return result


@router.post("/stop-loss/batch")
@limiter.limit("30/minute")
async def batch_stop_loss(request: Request, data: StopLossBatchRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Set stop-loss for multiple positions at once (post-import wizard)."""
    items = [item.model_dump() for item in data.items]
    result = await service_batch_update_stop_loss(db, str(user.id), items)
    if result["updated"]:
        invalidate_portfolio_cache(str(user.id))
    return result
