import asyncio
import datetime
import logging

from fastapi import APIRouter, Depends, Query, Request
from api.schemas import (
    TotalReturnResponse, DailyChangeResponse, MonthlyReturnsResponse,
    RealizedGainsResponse, FeeSummaryResponse,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.position import Position
from models.user import User
from services.history_service import get_portfolio_history
from services.recalculate_service import recalculate_position, recalculate_all_positions
from api.schemas import RecalculateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["performance"])


@router.get("/history")
@limiter.limit("5/minute")
async def portfolio_history(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    start: datetime.date = Query(default=None),
    end: datetime.date = Query(default=None),
    benchmark: str = Query(default="^GSPC"),
):
    if not start:
        start = datetime.date.today() - datetime.timedelta(days=365)
    if not end:
        end = datetime.date.today()
    return await get_portfolio_history(db, start, end, benchmark, user_id=user.id)


@router.get("/monthly-returns", response_model=MonthlyReturnsResponse)
@limiter.limit("5/minute")
async def portfolio_monthly_returns(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from services.performance_history_service import get_monthly_returns
    return await get_monthly_returns(db, user_id=user.id)


@router.get("/benchmark-returns")
@limiter.limit("60/minute")
async def benchmark_returns(request: Request, ticker: str = "^GSPC", user: User = Depends(get_current_user)):
    """Monthly returns for a benchmark index (default: S&P 500)."""
    ALLOWED_BENCHMARKS = frozenset({"^GSPC", "^IXIC", "^STOXX50E", "^SSMI"})
    if ticker not in ALLOWED_BENCHMARKS:
        raise HTTPException(status_code=400, detail="Ungültiger Benchmark-Ticker")
    from services.benchmark_service import get_benchmark_monthly_returns
    return await asyncio.to_thread(get_benchmark_monthly_returns, ticker)


@router.get("/total-return", response_model=TotalReturnResponse)
@limiter.limit("5/minute")
async def total_return(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from services.total_return_service import get_total_return
    return await get_total_return(db, user_id=user.id)


@router.get("/realized-gains", response_model=RealizedGainsResponse)
@limiter.limit("5/minute")
async def realized_gains(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from services.total_return_service import get_realized_gains
    return await get_realized_gains(db, user_id=user.id)


@router.get("/fee-summary", response_model=FeeSummaryResponse)
@limiter.limit("60/minute")
async def fee_summary(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from services.total_return_service import get_fee_summary
    return await get_fee_summary(db, user_id=user.id)


@router.get("/daily-change", response_model=DailyChangeResponse)
@limiter.limit("5/minute")
async def portfolio_daily_change(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Calculate today's portfolio change using price_cache (not positions.current_price)."""
    from services.performance_service import calculate_daily_change
    return await calculate_daily_change(db, user.id)


@router.get("/allocation/core-satellite")
@limiter.limit("60/minute")
async def core_satellite_allocation(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    view: str = Query(default="liquid"),
):
    """Return core/satellite/unassigned allocation breakdown."""
    from services.allocation_service import get_core_satellite_allocation
    return await get_core_satellite_allocation(db, user.id, view)


@router.post("/recalculate")
@limiter.limit("5/minute")
async def recalculate_portfolio(
    request: Request,
    data: RecalculateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recalculate cost_basis_chf for all or selected positions from transactions."""
    if data and data.tickers:
        pos_result = await db.execute(
            select(Position).where(
                Position.ticker.in_(data.tickers),
                Position.user_id == user.id,
                Position.is_active == True,
            )
        )
        positions_to_recalc = pos_result.scalars().all()
        results = []
        for pos in positions_to_recalc:
            r = await recalculate_position(db, pos.id)
            results.append(r)
        await db.commit()
    else:
        results = await recalculate_all_positions(db, user_id=user.id)

    positions = [
        {
            "ticker": r["ticker"],
            "old_cost_basis_chf": r["old_cost_basis_chf"],
            "new_cost_basis_chf": r["new_cost_basis_chf"],
            "delta_chf": round(r["new_cost_basis_chf"] - r["old_cost_basis_chf"], 2),
        }
        for r in results
        if "error" not in r
    ]

    return {
        "recalculated": len(positions),
        "positions": positions,
    }


@router.post("/fix-total-chf")
@limiter.limit("5/minute")
async def fix_total_chf(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Recalculate total_chf from fx_rate_to_chf for all foreign currency transactions."""
    from services.transaction_service import fix_foreign_total_chf
    return await fix_foreign_total_chf(db, user.id)


@router.post("/regenerate-snapshots")
@limiter.limit("5/minute")
async def regenerate_snapshots_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Regenerate all portfolio snapshots from transaction history + historical prices."""
    from services.snapshot_service import regenerate_snapshots
    result = await regenerate_snapshots(db, user.id)
    return result


@router.post("/earnings/refresh")
@limiter.limit("5/minute")
async def refresh_earnings(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Fetch and store next earnings dates for all active stock/etf positions."""
    from services.earnings_service import refresh_all_earnings
    return await refresh_all_earnings(db, user.id)
