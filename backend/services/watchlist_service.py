import logging
import uuid
from collections import defaultdict
from datetime import date as _date, timedelta as _td

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.price_alert import PriceAlert
from models.price_cache import PriceCache
from models.watchlist import WatchlistItem
from models.watchlist_tag import WatchlistTag, watchlist_item_tags
from services import cache as app_cache
from services.encryption_helpers import decrypt_field

logger = logging.getLogger(__name__)


async def get_watchlist_data(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Load watchlist items with prices, tags, and alert counts for a user."""
    result = await db.execute(
        select(WatchlistItem)
        .where(WatchlistItem.is_active == True, WatchlistItem.user_id == user_id)
        .order_by(WatchlistItem.ticker)
    )
    items = result.scalars().all()

    # Preload latest prices from DB for all watchlist tickers (fallback when memory cache expired)
    tickers = [w.ticker for w in items]
    db_prices: dict[str, dict] = {}
    if tickers:
        # Only load recent prices (last 7 days) — we need at most 2 per ticker (M-7)
        recent_cutoff = _date.today() - _td(days=7)
        pc_result = await db.execute(
            select(PriceCache)
            .where(PriceCache.ticker.in_(tickers), PriceCache.date >= recent_cutoff)
            .order_by(PriceCache.ticker, PriceCache.date.desc())
        )
        all_pcs = pc_result.scalars().all()

        # Group by ticker, keep max 2 per ticker
        ticker_prices: dict[str, list] = defaultdict(list)
        for pc in all_pcs:
            if len(ticker_prices[pc.ticker]) < 2:
                ticker_prices[pc.ticker].append(pc)

        for ticker, pcs in ticker_prices.items():
            if pcs:
                entry: dict = {"price": float(pcs[0].close), "currency": pcs[0].currency}
                if len(pcs) >= 2 and float(pcs[1].close) > 0:
                    entry["change_pct"] = round(
                        (float(pcs[0].close) - float(pcs[1].close)) / float(pcs[1].close) * 100, 2
                    )
                db_prices[ticker] = entry

    # Load all tags for this user's watchlist items
    item_ids = [w.id for w in items]
    tags_by_item: dict[uuid.UUID, list[dict]] = {}
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
            PriceAlert.user_id == user_id,
            PriceAlert.is_active == True,
        ).group_by(PriceAlert.ticker)
    )
    alerts_by_ticker: dict[str, int] = {ticker: cnt for ticker, cnt in alert_result}

    # Phase B: Bulk-Lookup für Core-Overlap (max ETF-Gewicht pro Ticker).
    # Eine SQL-Query mit IN-Clause statt N+1.
    overlap_max_weights: dict[str, float] = {}
    if tickers:
        try:
            from services.concentration_service import get_overlap_max_weight_for_tickers
            overlap_max_weights = await get_overlap_max_weight_for_tickers(
                db, [t.upper() for t in tickers], user_id,
            )
        except Exception as e:
            logger.debug(f"Core-Overlap bulk lookup failed: {e}")

    watchlist: list[dict] = []
    for w in items:
        item: dict = {
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
            "etf_overlap_max_weight_pct": overlap_max_weights.get(w.ticker.upper()),
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
    total_active_alerts: int = sum(alerts_by_ticker.values())

    return {"items": watchlist, "active_alerts_count": total_active_alerts}
