import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from models.user import User
from services.stock_service import get_company_profile, get_fundamentals, get_stock_news

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stock", tags=["stock"])


@router.get("/{ticker}/profile")
async def profile(ticker: str, user: User = Depends(get_current_user)):
    try:
        return await asyncio.to_thread(get_company_profile, ticker.upper())
    except Exception as e:
        logger.warning(f"Stock profile failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail="Profil konnte nicht geladen werden")


@router.get("/{ticker}/fundamentals")
async def fundamentals(ticker: str, user: User = Depends(get_current_user)):
    try:
        return {"data": await asyncio.to_thread(get_fundamentals, ticker.upper())}
    except Exception as e:
        logger.warning(f"Stock fundamentals failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail="Fundamentaldaten konnten nicht geladen werden")


@router.get("/{ticker}/key-metrics")
async def key_metrics(ticker: str, user: User = Depends(get_current_user)):
    """Key fundamental metrics from yfinance (no API key needed)."""
    from services.fundamental_service import get_key_metrics
    try:
        return await asyncio.to_thread(get_key_metrics, ticker.upper())
    except Exception as e:
        logger.warning(f"Key metrics failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail="Kennzahlen konnten nicht geladen werden")


@router.get("/{ticker}/news")
async def news(ticker: str, user: User = Depends(get_current_user)):
    try:
        articles = await asyncio.to_thread(get_stock_news, ticker.upper())
        return {"articles": articles if articles is not None else []}
    except Exception as e:
        logger.warning(f"Stock news failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail="News konnten nicht geladen werden")
