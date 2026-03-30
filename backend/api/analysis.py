import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.position import Position
from models.price_alert import PriceAlert
from models.user import User
from models.watchlist import WatchlistItem
from models.watchlist_tag import WatchlistTag, watchlist_item_tags
from services.encryption_helpers import encrypt_field, decrypt_field
from services.stock_scorer import score_stock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

TAG_PALETTE = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899", "#06B6D4", "#6B7280"]


class WatchlistCreate(BaseModel):
    ticker: str
    name: str
    sector: Optional[str] = None


class WatchlistUpdate(BaseModel):
    notes: Optional[str] = None


class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None


class ResistanceUpdate(BaseModel):
    manual_resistance: Optional[float] = None


@router.get("/mrs-history/{ticker}")
async def get_mrs_history(ticker: str, period: str = "1y", user: User = Depends(get_current_user)):
    """Returns weekly MRS (Modified Relative Strength) time series."""
    import asyncio
    from services.chart_service import get_mrs_history as _get_mrs
    data = await asyncio.to_thread(_get_mrs, ticker.upper(), period)
    return {"ticker": ticker.upper(), "data": data}


@router.get("/breakouts/{ticker}")
async def get_breakouts(ticker: str, period: str = "1y", user: User = Depends(get_current_user)):
    """Returns historical breakout/breakdown events."""
    import asyncio
    from services.chart_service import get_breakout_events
    breakouts = await asyncio.to_thread(get_breakout_events, ticker.upper(), period)
    return {"ticker": ticker.upper(), "breakouts": breakouts}


@router.get("/levels/{ticker}")
async def get_levels(ticker: str, user: User = Depends(get_current_user)):
    """Returns current support and resistance levels."""
    import asyncio
    from services.chart_service import get_support_resistance_levels
    levels = await asyncio.to_thread(get_support_resistance_levels, ticker.upper())
    return levels


@router.get("/reversal/{ticker}")
async def get_reversal(ticker: str, user: User = Depends(get_current_user)):
    """Returns 3-point reversal detection result."""
    import asyncio
    from services.chart_service import get_three_point_reversal
    result = await asyncio.to_thread(get_three_point_reversal, ticker.upper())
    return {"ticker": ticker.upper(), **result}


@router.get("/score/{ticker}")
async def get_score(ticker: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
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

        import asyncio
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
    from services import cache as app_cache
    from models.price_cache import PriceCache

    result = await db.execute(select(WatchlistItem).where(WatchlistItem.is_active == True, WatchlistItem.user_id == user.id).order_by(WatchlistItem.ticker))
    items = result.scalars().all()

    # Preload latest prices from DB for all watchlist tickers (fallback when memory cache expired)
    tickers = [w.ticker for w in items]
    db_prices = {}
    if tickers:
        # Batch query: get the 2 most recent prices per ticker using a window function
        from sqlalchemy import literal_column
        from sqlalchemy.sql import text as sa_text

        # Only load recent prices (last 7 days) — we need at most 2 per ticker (M-7)
        from datetime import date as _date, timedelta as _td
        recent_cutoff = _date.today() - _td(days=7)
        pc_result = await db.execute(
            select(PriceCache)
            .where(PriceCache.ticker.in_(tickers), PriceCache.date >= recent_cutoff)
            .order_by(PriceCache.ticker, PriceCache.date.desc())
        )
        all_pcs = pc_result.scalars().all()

        # Group by ticker, keep max 2 per ticker
        from collections import defaultdict
        ticker_prices = defaultdict(list)
        for pc in all_pcs:
            if len(ticker_prices[pc.ticker]) < 2:
                ticker_prices[pc.ticker].append(pc)

        for ticker, pcs in ticker_prices.items():
            if pcs:
                entry = {"price": float(pcs[0].close), "currency": pcs[0].currency}
                if len(pcs) >= 2 and float(pcs[1].close) > 0:
                    entry["change_pct"] = round((float(pcs[0].close) - float(pcs[1].close)) / float(pcs[1].close) * 100, 2)
                db_prices[ticker] = entry

    # Load all tags for this user's watchlist items
    item_ids = [w.id for w in items]
    tags_by_item = {}
    if item_ids:
        tag_result = await db.execute(
            select(watchlist_item_tags.c.watchlist_item_id, WatchlistTag)
            .join(WatchlistTag, watchlist_item_tags.c.tag_id == WatchlistTag.id)
            .where(watchlist_item_tags.c.watchlist_item_id.in_(item_ids))
        )
        for wl_id, tag in tag_result:
            tags_by_item.setdefault(wl_id, []).append({
                "id": str(tag.id), "name": tag.name, "color": tag.color,
            })

    # Load active alerts per ticker
    alert_result = await db.execute(
        select(PriceAlert.ticker, func.count(PriceAlert.id)).where(
            PriceAlert.user_id == user.id,
            PriceAlert.is_active == True,
        ).group_by(PriceAlert.ticker)
    )
    alerts_by_ticker = {ticker: cnt for ticker, cnt in alert_result}

    watchlist = []
    for w in items:
        item = {
            "id": str(w.id),
            "ticker": w.ticker,
            "name": w.name,
            "sector": w.sector,
            "notes": decrypt_field(w.notes),
            "manual_resistance": float(w.manual_resistance) if w.manual_resistance is not None else None,
            "created_at": w.created_at.isoformat() if w.created_at else None,
            "price": None,
            "currency": None,
            "change_pct": None,
            "tags": tags_by_item.get(w.id, []),
            "active_alerts": alerts_by_ticker.get(w.ticker, 0),
        }
        # Look up cached price (memory cache first, then DB fallback)
        cached = app_cache.get(f"price:{w.ticker}")
        if cached:
            item["price"] = cached.get("price")
            item["currency"] = cached.get("currency", "USD")
            item["change_pct"] = cached.get("change_pct")
        elif w.ticker in db_prices:
            item["price"] = db_prices[w.ticker]["price"]
            item["currency"] = db_prices[w.ticker].get("currency", "USD")
        # Always fill change_pct from DB if still None
        if item["change_pct"] is None and w.ticker in db_prices:
            item["change_pct"] = db_prices[w.ticker].get("change_pct")
        watchlist.append(item)

    # Total active alerts count for header
    total_active_alerts = sum(alerts_by_ticker.values())

    return {"items": watchlist, "active_alerts_count": total_active_alerts}


@router.post("/watchlist", status_code=201)
@limiter.limit("30/minute")
async def add_to_watchlist(request: Request, data: WatchlistCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # Per-user limit: max 200 watchlist items
    count_result = await db.execute(
        select(func.count()).select_from(WatchlistItem).where(
            WatchlistItem.user_id == user.id, WatchlistItem.is_active == True
        )
    )
    if (count_result.scalar() or 0) >= 200:
        raise HTTPException(status_code=400, detail="Watchlist-Limit erreicht (max. 200 Einträge)")

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
    await db.delete(item)
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
        # Auto-assign color from palette
        count_result = await db.execute(
            select(func.count()).select_from(WatchlistTag).where(WatchlistTag.user_id == user.id)
        )
        idx = count_result.scalar() % len(TAG_PALETTE)
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
