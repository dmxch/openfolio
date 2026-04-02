import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.position import Position
from models.user import User
from services.stock_service import get_company_profile, get_stock_news

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stock", tags=["stock"])


@router.get("/search")
@limiter.limit("30/minute")
async def search_ticker(
    request: Request,
    q: str = Query(..., min_length=1, max_length=30),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Search for tickers: existing positions first, then yfinance lookup."""
    query = q.strip().upper()
    results: list[dict] = []
    seen: set[str] = set()

    # 1. Search existing positions (ticker or name match)
    from services.auth_service import escape_like
    search_term = f"%{escape_like(query)}%"
    pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user.id,
            Position.ticker.ilike(search_term) | Position.name.ilike(search_term),
        ).limit(10)
    )
    for p in pos_result.scalars():
        results.append({
            "ticker": p.ticker,
            "name": p.name,
            "type": p.type.value,
            "currency": p.currency,
            "position_id": str(p.id),
            "is_existing": True,
        })
        seen.add(p.ticker.upper())

    # 2. yfinance search for new tickers (best-effort)
    if len(results) < 8:
        try:
            def _yf_search(q: str) -> list[dict]:
                import yfinance as yf
                results = []
                try:
                    search = yf.Search(q)
                    for quote in (search.quotes or [])[:8]:
                        symbol = quote.get("symbol", "")
                        if not symbol:
                            continue
                        results.append({
                            "ticker": symbol,
                            "name": quote.get("shortname") or quote.get("longname") or symbol,
                            "type": quote.get("quoteType", "EQUITY").lower(),
                            "exchange": quote.get("exchange", ""),
                        })
                except Exception:
                    logging.getLogger(__name__).debug(f"yfinance search failed for {q}, trying ticker fallback", exc_info=True)
                    # Fallback: try direct ticker lookup
                    try:
                        info = yf.Ticker(q).info or {}
                        if info.get("symbol"):
                            results.append({
                                "ticker": info["symbol"],
                                "name": info.get("shortName") or info.get("longName") or info["symbol"],
                                "type": info.get("quoteType", "EQUITY").lower(),
                                "exchange": info.get("exchange", ""),
                            })
                    except Exception:
                        logging.getLogger(__name__).debug(f"yfinance ticker fallback lookup failed for {q}", exc_info=True)
                return results

            yf_results = await asyncio.to_thread(_yf_search, query)
            for item in yf_results:
                if item["ticker"].upper() not in seen:
                    # Map yfinance quoteType to our asset types
                    qt = item["type"].lower()
                    if qt == "etf":
                        asset_type = "etf"
                    elif qt in ("cryptocurrency", "crypto"):
                        asset_type = "crypto"
                    else:
                        asset_type = "stock"
                    results.append({
                        "ticker": item["ticker"],
                        "name": item["name"],
                        "type": asset_type,
                        "currency": None,  # will be resolved on selection
                        "position_id": None,
                        "is_existing": False,
                    })
                    seen.add(item["ticker"].upper())
        except Exception as e:
            logger.warning(f"yfinance search failed for {query}: {e}", exc_info=True)

    return results


@router.get("/{ticker}/profile")
@limiter.limit("30/minute")
async def profile(request: Request, ticker: str, user: User = Depends(get_current_user)):
    try:
        return await asyncio.to_thread(get_company_profile, ticker.upper())
    except Exception as e:
        logger.warning(f"Stock profile failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail="Profil konnte nicht geladen werden")



@router.get("/{ticker}/news")
@limiter.limit("30/minute")
async def news(request: Request, ticker: str, user: User = Depends(get_current_user)):
    try:
        articles = await get_stock_news(ticker.upper())
        return {"articles": articles if articles is not None else []}
    except Exception as e:
        logger.warning(f"Stock news failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail="News konnten nicht geladen werden")
