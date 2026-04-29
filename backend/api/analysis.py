import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from constants.limits import MAX_WATCHLIST_PER_USER, MAX_WATCHLIST_TAGS_PER_USER
from db import get_db
from models.position import Position
from models.price_alert import PriceAlert
from models.user import User
from models.watchlist import WatchlistItem
from models.watchlist_tag import WatchlistTag, watchlist_item_tags
from services.encryption_helpers import encrypt_field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

TAG_PALETTE = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899", "#06B6D4", "#6B7280"]


class WatchlistCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    sector: Optional[str] = Field(default=None, max_length=100)


class WatchlistUpdate(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=2000)


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    color: Optional[str] = Field(default=None, max_length=7)


class ResistanceUpdate(BaseModel):
    manual_resistance: Optional[float] = Field(default=None, ge=0)


@router.get("/mrs-history/{ticker}")
@limiter.limit("30/minute")
async def get_mrs_history(request: Request, ticker: str, period: str = "1y", user: User = Depends(get_current_user)):
    """Returns weekly MRS (Modified Relative Strength) time series."""
    from services.chart_service import get_mrs_history as _get_mrs
    data = await asyncio.to_thread(_get_mrs, ticker.upper(), period)
    return {"ticker": ticker.upper(), "data": data}


@router.get("/breakouts/{ticker}")
@limiter.limit("30/minute")
async def get_breakouts(request: Request, ticker: str, period: str = "1y", user: User = Depends(get_current_user)):
    """Returns historical breakout/breakdown events."""
    from services.chart_service import get_breakout_events
    breakouts = await asyncio.to_thread(get_breakout_events, ticker.upper(), period)
    return {"ticker": ticker.upper(), "breakouts": breakouts}


@router.get("/levels/{ticker}")
@limiter.limit("30/minute")
async def get_levels(request: Request, ticker: str, user: User = Depends(get_current_user)):
    """Returns current support and resistance levels."""
    from services.chart_service import get_support_resistance_levels
    levels = await asyncio.to_thread(get_support_resistance_levels, ticker.upper())
    return levels


@router.get("/reversal/{ticker}")
@limiter.limit("30/minute")
async def get_reversal(request: Request, ticker: str, user: User = Depends(get_current_user)):
    """Returns 3-point reversal detection result."""
    from services.chart_service import get_three_point_reversal
    result = await asyncio.to_thread(get_three_point_reversal, ticker.upper())
    return {"ticker": ticker.upper(), **result}


