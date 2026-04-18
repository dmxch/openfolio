import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.position import Position
from models.price_alert import PriceAlert
from models.user import User
from services.correlation_service import compute_correlation_matrix
from services.earnings_service import get_upcoming_earnings_for_portfolio
from services.portfolio_service import get_portfolio_summary
from services.encryption_helpers import decrypt_field, decrypt_and_mask_iban
from api.schemas import PortfolioSummaryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

from services import cache as app_cache
_SUMMARY_TTL = 60  # seconds — matches frontend polling interval


def invalidate_portfolio_cache(user_id: str) -> None:
    """Invalidate the cached portfolio summary for a user. Call after any write that changes portfolio data."""
    app_cache.delete(f"portfolio_summary:{user_id}")


@router.get("/summary", response_model=PortfolioSummaryResponse)
@limiter.limit("60/minute")
async def portfolio_summary(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cache_key = f"portfolio_summary:{user.id}"
    cached = app_cache.get(cache_key)
    if cached:
        return cached
    summary = await get_portfolio_summary(db, user.id)
    # Enrich positions with bank_name/iban, notes, 24h change, active alert count
    if summary.get("positions"):
        pos_ids = [p["id"] for p in summary["positions"]]
        result = await db.execute(
            select(Position.id, Position.bank_name, Position.iban, Position.notes,
                   Position.coingecko_id, Position.yfinance_ticker, Position.ticker)
            .where(Position.id.in_(pos_ids))
        )
        extra = {str(r.id): r for r in result}
        alert_result = await db.execute(
            select(PriceAlert.ticker, func.count())
            .where(PriceAlert.user_id == user.id, PriceAlert.is_active == True)
            .group_by(PriceAlert.ticker)
        )
        alerts_by_ticker = {row[0]: row[1] for row in alert_result.all()}
        for p in summary["positions"]:
            e = extra.get(p["id"])
            if not e:
                continue
            p["bank_name"] = decrypt_field(e.bank_name)
            p["iban"] = decrypt_and_mask_iban(e.iban)
            p["notes"] = decrypt_field(e.notes)
            p["active_alerts"] = alerts_by_ticker.get(p["ticker"], 0)
            # 24h change from cached price data
            if e.coingecko_id:
                crypto_data = app_cache.get(f"crypto:{e.coingecko_id}")
                p["change_pct_24h"] = crypto_data.get("change_pct") if crypto_data else None
            else:
                yf_ticker = e.yfinance_ticker or e.ticker
                price_data = app_cache.get(f"price:{yf_ticker}")
                p["change_pct_24h"] = price_data.get("change_pct") if price_data else None
    app_cache.set(cache_key, summary, ttl=_SUMMARY_TTL)
    return summary


@router.get("/correlation-matrix")
@limiter.limit("60/minute")
async def correlation_matrix(
    request: Request,
    period: str = Query("90d", regex="^(30d|90d|180d|1y)$"),
    include_cash: bool = Query(False),
    include_pension: bool = Query(False),
    include_commodity: bool = Query(True),
    include_crypto: bool = Query(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Paarweise Korrelations-Matrix + HHI-Konzentration fuer das Liquid-Portfolio.

    Cache-Key wird mit dem externen v1-Endpoint geteilt, damit Cron-Briefe und
    User-Logins sich den gleichen Service-Cache teilen.
    """
    cache_key = (
        f"external:correlation:{user.id}:{period}"
        f":c{int(include_cash)}p{int(include_pension)}"
        f"m{int(include_commodity)}k{int(include_crypto)}:v1"
    )
    cached = app_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = await compute_correlation_matrix(
            db,
            user.id,
            period=period,
            include_cash=include_cash,
            include_pension=include_pension,
            include_commodity=include_commodity,
            include_crypto=include_crypto,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("correlation-matrix failed")
        raise HTTPException(status_code=503, detail="correlation_matrix_unavailable")
    app_cache.set(cache_key, data, ttl=86400)  # 24h, gleicher Key wie External
    return data


@router.get("/upcoming-earnings")
@limiter.limit("60/minute")
async def upcoming_earnings(
    request: Request,
    days: int = Query(7, ge=1, le=60),
    include_etfs: bool = Query(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Liefert naechste Earnings-Termine fuer die Portfolio-Positionen."""
    cache_key = f"external:upcoming_earnings:{user.id}:{days}:{int(include_etfs)}:v1"
    cached = app_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = await get_upcoming_earnings_for_portfolio(
            db,
            user.id,
            days=days,
            include_etfs=include_etfs,
        )
    except Exception:
        logger.exception("upcoming-earnings failed")
        raise HTTPException(status_code=503, detail="upcoming_earnings_unavailable")
    app_cache.set(cache_key, data, ttl=43200)  # 12h
    return data
