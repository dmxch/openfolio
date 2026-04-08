"""External read-only REST API — versioned, X-API-Key authenticated.

All endpoints under /api/v1/external/* are read-only and authenticated via
the X-API-Key header. They re-use existing service functions but expose a
filtered, stable contract that intentionally excludes sensitive fields
(bank_name, iban) and never touches the HEILIGE Performance-Berechnungen.
"""

import asyncio
import datetime
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from api.external_v1_schemas import (
    filter_pension_position,
    filter_position,
    filter_property,
)
from auth import get_api_user
from db import get_db
from models.position import AssetType, Position
from models.screening import ScreeningResult, ScreeningScan
from models.user import User
from services.portfolio_service import get_portfolio_summary
from services.property_service import get_properties_summary, get_property_detail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/external", tags=["external"])

# Stricter rate-limit than internal API — external consumers should cache.
RATE_LIMIT = "30/minute"


def _filter_summary(summary: dict) -> dict:
    """Strip sensitive fields from a portfolio summary."""
    out = {
        "total_invested_chf": summary.get("total_invested_chf"),
        "total_market_value_chf": summary.get("total_market_value_chf"),
        "total_pnl_chf": summary.get("total_pnl_chf"),
        "total_pnl_pct": summary.get("total_pnl_pct"),
        "total_fees_chf": summary.get("total_fees_chf"),
        "positions": [filter_position(p) for p in summary.get("positions", [])],
        "allocations": summary.get("allocations", {}),
        "fx_rates": summary.get("fx_rates"),
    }
    return out


# --- Health (no auth) ---

@router.get("/health")
async def external_health() -> dict:
    """Liveness probe — no authentication required."""
    return {"status": "ok", "api_version": "v1"}


# --- Portfolio ---

@router.get("/portfolio/summary")
@limiter.limit(RATE_LIMIT)
async def portfolio_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Portfolio summary: totals, allocations, positions (no bank_name/iban)."""
    summary = await get_portfolio_summary(db, user.id)
    return _filter_summary(summary)


@router.get("/positions")
@limiter.limit(RATE_LIMIT)
async def list_positions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """List all positions for the authenticated user (filtered fields)."""
    summary = await get_portfolio_summary(db, user.id)
    return {"positions": [filter_position(p) for p in summary.get("positions", [])]}


@router.get("/positions/{ticker}")
@limiter.limit(RATE_LIMIT)
async def get_position(
    request: Request,
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Get a single position by ticker."""
    summary = await get_portfolio_summary(db, user.id)
    upper = ticker.upper()
    for p in summary.get("positions", []):
        if (p.get("ticker") or "").upper() == upper:
            return filter_position(p)
    raise HTTPException(status_code=404, detail="Position nicht gefunden")


# --- Performance ---

