import asyncio
import datetime
import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.position import Position
from models.user import User
from models.transaction import Transaction
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


@router.get("/monthly-returns")
@limiter.limit("5/minute")
async def portfolio_monthly_returns(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from services.performance_history_service import get_monthly_returns
    return await get_monthly_returns(db, user_id=user.id)


@router.get("/benchmark-returns")
@limiter.limit("60/minute")
async def benchmark_returns(request: Request, ticker: str = "^GSPC", user: User = Depends(get_current_user)):
    """Monthly returns for a benchmark index (default: S&P 500)."""
    import asyncio
    from services.benchmark_service import get_benchmark_monthly_returns
    return await asyncio.to_thread(get_benchmark_monthly_returns, ticker)


@router.get("/total-return")
@limiter.limit("5/minute")
async def total_return(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from services.total_return_service import get_total_return
    return await get_total_return(db, user_id=user.id)


@router.get("/realized-gains")
@limiter.limit("5/minute")
async def realized_gains(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from services.total_return_service import get_realized_gains
    return await get_realized_gains(db, user_id=user.id)


@router.get("/fee-summary")
@limiter.limit("60/minute")
async def fee_summary(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from services.total_return_service import get_fee_summary
    return await get_fee_summary(db, user_id=user.id)


@router.get("/daily-change")
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
    result = await db.execute(
        select(Position).where(Position.is_active == True, Position.user_id == user.id)
    )
    positions = result.scalars().all()

    from services.utils import get_fx_rates_batch
    fx_rates = await asyncio.to_thread(get_fx_rates_batch)

    # Only include tradable types for core/satellite
    TRADABLE_TYPES = {"stock", "etf"}
    # Exclude types from liquid view
    EXCLUDE_LIQUID = {"pension", "real_estate", "private_equity"}

    core = {"value_chf": 0, "positions": []}
    satellite = {"value_chf": 0, "positions": []}
    unassigned = {"value_chf": 0, "positions": []}

    for pos in positions:
        if float(pos.shares) <= 0:
            continue
        if view == "liquid" and pos.type.value in EXCLUDE_LIQUID:
            continue
        if pos.type.value not in TRADABLE_TYPES:
            continue

        # Use current_price from DB (updated by cache refresh) — no blocking API calls
        shares = float(pos.shares)
        price = float(pos.current_price) if pos.current_price else 0
        if price > 0:
            fx = fx_rates.get(pos.currency, 1.0) if pos.currency != "CHF" else 1.0
            value_chf = round(price * shares * fx, 2)
        else:
            value_chf = round(float(pos.cost_basis_chf), 2)

        pos_info = {
            "ticker": pos.ticker,
            "name": pos.name,
            "value_chf": value_chf,
            "type": pos.type.value,
            "position_type": pos.position_type,
        }

        if pos.position_type == "core":
            core["value_chf"] += value_chf
            core["positions"].append(pos_info)
        elif pos.position_type == "satellite":
            satellite["value_chf"] += value_chf
            satellite["positions"].append(pos_info)
        else:
            unassigned["value_chf"] += value_chf
            unassigned["positions"].append(pos_info)

    total = core["value_chf"] + satellite["value_chf"] + unassigned["value_chf"]
    core["pct"] = round(core["value_chf"] / total * 100, 1) if total > 0 else 0
    satellite["pct"] = round(satellite["value_chf"] / total * 100, 1) if total > 0 else 0
    unassigned["pct"] = round(unassigned["value_chf"] / total * 100, 1) if total > 0 else 0

    # Sort positions by value descending
    core["positions"].sort(key=lambda p: p["value_chf"], reverse=True)
    satellite["positions"].sort(key=lambda p: p["value_chf"], reverse=True)
    unassigned["positions"].sort(key=lambda p: p["value_chf"], reverse=True)

    return {"core": core, "satellite": satellite, "unassigned": unassigned}


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
        results = []
        for ticker in data.tickers:
            pos_result = await db.execute(
                select(Position).where(
                    Position.ticker == ticker,
                    Position.user_id == user.id,
                    Position.is_active == True,
                )
            )
            pos = pos_result.scalars().first()
            if pos:
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
    result = await db.execute(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.currency != "CHF",
            Transaction.shares > 0,
            Transaction.price_per_share > 0,
            Transaction.fx_rate_to_chf > 0,
        )
    )
    txns = result.scalars().all()

    fixed = []
    for txn in txns:
        old_total = float(txn.total_chf)
        new_total = round(abs(float(txn.shares) * float(txn.price_per_share)) * float(txn.fx_rate_to_chf) + float(txn.fees_chf), 2)
        if abs(old_total - new_total) >= 0.01:
            txn.total_chf = new_total
            fixed.append({
                "ticker": txn.isin or str(txn.position_id)[:8],
                "date": txn.date.isoformat(),
                "old_total_chf": old_total,
                "new_total_chf": new_total,
                "delta": round(new_total - old_total, 2),
            })

    if fixed:
        await db.commit()

    return {"fixed": len(fixed), "transactions": fixed}


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
    from services.earnings_service import get_next_earnings_date

    result = await db.execute(
        select(Position).where(
            Position.is_active == True,
            Position.user_id == user.id,
            Position.shares > 0,
            Position.type.in_(["stock", "etf"]),
        )
    )
    positions = result.scalars().all()
    updated = []

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

    results = await asyncio.gather(*[_fetch_earnings(p) for p in positions], return_exceptions=True)
    for r in results:
        if isinstance(r, dict):
            updated.append(r)
        elif isinstance(r, Exception):
            logger.debug(f"Earnings fetch failed: {r}")

    await db.commit()
    return {"updated": len(updated), "positions": updated}
