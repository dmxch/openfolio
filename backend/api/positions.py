import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.position import Position, AssetType, PricingMode, PriceSource, Style
from models.user import User
from models.transaction import Transaction
from api.schemas import PositionResponse
from services.snapshot_trigger import trigger_snapshot_regen
from services.dividend_service import fetch_dividends
from services.price_service import get_stock_price
from services.recalculate_service import recalculate_position, recalculate_all_positions, debug_position
from services.sector_mapping import INDUSTRY_TO_SECTOR
from api.auth import limiter
from api.portfolio import invalidate_portfolio_cache
from services.encryption_helpers import encrypt_field, decrypt_field, decrypt_and_mask_iban
from constants.limits import MAX_POSITIONS_PER_USER

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["positions"])


class PositionCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    type: AssetType
    sector: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    currency: str = Field(default="CHF", min_length=3, max_length=3)
    pricing_mode: PricingMode = PricingMode.auto
    risk_class: int = Field(default=3, ge=1, le=5)
    style: Optional[Style] = None
    position_type: Optional[str] = Field(default=None, max_length=20)
    yfinance_ticker: Optional[str] = Field(default=None, max_length=60)
    coingecko_id: Optional[str] = Field(default=None, max_length=100)
    gold_org: bool = False
    price_source: PriceSource = PriceSource.yahoo
    isin: Optional[str] = Field(default=None, max_length=20)
    shares: float = Field(default=0, ge=0)
    cost_basis_chf: float = Field(default=0, ge=0)
    current_price: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = Field(default=None, max_length=2000)
    bank_name: Optional[str] = Field(default=None, max_length=200)
    iban: Optional[str] = Field(default=None, max_length=34)


class PositionUpdate(BaseModel):
    ticker: Optional[str] = Field(default=None, min_length=1, max_length=60)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    type: Optional[AssetType] = None
    sector: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    pricing_mode: Optional[PricingMode] = None
    risk_class: Optional[int] = Field(default=None, ge=1, le=5)
    style: Optional[Style] = None
    position_type: Optional[str] = Field(default=None, max_length=20)
    yfinance_ticker: Optional[str] = Field(default=None, max_length=60)
    coingecko_id: Optional[str] = Field(default=None, max_length=100)
    gold_org: Optional[bool] = None
    price_source: Optional[PriceSource] = None
    isin: Optional[str] = Field(default=None, max_length=20)
    shares: Optional[float] = Field(default=None, ge=0)
    cost_basis_chf: Optional[float] = Field(default=None, ge=0)
    current_price: Optional[float] = Field(default=None, ge=0)
    manual_resistance: Optional[float] = Field(default=None, ge=0)
    stop_loss_price: Optional[float] = Field(default=None, ge=0)
    stop_loss_confirmed_at_broker: Optional[bool] = None
    stop_loss_method: Optional[str] = Field(default=None, max_length=50)
    is_active: Optional[bool] = None
    bank_name: Optional[str] = Field(default=None, max_length=200)
    iban: Optional[str] = Field(default=None, max_length=34)
    notes: Optional[str] = Field(default=None, max_length=2000)


class PositionTypeBatchItem(BaseModel):
    ticker: str
    position_type: str  # 'core' or 'satellite'


class PositionTypeBatchRequest(BaseModel):
    items: list[PositionTypeBatchItem]


def _pos_to_dict(pos: Position) -> dict:
    return {
        "id": str(pos.id),
        "ticker": pos.ticker,
        "name": pos.name,
        "type": pos.type.value,
        "sector": pos.sector,
        "industry": pos.industry,
        "currency": pos.currency,
        "pricing_mode": pos.pricing_mode.value,
        "risk_class": pos.risk_class,
        "style": pos.style.value if pos.style else None,
        "position_type": pos.position_type,
        "yfinance_ticker": pos.yfinance_ticker,
        "coingecko_id": pos.coingecko_id,
        "gold_org": pos.gold_org,
        "price_source": pos.price_source.value,
        "isin": pos.isin,
        "shares": float(pos.shares),
        "cost_basis_chf": float(pos.cost_basis_chf),
        "current_price": float(pos.current_price) if pos.current_price else None,
        "manual_resistance": float(pos.manual_resistance) if pos.manual_resistance is not None else None,
        "stop_loss_price": float(pos.stop_loss_price) if pos.stop_loss_price is not None else None,
        "stop_loss_confirmed_at_broker": pos.stop_loss_confirmed_at_broker,
        "stop_loss_updated_at": pos.stop_loss_updated_at.isoformat() if pos.stop_loss_updated_at else None,
        "stop_loss_method": pos.stop_loss_method,
        "next_earnings_date": pos.next_earnings_date.isoformat() if pos.next_earnings_date else None,
        "is_etf": pos.is_etf,
        "is_active": pos.is_active,
        "notes": decrypt_field(pos.notes),
        "bank_name": decrypt_field(pos.bank_name),
        "iban": decrypt_and_mask_iban(pos.iban),
        "created_at": pos.created_at.isoformat() if pos.created_at else None,
        "updated_at": pos.updated_at.isoformat() if pos.updated_at else None,
    }


