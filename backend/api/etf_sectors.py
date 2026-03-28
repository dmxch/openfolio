"""API routes for ETF sector weight management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, delete

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.etf_sector_weight import EtfSectorWeight
from models.user import User
from services.sector_mapping import FINVIZ_SECTORS

router = APIRouter(prefix="/api/etf-sectors", tags=["etf-sectors"])

VALID_SECTORS = set(FINVIZ_SECTORS)


class SectorWeight(BaseModel):
    sector: str
    weight_pct: float


class SectorWeightsBody(BaseModel):
    sectors: list[SectorWeight]


@router.get("/{ticker}")
async def get_etf_sectors(ticker: str, db=Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(
        select(EtfSectorWeight).where(
            EtfSectorWeight.ticker == ticker.upper(),
            EtfSectorWeight.user_id == user.id,
        )
    )
    weights = result.scalars().all()

    sectors = [{"sector": w.sector, "weight_pct": float(w.weight_pct)} for w in weights]
    total = sum(s["weight_pct"] for s in sectors)

    return {
        "ticker": ticker.upper(),
        "sectors": sorted(sectors, key=lambda s: s["weight_pct"], reverse=True),
        "is_complete": 99.9 <= total <= 100.1,
    }


@router.put("/{ticker}")
@limiter.limit("30/minute")
async def put_etf_sectors(request: Request, ticker: str, body: SectorWeightsBody, db=Depends(get_db), user: User = Depends(get_current_user)):
    for s in body.sectors:
        if s.sector not in VALID_SECTORS:
            raise HTTPException(400, f"Ungültiger Sektor: {s.sector}")
        if not (0.0 <= s.weight_pct <= 100.0):
            raise HTTPException(400, f"Gewichtung muss zwischen 0 und 100 liegen: {s.sector}")

    total = sum(s.weight_pct for s in body.sectors)
    if not (99.9 <= total <= 100.1):
        raise HTTPException(400, f"Summe muss 100% ergeben (aktuell: {total:.1f}%)")

    ticker_upper = ticker.upper()

    await db.execute(
        delete(EtfSectorWeight).where(
            EtfSectorWeight.ticker == ticker_upper,
            EtfSectorWeight.user_id == user.id,
        )
    )

    for s in body.sectors:
        if s.weight_pct > 0:
            db.add(EtfSectorWeight(
                user_id=user.id,
                ticker=ticker_upper,
                sector=s.sector,
                weight_pct=s.weight_pct,
            ))

    await db.commit()

    return await get_etf_sectors(ticker_upper, db, user)


@router.delete("/{ticker}")
@limiter.limit("30/minute")
async def delete_etf_sectors(request: Request, ticker: str, db=Depends(get_db), user: User = Depends(get_current_user)):
    await db.execute(
        delete(EtfSectorWeight).where(
            EtfSectorWeight.ticker == ticker.upper(),
            EtfSectorWeight.user_id == user.id,
        )
    )
    await db.commit()
    return {"status": "deleted", "ticker": ticker.upper()}