@router.get("/score/{ticker}")
@limiter.limit("30/minute")
async def get_score(request: Request, ticker: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from services.scoring_service import assess_ticker
    try:
        upper_ticker = ticker.upper()
        # Look up manual_resistance from positions or watchlist
        manual_resistance = None
        sector = None
        pos_result = await db.execute(
            select(Position.manual_resistance, Position.sector).where(
                (Position.ticker == upper_ticker) | (Position.yfinance_ticker == upper_ticker),
                Position.is_active == True,
                Position.user_id == user.id,
            ).limit(1)
        )
        row = pos_result.first()
        if row:
            if row[0] is not None:
                manual_resistance = float(row[0])
            sector = row[1]
        else:
            wl_result = await db.execute(
                select(WatchlistItem.manual_resistance, WatchlistItem.sector).where(
                    WatchlistItem.ticker == upper_ticker,
                    WatchlistItem.is_active == True,
                    WatchlistItem.user_id == user.id,
                ).limit(1)
            )
            row = wl_result.first()
            if row:
                if row[0] is not None:
                    manual_resistance = float(row[0])
                sector = row[1]

        result = await asyncio.to_thread(assess_ticker, upper_ticker, sector=sector, manual_resistance=manual_resistance)
        if result.get("max_score", 0) == 0 and result.get("price") is None:
            raise HTTPException(status_code=404, detail="Ticker nicht gefunden")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Score calculation failed for {ticker}: {e}")
        raise HTTPException(status_code=400, detail="Score-Berechnung fehlgeschlagen")


@router.put("/resistance/{ticker}")
@limiter.limit("30/minute")
async def update_resistance(request: Request, ticker: str, data: ResistanceUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Update manual resistance level for a ticker (positions and/or watchlist)."""
    upper_ticker = ticker.upper()
    updated = False

    # Update in positions
    pos_result = await db.execute(
        select(Position).where(
            (Position.ticker == upper_ticker) | (Position.yfinance_ticker == upper_ticker),
            Position.is_active == True,
            Position.user_id == user.id,
        )
    )
    for pos in pos_result.scalars().all():
        pos.manual_resistance = data.manual_resistance
        updated = True

    # Update in watchlist
    wl_result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.ticker == upper_ticker,
            WatchlistItem.is_active == True,
            WatchlistItem.user_id == user.id,
        )
    )
    for item in wl_result.scalars().all():
        item.manual_resistance = data.manual_resistance
        updated = True

    if updated:
        await db.commit()

    # Clear scorer cache so next request picks up new resistance
    from services import cache
    cache.delete(f"scorer_data:{upper_ticker}")

    return {"ticker": upper_ticker, "manual_resistance": data.manual_resistance, "updated": updated}


@router.get("/watchlist")
async def get_watchlist(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from services.watchlist_service import get_watchlist_data
    return await get_watchlist_data(db, user.id)


@router.post("/watchlist", status_code=201)
@limiter.limit("30/minute")
async def add_to_watchlist(request: Request, data: WatchlistCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # Per-user limit: max 200 watchlist items
    count_result = await db.execute(
        select(func.count()).select_from(WatchlistItem).where(
            WatchlistItem.user_id == user.id, WatchlistItem.is_active == True
        )
    )
    if (count_result.scalar() or 0) >= MAX_WATCHLIST_PER_USER:
        raise HTTPException(status_code=400, detail=f"Watchlist-Limit erreicht (max. {MAX_WATCHLIST_PER_USER} Einträge)")

    item = WatchlistItem(**data.model_dump(), user_id=user.id)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {"id": str(item.id), "ticker": item.ticker, "name": item.name, "sector": item.sector}


@router.patch("/watchlist/{item_id}")
@limiter.limit("30/minute")
async def update_watchlist_item(request: Request, item_id: uuid.UUID, data: WatchlistUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = await db.get(WatchlistItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Watchlist-Eintrag nicht gefunden")
    if data.notes is not None:
        item.notes = encrypt_field(data.notes) if data.notes else None
    await db.commit()
    return {"id": str(item.id), "notes": item.notes}


@router.delete("/watchlist/{item_id}", status_code=204)
@limiter.limit("30/minute")
async def remove_from_watchlist(request: Request, item_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = await db.get(WatchlistItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist-Eintrag nicht gefunden")
    if item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Watchlist-Eintrag nicht gefunden")

    ticker = item.ticker
    await db.delete(item)

    # Cascade: drop price alerts for this ticker since they're typically set up
    # via the watchlist's bell popover and become invisible orphans otherwise.
    alerts = await db.execute(
        select(PriceAlert).where(
            PriceAlert.user_id == user.id,
            PriceAlert.ticker == ticker,
        )
    )
    for alert in alerts.scalars().all():
        await db.delete(alert)

    await db.commit()


# --- Tags ---

@router.get("/tags")
async def list_tags(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(
        select(WatchlistTag).where(WatchlistTag.user_id == user.id).order_by(WatchlistTag.name)
    )
    return [{"id": str(t.id), "name": t.name, "color": t.color} for t in result.scalars().all()]


@router.post("/watchlist/{item_id}/tags")
@limiter.limit("30/minute")
async def add_tag_to_item(request: Request, item_id: uuid.UUID, data: TagCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = await db.get(WatchlistItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Watchlist-Eintrag nicht gefunden")

    # Check max 5 tags
    count_result = await db.execute(
        select(func.count()).select_from(watchlist_item_tags).where(
            watchlist_item_tags.c.watchlist_item_id == item_id
        )
    )
    if count_result.scalar() >= 5:
        raise HTTPException(status_code=400, detail="Max. 5 Tags pro Eintrag")

    # Find or create tag
    tag_name = data.name.strip()[:30]
    result = await db.execute(
        select(WatchlistTag).where(
            WatchlistTag.user_id == user.id,
            func.lower(WatchlistTag.name) == tag_name.lower(),
        )
    )
    tag = result.scalars().first()
    if not tag:
        # Per-user tag limit
        count_result = await db.execute(
            select(func.count()).select_from(WatchlistTag).where(WatchlistTag.user_id == user.id)
        )
        tag_count = count_result.scalar() or 0
        if tag_count >= MAX_WATCHLIST_TAGS_PER_USER:
            raise HTTPException(400, f"Tag-Limit erreicht (max. {MAX_WATCHLIST_TAGS_PER_USER} Tags)")
        # Auto-assign color from palette
        idx = tag_count % len(TAG_PALETTE)
        tag = WatchlistTag(user_id=user.id, name=tag_name, color=data.color or TAG_PALETTE[idx])
        db.add(tag)
        await db.flush()

    # Check if already linked
    existing = await db.execute(
        select(watchlist_item_tags).where(
            watchlist_item_tags.c.watchlist_item_id == item_id,
            watchlist_item_tags.c.tag_id == tag.id,
        )
    )
    if existing.first():
        return {"id": str(tag.id), "name": tag.name, "color": tag.color}

    await db.execute(watchlist_item_tags.insert().values(watchlist_item_id=item_id, tag_id=tag.id))
    await db.commit()
    return {"id": str(tag.id), "name": tag.name, "color": tag.color}


@router.delete("/watchlist/{item_id}/tags/{tag_id}", status_code=204)
@limiter.limit("30/minute")
async def remove_tag_from_item(request: Request, item_id: uuid.UUID, tag_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = await db.get(WatchlistItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Watchlist-Eintrag nicht gefunden")
    await db.execute(
        watchlist_item_tags.delete().where(
            watchlist_item_tags.c.watchlist_item_id == item_id,
            watchlist_item_tags.c.tag_id == tag_id,
        )
    )
    await db.commit()