@router.get("/positions", response_model=list[PositionResponse])
async def list_positions(include_closed: bool = False, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(Position).where(Position.is_active == True, Position.user_id == user.id)
    if not include_closed:
        query = query.where(Position.shares > 0)
    result = await db.execute(query.order_by(func.lower(Position.name)))
    positions = result.scalars().all()
    return [_pos_to_dict(p) for p in positions]


@router.get("/positions-without-type")
async def positions_without_type(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Return active tradable positions (shares > 0) that have no position_type set."""
    from services.utils import get_fx_rates_batch

    result = await db.execute(
        select(Position).where(
            Position.is_active == True,
            Position.user_id == user.id,
            Position.shares > 0,
            Position.position_type.is_(None),
            Position.type.in_(["stock", "etf"]),
        )
    )
    positions = result.scalars().all()
    fx_rates = await asyncio.to_thread(get_fx_rates_batch)
    return [
        {
            "id": str(p.id),
            "ticker": p.ticker,
            "name": p.name,
            "shares": float(p.shares),
            "current_price": float(p.current_price) if p.current_price else None,
            "currency": p.currency,
            "market_value_chf": round(
                float(p.current_price or 0) * float(p.shares) * (fx_rates.get(p.currency, 1.0) if p.currency != "CHF" else 1.0), 2
            ),
        }
        for p in positions
    ]


@router.get("/positions/{position_id}", response_model=PositionResponse)
async def get_position(position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    return _pos_to_dict(pos)



@router.post("/positions", status_code=201)
@limiter.limit("30/minute")
async def create_position(request: Request, data: PositionCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # Per-user limit
    count = await db.scalar(select(func.count(Position.id)).where(Position.user_id == user.id))
    if count >= MAX_POSITIONS_PER_USER:
        raise HTTPException(400, f"Maximale Anzahl Positionen erreicht ({MAX_POSITIONS_PER_USER})")
    dump = data.model_dump()
    # Encrypt PII fields before saving
    if dump.get("iban"):
        dump["iban"] = encrypt_field(dump["iban"])
    if dump.get("notes"):
        dump["notes"] = encrypt_field(dump["notes"])
    if dump.get("bank_name"):
        dump["bank_name"] = encrypt_field(dump["bank_name"])
    # Auto-derive sector from industry
    if dump.get("industry"):
        if dump["industry"] not in INDUSTRY_TO_SECTOR:
            raise HTTPException(422, f"Ungültige Branche: {dump['industry']}")
        dump["sector"] = INDUSTRY_TO_SECTOR[dump["industry"]]
    elif "industry" in dump:
        dump["sector"] = None
    pos = Position(**dump, user_id=user.id)
    db.add(pos)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(409, "Eine Position mit diesem Namen existiert bereits.")
        raise HTTPException(500, "Position konnte nicht erstellt werden.")
    await db.refresh(pos)
    invalidate_portfolio_cache(str(user.id))
    # Regenerate historical snapshots if position has cost basis (= historical data)
    if float(pos.cost_basis_chf or 0) > 0:
        trigger_snapshot_regen(user.id, pos.created_at.date() if pos.created_at else None)
    return _pos_to_dict(pos)


@router.put("/positions/{position_id}")
@limiter.limit("30/minute")
async def update_position(request: Request, position_id: uuid.UUID, data: PositionUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    updates = data.model_dump(exclude_unset=True)
    # Encrypt PII fields before saving
    if "iban" in updates:
        updates["iban"] = encrypt_field(updates["iban"]) if updates["iban"] else None
    if "notes" in updates:
        updates["notes"] = encrypt_field(updates["notes"]) if updates["notes"] else None
    if "bank_name" in updates:
        updates["bank_name"] = encrypt_field(updates["bank_name"]) if updates["bank_name"] else None
    # Auto-derive sector from industry
    if "industry" in updates:
        if updates["industry"]:
            if updates["industry"] not in INDUSTRY_TO_SECTOR:
                raise HTTPException(422, f"Ungültige Branche: {updates['industry']}")
            updates["sector"] = INDUSTRY_TO_SECTOR[updates["industry"]]
        else:
            # Industry cleared → clear sector too
            updates["sector"] = None
    for key, val in updates.items():
        setattr(pos, key, val)
    await db.commit()
    await db.refresh(pos)
    invalidate_portfolio_cache(str(user.id))
    return _pos_to_dict(pos)


@router.delete("/positions/{position_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_position(request: Request, position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    user_id = pos.user_id
    created = pos.created_at.date() if pos.created_at else None
    await db.delete(pos)
    await db.commit()
    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user_id, created)


@router.get("/positions/{position_id}/dividends")
async def position_dividends(position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    # Find earliest buy date
    result = await db.execute(
        select(Transaction.date)
        .where(Transaction.position_id == position_id, Transaction.type == "buy")
        .order_by(Transaction.date.asc())
        .limit(1)
    )
    first_buy = result.scalar()
    if not first_buy:
        return []
    yf_ticker = pos.yfinance_ticker or pos.ticker
    return await asyncio.to_thread(fetch_dividends, yf_ticker, first_buy, float(pos.shares), pos.currency)


@router.get("/positions/{position_id}/test-price")
@limiter.limit("10/minute")
async def test_price(request: Request, position_id: uuid.UUID, yfinance_ticker: str = Query(...), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    result = await asyncio.to_thread(get_stock_price, yfinance_ticker)
    if not result:
        return {"ok": False, "error": f"Kein Kurs für '{yfinance_ticker}' gefunden"}
    return {"ok": True, "price": result["price"], "currency": result["currency"]}


@router.get("/positions/{position_id}/history")
async def position_history(position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    result = await db.execute(
        select(Transaction)
        .where(Transaction.position_id == position_id)
        .order_by(Transaction.date.desc())
    )
    txns = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "type": t.type.value,
            "date": t.date.isoformat(),
            "shares": float(t.shares),
            "price_per_share": float(t.price_per_share),
            "currency": t.currency,
            "fx_rate_to_chf": float(t.fx_rate_to_chf),
            "fees_chf": float(t.fees_chf),
            "taxes_chf": float(t.taxes_chf),
            "total_chf": float(t.total_chf),
            "notes": t.notes,
        }
        for t in txns
    ]


@router.get("/positions/{position_id}/debug")
@limiter.limit("10/minute")
async def debug_single(request: Request, position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    return await debug_position(db, position_id)


@router.post("/positions/recalculate")
@limiter.limit("5/minute")
async def recalculate_all(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    results = await recalculate_all_positions(db, user_id=user.id)
    return {"results": results}


@router.post("/positions/{position_id}/recalculate")
@limiter.limit("5/minute")
async def recalculate_single(request: Request, position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    result = await recalculate_position(db, position_id)
    await db.commit()
    invalidate_portfolio_cache(str(user.id))
    return result


@router.post("/position-type/batch")
@limiter.limit("5/minute")
async def batch_position_type(request: Request, data: PositionTypeBatchRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Set position_type for multiple positions at once."""
    results = []
    errors = []

    # Validate types first
    valid_items = []
    for item in data.items:
        if item.position_type not in ("core", "satellite"):
            errors.append({"ticker": item.ticker, "error": "Ungültiger Typ. Erlaubt: core, satellite"})
        else:
            valid_items.append(item)

    # Batch-load all positions
    if valid_items:
        tickers = [item.ticker for item in valid_items]
        pos_result = await db.execute(
            select(Position).where(Position.ticker.in_(tickers), Position.is_active == True, Position.user_id == user.id)
        )
        pos_map = {pos.ticker: pos for pos in pos_result.scalars().all()}

        for item in valid_items:
            pos = pos_map.get(item.ticker)
            if not pos:
                errors.append({"ticker": item.ticker, "error": "Position not found"})
                continue
            pos.position_type = item.position_type
            results.append({"ticker": item.ticker, "position_type": item.position_type})

    await db.commit()
    if results:
        invalidate_portfolio_cache(str(user.id))
    return {"updated": results, "errors": errors}
