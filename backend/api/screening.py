import asyncio
import logging
import uuid
from datetime import timedelta

from dateutils import utcnow
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import desc, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import async_session, get_db
from models.screening import ScreeningResult, ScreeningScan
from models.user import User
from services.concentration_service import get_overlap_max_weight_for_tickers
from services.screening.sector_rotation_service import VALID_MOMENTUM_VALUES

SCHWUR2_EARNINGS_VETO_DAYS = 7

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
@limiter.limit("1/day")
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
        "score_display": result.score_display,
        "signals": result.signals,
        "price_usd": result.price_usd,
        "industry_name": result.industry_name,
        "sector_momentum": result.sector_momentum,
        "sector_bonus": result.sector_bonus,
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
    min_score_display: int | None = Query(default=None, ge=0, le=100),
    signal_type: str | None = Query(default=None),
    signal_types: list[str] | None = Query(default=None),
    sector_momentum: str | None = Query(default=None),
    sector_momentums: list[str] | None = Query(default=None),
    sectors: list[str] | None = Query(default=None),
    schwur1_only: bool = Query(default=False),
    schwur2_only: bool = Query(default=False),
    schwur3_only: bool = Query(default=False),
    sort_by: str = Query(default="score"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get screening results from the latest completed scan.

    Filter-Semantik:
    - `min_score` (raw 0..10): backwards-compat fuer /screening Page.
    - `min_score_display` (0..100): Smart-Money-Page; hat Vorrang wenn gesetzt.
    - `signal_types[]` / `sector_momentums[]` / `sectors[]`: Multi-Value-Versionen
      mit OR-Match. Single-Value-Versionen (`signal_type`, `sector_momentum`)
      bleiben fuer Backwards-Compat funktional; Multi-Value hat Vorrang
      wenn gesetzt.

    Response enthaelt `all_sectors`: DISTINCT(sector) ueber den aktuellen Scan
    VOR Filter — Frontend kann damit Sektor-Checkboxen vollstaendig halten.
    """
    if sector_momentum is not None and sector_momentum not in VALID_MOMENTUM_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"sector_momentum muss einer von {sorted(VALID_MOMENTUM_VALUES)} sein",
        )
    if sector_momentums:
        invalid = [m for m in sector_momentums if m not in VALID_MOMENTUM_VALUES]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"sector_momentums enthaelt ungueltige Werte: {invalid}",
            )

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
            "all_sectors": [],
            "scan_id": None,
            "scanned_at": None,
        }

    # all_sectors VOR Filter — Frontend braucht das Vollset fuer Sektor-Checkboxen
    all_sectors_q = (
        select(ScreeningResult.sector)
        .where(
            ScreeningResult.scan_id == scan.id,
            ScreeningResult.sector.is_not(None),
        )
        .distinct()
        .order_by(ScreeningResult.sector)
    )
    all_sectors = [s for s in (await db.execute(all_sectors_q)).scalars().all() if s]

    # Build query
    query = select(ScreeningResult).where(
        ScreeningResult.scan_id == scan.id,
        ScreeningResult.score >= min_score,
    )

    if min_score_display is not None:
        query = query.where(ScreeningResult.score_display >= min_score_display)

    # Filter by signal type — Multi-Value hat Vorrang, sonst Single.
    # has_key portierbar zwischen JSONB (Prod) und JSON (SQLite-Test).
    if signal_types:
        query = query.where(or_(*(ScreeningResult.signals.has_key(s) for s in signal_types)))
    elif signal_type:
        query = query.where(ScreeningResult.signals.has_key(signal_type))

    # Filter by sector momentum — Multi-Value hat Vorrang, sonst Single
    if sector_momentums:
        query = query.where(ScreeningResult.sector_momentum.in_(sector_momentums))
    elif sector_momentum:
        query = query.where(ScreeningResult.sector_momentum == sector_momentum)

    # Filter by sectors (multi-value)
    if sectors:
        query = query.where(ScreeningResult.sector.in_(sectors))

    # --- Schwur-Filter (Iteration 2.6) -------------------------------
    # Defensive Default: NULL-Daten (kein SMA / kein Earnings-Datum)
    # passieren den Filter — Schwur ist Verschaerfung, kein Pflicht-Drop.
    if schwur1_only:
        query = query.where(
            or_(
                ScreeningResult.sma150.is_(None),
                ScreeningResult.price_usd > ScreeningResult.sma150,
            )
        )
    if schwur2_only:
        veto_cutoff = utcnow() + timedelta(days=SCHWUR2_EARNINGS_VETO_DAYS)
        query = query.where(
            or_(
                ScreeningResult.next_earnings_at.is_(None),
                ScreeningResult.next_earnings_at > veto_cutoff,
            )
        )
    if schwur3_only:
        scan_tickers_q = (
            select(distinct(ScreeningResult.ticker))
            .where(ScreeningResult.scan_id == scan.id)
        )
        scan_tickers = [
            t for t in (await db.execute(scan_tickers_q)).scalars().all() if t
        ]
        overlap_map = await get_overlap_max_weight_for_tickers(
            db, scan_tickers, user.id
        )
        if overlap_map:
            query = query.where(ScreeningResult.ticker.not_in(list(overlap_map.keys())))

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
                "score_display": r.score_display,
                "signals": r.signals,
                "price_usd": r.price_usd,
                "industry_name": r.industry_name,
                "sector_momentum": r.sector_momentum,
                "sector_bonus": r.sector_bonus,
                "sma150": float(r.sma150) if r.sma150 is not None else None,
                "next_earnings_at": r.next_earnings_at.isoformat() if r.next_earnings_at else None,
            }
            for r in results
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "all_sectors": all_sectors,
        "scan_id": str(scan.id),
        "scanned_at": scan.started_at.isoformat() if scan.started_at else None,
    }
