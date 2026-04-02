import asyncio
import datetime
import logging
from typing import Optional

from dateutils import utcnow

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import Position
from models.transaction import Transaction
from services.utils import get_fx_rates_batch

logger = logging.getLogger(__name__)


async def get_positions_without_stoploss(db: AsyncSession, user_id: str) -> list[dict]:
    """Return active positions (shares > 0) that have no stop-loss set."""
    result = await db.execute(
        select(Position).where(
            Position.is_active == True,
            Position.user_id == user_id,
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


async def get_stop_loss_status(db: AsyncSession, user_id: str) -> list[dict]:
    """Return stop-loss status for all active tradable positions."""
    result = await db.execute(
        select(Position).where(
            Position.is_active == True,
            Position.user_id == user_id,
            Position.shares > 0,
            Position.type.notin_(["cash", "pension", "real_estate", "crypto", "commodity"]),
        )
    )
    positions = result.scalars().all()
    fx_rates = await asyncio.to_thread(get_fx_rates_batch)
    items: list[dict] = []

    for pos in positions:
        current_price = float(pos.current_price) if pos.current_price else None
        sl_price = float(pos.stop_loss_price) if pos.stop_loss_price is not None else None

        distance_pct: Optional[float] = None
        distance_chf: Optional[float] = None
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

        days_since_update: Optional[int] = None
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


async def update_stop_loss(
    db: AsyncSession,
    user_id: str,
    position_id: str,
    stop_loss_price: Optional[float],
    confirmed_at_broker: bool,
    method: Optional[str],
) -> dict:
    """Update stop-loss for a position. Returns result dict, may include 'warning' key."""
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.is_active == True, Position.user_id == user_id)
    )
    pos = result.scalars().first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")

    # Allow removing stop-loss (price=0 or None) for Core positions
    is_removing = not stop_loss_price or stop_loss_price == 0

    if is_removing:
        if pos.position_type != "core":
            raise HTTPException(status_code=422, detail="Stop-Loss ist Pflicht für Satellite-Positionen")
        pos.stop_loss_price = None
        pos.stop_loss_confirmed_at_broker = False
        pos.stop_loss_method = None
        pos.stop_loss_updated_at = utcnow()
        await db.commit()
        await db.refresh(pos)
        return {"ok": True, "ticker": pos.ticker, "stop_loss_price": None}

    current_price = float(pos.current_price) if pos.current_price else None
    if current_price and stop_loss_price >= current_price:
        raise HTTPException(status_code=422, detail="Stop-Loss muss unter dem aktuellen Kurs liegen")

    old_sl = float(pos.stop_loss_price) if pos.stop_loss_price is not None else None

    # Trailing stop: warn if lowered without a recent buy, but allow override
    warning: Optional[str] = None
    if old_sl is not None and stop_loss_price < old_sl:
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

    pos.stop_loss_price = stop_loss_price
    pos.stop_loss_confirmed_at_broker = confirmed_at_broker
    pos.stop_loss_method = method
    pos.stop_loss_updated_at = utcnow()

    await db.commit()
    await db.refresh(pos)
    result_dict: dict = {"ok": True, "ticker": pos.ticker, "stop_loss_price": float(pos.stop_loss_price)}
    if warning:
        result_dict["warning"] = warning
    return result_dict


async def batch_update_stop_loss(
    db: AsyncSession,
    user_id: str,
    items: list[dict],
) -> dict:
    """Set stop-loss for multiple positions at once. Returns dict with 'updated' and 'errors' lists."""
    results: list[dict] = []
    errors: list[dict] = []

    # Batch-load all positions in a single query
    requested_tickers = [item["ticker"] for item in items]
    pos_result = await db.execute(
        select(Position).where(
            Position.ticker.in_(requested_tickers),
            Position.is_active == True,
            Position.user_id == user_id,
        )
    )
    pos_map = {pos.ticker: pos for pos in pos_result.scalars().all()}

    for item in items:
        pos = pos_map.get(item["ticker"])
        if not pos:
            errors.append({"ticker": item["ticker"], "error": "Position nicht gefunden"})
            continue

        current_price = float(pos.current_price) if pos.current_price else None
        if current_price and item["stop_loss_price"] >= current_price:
            errors.append({"ticker": item["ticker"], "error": "Stop-Loss muss unter aktuellem Kurs liegen"})
            continue

        if item["stop_loss_price"] <= 0:
            errors.append({"ticker": item["ticker"], "error": "Stop-Loss muss grösser als 0 sein"})
            continue

        pos.stop_loss_price = item["stop_loss_price"]
        pos.stop_loss_confirmed_at_broker = item["confirmed_at_broker"]
        pos.stop_loss_method = item["method"]
        pos.stop_loss_updated_at = utcnow()
        results.append({"ticker": item["ticker"], "stop_loss_price": item["stop_loss_price"]})

    await db.commit()
    return {"updated": results, "errors": errors}
