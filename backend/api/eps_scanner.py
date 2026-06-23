"""EPS-Scanner API — Quartals-Gewinn-Scanner fuer das S&P-Composite-1500-Universum.

Endpoints:
- GET   /api/eps-scanner/results     — berechnete + gefilterte Ergebnistabelle
- GET   /api/eps-scanner/thresholds  — User-Filter-Schwellen
- PATCH /api/eps-scanner/thresholds  — User-Filter-Schwellen setzen
- GET   /api/eps-scanner/status      — Daten-Freshness / Job-Status

EPS-Rohdaten sind universe-global; Filter-Schwellen sind user_id-scoped.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.user import User
from services import eps_scanner_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eps-scanner", tags=["eps-scanner"])


class ThresholdsUpdate(BaseModel):
    super_quarter_yoy_pct: float | None = Field(default=None, gt=0, le=200)
    acceleration_margin_pp: float | None = Field(default=None, gt=0, le=200)
    outlier_multiplier: float | None = Field(default=None, gt=0, le=20)


@router.get("/results")
async def get_results(
    super_quarter_only: bool = Query(False),
    record_quarter_only: bool = Query(False),
    turnaround_only: bool = Query(False),
    min_quarters: int = Query(6, ge=2, le=8),
    sector: list[str] | None = Query(None),
    index: list[str] | None = Query(None),
    search: str | None = Query(None, max_length=50),
    sort_by: str = Query("yoy_growth"),
    sort_asc: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Berechnete und gefilterte Scanner-Ergebnisse fuer den eingeloggten User."""
    valid_sort = {"ticker", "yoy_growth", "streak_count", "latest_eps"}
    if sort_by not in valid_sort:
        sort_by = "yoy_growth"
    return await svc.get_scanner_results(
        db,
        user.id,
        super_quarter_only=super_quarter_only,
        record_quarter_only=record_quarter_only,
        turnaround_only=turnaround_only,
        min_quarters=min_quarters,
        sectors=sector,
        indices=index,
        search=search,
        sort_by=sort_by,
        sort_asc=sort_asc,
        page=page,
        per_page=per_page,
    )


@router.get("/ticker/{ticker}")
async def get_ticker(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """EPS-Metriken fuer einen einzelnen Ticker (fuer das Kontext-Widget).

    404, wenn der Ticker nicht im Scanner-Universum ist bzw. keine EPS-Daten hat.
    """
    res = await svc.get_ticker_result(db, user.id, ticker)
    if res is None:
        raise HTTPException(status_code=404, detail="Keine EPS-Daten fuer diesen Ticker")
    return res


@router.get("/thresholds")
async def get_thresholds(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Aktuelle Filter-Schwellen des Users (Service-Defaults bei NULL)."""
    t = await svc.resolve_thresholds(db, user.id)
    return {
        "super_quarter_yoy_pct": t.yoy_threshold,
        "acceleration_margin_pp": t.acceleration_margin,
        "outlier_multiplier": t.outlier_multiplier,
    }


@router.patch("/thresholds")
@limiter.limit("30/minute")
async def patch_thresholds(
    request: Request,
    data: ThresholdsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Setze die Filter-Schwellen des Users (user_id-scoped)."""
    t = await svc.update_thresholds(
        db,
        user.id,
        yoy=data.super_quarter_yoy_pct,
        accel=data.acceleration_margin_pp,
        outlier=data.outlier_multiplier,
    )
    return {
        "super_quarter_yoy_pct": t.yoy_threshold,
        "acceleration_margin_pp": t.acceleration_margin,
        "outlier_multiplier": t.outlier_multiplier,
    }


@router.get("/status")
async def get_scanner_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Daten-Freshness und Worker-Job-Status."""
    return await svc.get_status(db)
