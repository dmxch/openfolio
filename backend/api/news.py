import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.user import User
from services.news_service import get_news_for_user, get_news_for_ticker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
@limiter.limit("30/minute")
async def get_news_feed(
    request: Request,
    scope: str = Query(default="all", pattern="^(portfolio|watchlist|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get aggregated news feed for user's portfolio and/or watchlist tickers."""
    articles = await get_news_for_user(db, user.id, scope=scope, limit=limit)
    return {"articles": articles, "total": len(articles), "scope": scope}


@router.get("/{ticker}")
@limiter.limit("60/minute")
async def get_ticker_news(
    request: Request,
    ticker: str,
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get news for a specific ticker."""
    articles = await get_news_for_ticker(db, ticker.upper(), limit=limit)
    return {"articles": articles, "ticker": ticker.upper()}