@router.get("/performance/history")
@limiter.limit(RATE_LIMIT)
async def performance_history(
    request: Request,
    period: str = Query(default="1y", pattern="^(1m|3m|ytd|1y|all)$"),
    benchmark: str = Query(default="^GSPC"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Portfolio history snapshots over the requested period."""
    from services.history_service import get_portfolio_history

    today = datetime.date.today()
    if period == "1m":
        start = today - datetime.timedelta(days=30)
    elif period == "3m":
        start = today - datetime.timedelta(days=90)
    elif period == "ytd":
        start = datetime.date(today.year, 1, 1)
    elif period == "1y":
        start = today - datetime.timedelta(days=365)
    else:  # all
        start = datetime.date(2000, 1, 1)

    return await get_portfolio_history(db, start, today, benchmark, user_id=user.id)


@router.get("/performance/monthly-returns")
@limiter.limit(RATE_LIMIT)
async def performance_monthly_returns(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Modified-Dietz monthly returns."""
    from services.performance_history_service import get_monthly_returns
    return await get_monthly_returns(db, user_id=user.id)


@router.get("/performance/total-return")
@limiter.limit(RATE_LIMIT)
async def performance_total_return(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Total return (XIRR-based)."""
    from services.total_return_service import get_total_return
    return await get_total_return(db, user_id=user.id)


@router.get("/performance/realized-gains")
@limiter.limit(RATE_LIMIT)
async def performance_realized_gains(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Realised gains from sell transactions."""
    from services.total_return_service import get_realized_gains
    return await get_realized_gains(db, user_id=user.id)


@router.get("/performance/daily-change")
@limiter.limit(RATE_LIMIT)
async def performance_daily_change(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Today's portfolio change."""
    from services.performance_service import calculate_daily_change
    return await calculate_daily_change(db, user.id)


# --- Analysis ---

@router.get("/analysis/score/{ticker}")
@limiter.limit(RATE_LIMIT)
async def analysis_score(
    request: Request,
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Setup score 0-10 for a ticker."""
    from services.scoring_service import assess_ticker

    upper = ticker.upper()
    manual_resistance = None
    sector = None
    pos_result = await db.execute(
        select(Position.manual_resistance, Position.sector).where(
            (Position.ticker == upper) | (Position.yfinance_ticker == upper),
            Position.is_active == True,
            Position.user_id == user.id,
        ).limit(1)
    )
    row = pos_result.first()
    if row:
        if row[0] is not None:
            manual_resistance = float(row[0])
        sector = row[1]

    try:
        result = await asyncio.to_thread(
            assess_ticker, upper, sector=sector, manual_resistance=manual_resistance
        )
    except Exception as e:
        logger.warning(f"External score failed for {ticker}: {e}")
        raise HTTPException(status_code=400, detail="Score-Berechnung fehlgeschlagen")

    if result.get("max_score", 0) == 0 and result.get("price") is None:
        raise HTTPException(status_code=404, detail="Ticker nicht gefunden")
    return result


@router.get("/analysis/mrs/{ticker}")
@limiter.limit(RATE_LIMIT)
async def analysis_mrs(
    request: Request,
    ticker: str,
    period: str = Query(default="1y"),
    user: User = Depends(get_api_user),
) -> dict:
    """Weekly MRS (Mansfield Relative Strength) history."""
    from services.chart_service import get_mrs_history
    data = await asyncio.to_thread(get_mrs_history, ticker.upper(), period)
    return {"ticker": ticker.upper(), "data": data}


@router.get("/analysis/levels/{ticker}")
@limiter.limit(RATE_LIMIT)
async def analysis_levels(
    request: Request,
    ticker: str,
    user: User = Depends(get_api_user),
) -> dict:
    """Support and resistance levels for a ticker."""
    from services.chart_service import get_support_resistance_levels
    return await asyncio.to_thread(get_support_resistance_levels, ticker.upper())


@router.get("/analysis/reversal/{ticker}")
@limiter.limit(RATE_LIMIT)
async def analysis_reversal(
    request: Request,
    ticker: str,
    user: User = Depends(get_api_user),
) -> dict:
    """3-point reversal detection."""
    from services.chart_service import get_three_point_reversal
    result = await asyncio.to_thread(get_three_point_reversal, ticker.upper())
    return {"ticker": ticker.upper(), **result}


# --- Screening ---

@router.get("/screening/latest")
@limiter.limit(RATE_LIMIT)
async def screening_latest(
    request: Request,
    min_score: int = Query(default=1, ge=0, le=10),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Results of the most recent completed screening scan."""
    latest_q = (
        select(ScreeningScan)
        .where(ScreeningScan.status == "completed")
        .order_by(desc(ScreeningScan.started_at))
        .limit(1)
    )
    scan = (await db.execute(latest_q)).scalar_one_or_none()
    if not scan:
        return {"scan_id": None, "scanned_at": None, "total": 0, "results": []}

    res_q = (
        select(ScreeningResult)
        .where(ScreeningResult.scan_id == scan.id, ScreeningResult.score >= min_score)
        .order_by(desc(ScreeningResult.score))
    )
    rows = (await db.execute(res_q)).scalars().all()

    return {
        "scan_id": str(scan.id),
        "scanned_at": scan.started_at.isoformat() if scan.started_at else None,
        "total": len(rows),
        "results": [
            {
                "ticker": r.ticker,
                "name": r.name,
                "sector": r.sector,
                "score": r.score,
                "signals": r.signals,
                "price_usd": r.price_usd,
            }
            for r in rows
        ],
    }


# --- Immobilien (Real Estate) ---
#
# Eigener Namespace, weil Immobilien (HEILIGE Regel 4) niemals in die liquide
# Portfolio-Performance einfliessen. Sensible Felder (address, bank, tenant,
# notes) werden ueber filter_property() / filter_mortgage() entfernt.

def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail=f"{label} nicht gefunden")


@router.get("/immobilien")
@limiter.limit(RATE_LIMIT)
async def list_immobilien(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Alle Immobilien des Users inkl. Hypotheken (gefiltert), Totals."""
    summary = await get_properties_summary(db, user_id=user.id)
    return {
        "total_value_chf": summary.get("total_value_chf"),
        "total_mortgage_chf": summary.get("total_mortgage_chf"),
        "total_equity_chf": summary.get("total_equity_chf"),
        "properties": [filter_property(p) for p in summary.get("properties", [])],
    }


@router.get("/immobilien/{property_id}")
@limiter.limit(RATE_LIMIT)
async def get_immobilie(
    request: Request,
    property_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Detailansicht einer einzelnen Immobilie inkl. Hypotheken/Ausgaben/Einnahmen."""
    pid = _parse_uuid(property_id, "Immobilie")
    detail = await get_property_detail(db, pid, user_id=user.id)
    if not detail:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden")
    return filter_property(detail)


@router.get("/immobilien/{property_id}/hypotheken")
@limiter.limit(RATE_LIMIT)
async def list_hypotheken(
    request: Request,
    property_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Hypotheken einer Immobilie (ohne sensible Bank-Felder)."""
    pid = _parse_uuid(property_id, "Immobilie")
    detail = await get_property_detail(db, pid, user_id=user.id)
    if not detail:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden")
    filtered = filter_property(detail)
    return {
        "property_id": filtered["id"],
        "mortgages": filtered.get("mortgages", []),
    }


# --- Vorsorge (Saeule 3a / Pension) ---
#
# Eigener Namespace, weil Vorsorge (HEILIGE Regel 5) nicht in liquides Vermoegen
# einfliesst. Wir liefern hier nur die Accounts selbst — keine aggregierten
# Performance-Kennzahlen, weil cost_basis_chf == market_value_chf manuell
# gepflegt wird. Sensible Felder (bank_name, iban, notes) werden gefiltert.

def _pension_to_dict(p: Position) -> dict:
    return {
        "id": str(p.id),
        "ticker": p.ticker,
        "name": p.name,
        "type": p.type.value if p.type else None,
        "currency": p.currency,
        "cost_basis_chf": float(p.cost_basis_chf or 0),
        "market_value_chf": float(p.cost_basis_chf or 0),
        "buy_date": None,
        "is_active": p.is_active,
    }


@router.get("/vorsorge")
@limiter.limit(RATE_LIMIT)
async def list_vorsorge(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Alle Vorsorge-Konten (Saeule 3a) des Users (ohne bank_name/iban/notes)."""
    result = await db.execute(
        select(Position).where(
            Position.user_id == user.id,
            Position.type == AssetType.pension,
            Position.is_active == True,
        )
    )
    rows = result.scalars().all()
    accounts = [filter_pension_position(_pension_to_dict(p)) for p in rows]
    total = sum(a.get("market_value_chf", 0) or 0 for a in accounts)
    return {
        "total_value_chf": round(total, 2),
        "accounts": accounts,
    }


@router.get("/vorsorge/{position_id}")
@limiter.limit(RATE_LIMIT)
async def get_vorsorge(
    request: Request,
    position_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Detailansicht eines einzelnen Vorsorge-Kontos."""
    pid = _parse_uuid(position_id, "Vorsorge-Konto")
    result = await db.execute(
        select(Position).where(
            Position.id == pid,
            Position.user_id == user.id,
            Position.type == AssetType.pension,
        )
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Vorsorge-Konto nicht gefunden")
    return filter_pension_position(_pension_to_dict(pos))
