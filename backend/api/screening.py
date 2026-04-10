import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import async_session, get_db
from models.screening import ScreeningResult, ScreeningScan
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/screening", tags=["screening"])


async def _run_scan_background(scan_id: uuid.UUID) -> None:
    """Run scan in background with its own DB session."""
    from services.screening.screening_service import run_scan
    async with async_session() as db:
        try:
            await run_scan(db, scan_id)
        except Exception:
            logger.exception("Screening scan %s failed", scan_id)
            scan = await db.get(ScreeningScan, scan_id)
            if scan:
                scan.status = "error"
                scan.error = "Scan fehlgeschlagen"
                await db.commit()


@router.post("/scan")
@limiter.limit("5/minute")
async def start_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start a new screening scan. Returns scan_id for progress polling."""
    # Retention: Scans werden akkumuliert und durch den taeglichen Cleanup-Job
    # in backend/worker.py (cleanup_old_screening_scans) nach 365 Tagen entfernt.
    # Siehe SCOPE_SMART_MONEY_V4.md Block 0a.

    scan = ScreeningScan(status="pending", steps=[])
    db.add(scan)
    await db.commit()
    await db.refresh(scan)

    background_tasks.add_task(_run_scan_background, scan.id)

    return {"scan_id": str(scan.id), "status": "pending"}


@router.get("/scan/{scan_id}/progress")
@limiter.limit("60/minute")
async def get_scan_progress(
    request: Request,
    scan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Poll scan progress."""
    scan = await db.get(ScreeningScan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan nicht gefunden")

    return {
        "scan_id": str(scan.id),
        "status": scan.status,
        "steps": scan.steps or [],
        "result_count": scan.result_count,
        "started_at": scan.started_at.isoformat() if scan.started_at else None,
        "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
        "error": scan.error,
    }


@router.get("/ticker/{ticker}")
@limiter.limit("60/minute")
async def get_ticker_result(
    request: Request,
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get screening result for a single ticker from the latest completed scan."""
    latest_scan_q = (
        select(ScreeningScan)
        .where(ScreeningScan.status == "completed")
        .order_by(desc(ScreeningScan.started_at))
        .limit(1)
    )
    scan = (await db.execute(latest_scan_q)).scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=404, detail="Kein abgeschlossener Scan vorhanden")

    result_q = select(ScreeningResult).where(
        ScreeningResult.scan_id == scan.id,
        ScreeningResult.ticker == ticker.upper(),
    )
    result = (await db.execute(result_q)).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="Ticker nicht im Screening gefunden")

    return {
        "ticker": result.ticker,
        "name": result.name,
        "sector": result.sector,
        "score": result.score,
        "signals": result.signals,
        "price_usd": result.price_usd,
        "scanned_at": scan.started_at.isoformat() if scan.started_at else None,
    }


@router.get("/macro/cot")
@limiter.limit("30/minute")
async def get_macro_cot(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Latest CFTC COT snapshot per configured instrument with 52w percentiles.

    Isolated macro/positioning data — has no influence on the equity screening
    score. See SCOPE_SMART_MONEY_V4.md Block 1.
    """
    from services.macro.cot_service import get_latest_cot_overview
    return await get_latest_cot_overview(db)


@router.get("/results")
@limiter.limit("30/minute")
async def get_results(
    request: Request,
    min_score: int = Query(default=1, ge=0, le=10),
    signal_type: str | None = Query(default=None),
    sort_by: str = Query(default="score"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get screening results from the latest completed scan."""
    # Find latest completed scan
    latest_scan_q = (
        select(ScreeningScan)
        .where(ScreeningScan.status == "completed")
        .order_by(desc(ScreeningScan.started_at))
        .limit(1)
    )
    scan_result = await db.execute(latest_scan_q)
    scan = scan_result.scalar_one_or_none()

    if not scan:
        return {
            "results": [],
            "total": 0,
            "scan_id": None,
            "scanned_at": None,
        }

    # Build query
    query = select(ScreeningResult).where(
        ScreeningResult.scan_id == scan.id,
        ScreeningResult.score >= min_score,
    )

    # Filter by signal type
    if signal_type:
        query = query.where(
            ScreeningResult.signals.has_key(signal_type)
        )

    # Count total
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Sort
    if sort_by == "ticker":
        query = query.order_by(ScreeningResult.ticker)
    else:
        query = query.order_by(desc(ScreeningResult.score), ScreeningResult.ticker)

    # Paginate
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    results = (await db.execute(query)).scalars().all()

    return {
        "results": [
            {
                "ticker": r.ticker,
                "name": r.name,
                "sector": r.sector,
                "score": r.score,
                "signals": r.signals,
                "price_usd": r.price_usd,
            }
            for r in results
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "scan_id": str(scan.id),
        "scanned_at": scan.started_at.isoformat() if scan.started_at else None,
    }
