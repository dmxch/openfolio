"""Fetch next earnings dates from yfinance."""

import asyncio
import logging
from datetime import datetime
from uuid import UUID

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import Position
from services import cache

logger = logging.getLogger(__name__)


def get_next_earnings_date(ticker: str) -> datetime | None:
    """Fetch next earnings date for a ticker. Returns None if unavailable."""
    cache_key = f"earnings:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached != "none" else None

    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
            # yfinance returns calendar as a dict with 'Earnings Date' key
            # or as a DataFrame depending on the version
            if isinstance(cal, dict):
                dates = cal.get("Earnings Date")
                if dates and len(dates) > 0:
                    ed = dates[0]
                    if isinstance(ed, str):
                        ed = datetime.fromisoformat(ed)
                    elif hasattr(ed, 'to_pydatetime'):
                        ed = ed.to_pydatetime()
                    cache.set(cache_key, ed, ttl=86400)  # cache 24h
                    return ed
            else:
                # DataFrame format
                if "Earnings Date" in cal.columns:
                    vals = cal["Earnings Date"].tolist()
                    if vals:
                        ed = vals[0]
                        if hasattr(ed, 'to_pydatetime'):
                            ed = ed.to_pydatetime()
                        cache.set(cache_key, ed, ttl=86400)
                        return ed
    except Exception as e:
        logger.debug(f"Could not fetch earnings for {ticker}: {e}")

    cache.set(cache_key, "none", ttl=86400)
    return None


async def refresh_all_earnings(db: AsyncSession, user_id: UUID) -> dict:
    """Fetch and store next earnings dates for all active stock/etf positions.

    Args:
        db: Async database session.
        user_id: The current user's ID.

    Returns:
        Dict with count of updated positions and their details.
    """
    result = await db.execute(
        select(Position).where(
            Position.is_active == True,
            Position.user_id == user_id,
            Position.shares > 0,
            Position.type.in_(["stock", "etf"]),
        )
    )
    positions = result.scalars().all()
    updated: list[dict] = []

    # Parallel fetch with semaphore (max 5 concurrent)
    sem = asyncio.Semaphore(5)

    async def _fetch_earnings(pos: Position) -> dict | None:
        async with sem:
            yf_ticker = pos.yfinance_ticker or pos.ticker
            ed = await asyncio.to_thread(get_next_earnings_date, yf_ticker)
            if ed:
                pos.next_earnings_date = ed
                return {"ticker": pos.ticker, "next_earnings_date": ed.isoformat()}
            return None

    results = await asyncio.gather(
        *[_fetch_earnings(p) for p in positions], return_exceptions=True
    )
    for r in results:
        if isinstance(r, dict):
            updated.append(r)
        elif isinstance(r, Exception):
            logger.debug(f"Earnings fetch failed: {r}")

    await db.commit()
    return {"updated": len(updated), "positions": updated}
