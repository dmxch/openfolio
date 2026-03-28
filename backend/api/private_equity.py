"""Private Equity / Direktbeteiligungen API routes."""

import logging
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import get_current_user, limiter
from api.portfolio import invalidate_portfolio_cache
from db import get_db
from models.private_equity import PrivateEquityHolding, PrivateEquityValuation, PrivateEquityDividend
from models.user import User
from services.encryption_helpers import encrypt_field
from services.private_equity_service import (
    get_holdings_summary,
    get_holding_detail,
    sync_position,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/private-equity", tags=["private-equity"])

MAX_HOLDINGS_PER_USER = 20
MAX_VALUATIONS_PER_HOLDING = 50
MAX_DIVIDENDS_PER_HOLDING = 50


# --- Pydantic Models ---

class HoldingCreate(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    num_shares: int = Field(..., gt=0)
    nominal_value: float = Field(..., ge=0)
    purchase_price_per_share: Optional[float] = Field(None, ge=0)
    purchase_date: Optional[date] = None
    currency: str = Field("CHF", max_length=3)
    uid_number: Optional[str] = Field(None, max_length=50)
    register_nr: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = Field(None, max_length=1000)


class HoldingUpdate(BaseModel):
    company_name: Optional[str] = Field(None, min_length=1, max_length=200)
    num_shares: Optional[int] = Field(None, gt=0)
    nominal_value: Optional[float] = Field(None, ge=0)
    purchase_price_per_share: Optional[float] = Field(None, ge=0)
    purchase_date: Optional[date] = None
    currency: Optional[str] = Field(None, max_length=3)
    uid_number: Optional[str] = Field(None, max_length=50)
    register_nr: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = Field(None, max_length=1000)


class ValuationCreate(BaseModel):
    valuation_date: date
    gross_value_per_share: float = Field(..., ge=0)
    discount_pct: float = Field(30.0, ge=0, le=100)
    source: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=500)


class ValuationUpdate(BaseModel):
    valuation_date: Optional[date] = None
    gross_value_per_share: Optional[float] = Field(None, ge=0)
    discount_pct: Optional[float] = Field(None, ge=0, le=100)
    source: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=500)


class DividendCreate(BaseModel):
    payment_date: date
    dividend_per_share: float = Field(..., ge=0)
    withholding_tax_pct: float = Field(35.0, ge=0, le=100)
    fiscal_year: int = Field(..., ge=1900, le=2100)
    notes: Optional[str] = Field(None, max_length=500)


class DividendUpdate(BaseModel):
    payment_date: Optional[date] = None
    dividend_per_share: Optional[float] = Field(None, ge=0)
    withholding_tax_pct: Optional[float] = Field(None, ge=0, le=100)
    fiscal_year: Optional[int] = Field(None, ge=1900, le=2100)
    notes: Optional[str] = Field(None, max_length=500)


# --- Helpers ---

async def _get_holding(db: AsyncSession, user_id: UUID, holding_id: UUID) -> PrivateEquityHolding:
    """Load holding with children, raise 404 if not found or wrong user."""
    result = await db.execute(
        select(PrivateEquityHolding)
        .options(selectinload(PrivateEquityHolding.valuations), selectinload(PrivateEquityHolding.dividends))
        .where(PrivateEquityHolding.id == holding_id, PrivateEquityHolding.user_id == user_id)
    )
    h = result.scalars().first()
    if not h:
        raise HTTPException(404, "Beteiligung nicht gefunden")
    return h


# --- Holdings CRUD ---

@router.get("")
async def list_holdings(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """List all active PE holdings with summary data."""
    return await get_holdings_summary(db, user.id)


@router.post("", status_code=201)
@limiter.limit("30/minute")
async def create_holding(request: Request, data: HoldingCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Create a new PE holding."""
    # Per-user limit
    from sqlalchemy import func
    count_result = await db.execute(
        select(func.count()).select_from(PrivateEquityHolding).where(
            PrivateEquityHolding.user_id == user.id, PrivateEquityHolding.is_active == True
        )
    )
    if (count_result.scalar() or 0) >= MAX_HOLDINGS_PER_USER:
        raise HTTPException(400, f"Maximal {MAX_HOLDINGS_PER_USER} Beteiligungen erlaubt")

    holding = PrivateEquityHolding(
        user_id=user.id,
        company_name=encrypt_field(data.company_name),
        num_shares=data.num_shares,
        nominal_value=data.nominal_value,
        purchase_price_per_share=data.purchase_price_per_share,
        purchase_date=data.purchase_date,
        currency=data.currency,
        uid_number=encrypt_field(data.uid_number),
        register_nr=encrypt_field(data.register_nr),
        notes=encrypt_field(data.notes),
    )
    db.add(holding)
    await db.flush()

    await sync_position(db, user.id, holding)
    await db.commit()

    invalidate_portfolio_cache(str(user.id))

    return await get_holding_detail(db, user.id, holding.id)


@router.get("/{holding_id}")
async def get_holding(holding_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Get single holding with full valuation and dividend history."""
    detail = await get_holding_detail(db, user.id, holding_id)
    if not detail:
        raise HTTPException(404, "Beteiligung nicht gefunden")
    return detail


@router.put("/{holding_id}")
@limiter.limit("30/minute")
async def update_holding(request: Request, holding_id: UUID, data: HoldingUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Update a PE holding."""
    h = await _get_holding(db, user.id, holding_id)

    if data.company_name is not None:
        h.company_name = encrypt_field(data.company_name)
    if data.num_shares is not None:
        h.num_shares = data.num_shares
    if data.nominal_value is not None:
        h.nominal_value = data.nominal_value
    if data.purchase_price_per_share is not None:
        h.purchase_price_per_share = data.purchase_price_per_share
    if data.purchase_date is not None:
        h.purchase_date = data.purchase_date
    if data.currency is not None:
        h.currency = data.currency
    if data.uid_number is not None:
        h.uid_number = encrypt_field(data.uid_number)
    if data.register_nr is not None:
        h.register_nr = encrypt_field(data.register_nr)
    if data.notes is not None:
        h.notes = encrypt_field(data.notes)

    await sync_position(db, user.id, h)
    await db.commit()

    invalidate_portfolio_cache(str(user.id))

    return await get_holding_detail(db, user.id, holding_id)


@router.delete("/{holding_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_holding(request: Request, holding_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Delete a PE holding (CASCADE to valuations and dividends)."""
    h = await _get_holding(db, user.id, holding_id)
    h.is_active = False
    await sync_position(db, user.id, h)

    await db.delete(h)
    await db.commit()

    invalidate_portfolio_cache(str(user.id))


# --- Valuations CRUD ---

@router.post("/{holding_id}/valuations", status_code=201)
@limiter.limit("30/minute")
async def create_valuation(request: Request, holding_id: UUID, data: ValuationCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Add a valuation to a PE holding."""
    h = await _get_holding(db, user.id, holding_id)

    if len(h.valuations) >= MAX_VALUATIONS_PER_HOLDING:
        raise HTTPException(400, f"Maximal {MAX_VALUATIONS_PER_HOLDING} Bewertungen pro Beteiligung erlaubt")

    net_value = round(data.gross_value_per_share * (1 - data.discount_pct / 100), 2)

    v = PrivateEquityValuation(
        holding_id=h.id,
        valuation_date=data.valuation_date,
        gross_value_per_share=data.gross_value_per_share,
        discount_pct=data.discount_pct,
        net_value_per_share=net_value,
        source=data.source,
        notes=encrypt_field(data.notes),
    )
    db.add(v)
    await db.flush()

    # Re-load to get updated valuation list for position sync
    h = await _get_holding(db, user.id, holding_id)
    await sync_position(db, user.id, h)
    await db.commit()

    invalidate_portfolio_cache(str(user.id))

    return await get_holding_detail(db, user.id, holding_id)


@router.put("/{holding_id}/valuations/{valuation_id}")
@limiter.limit("30/minute")
async def update_valuation(request: Request, holding_id: UUID, valuation_id: UUID, data: ValuationUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Update a valuation."""
    h = await _get_holding(db, user.id, holding_id)

    v = next((v for v in h.valuations if v.id == valuation_id), None)
    if not v:
        raise HTTPException(404, "Bewertung nicht gefunden")

    if data.valuation_date is not None:
        v.valuation_date = data.valuation_date
    if data.gross_value_per_share is not None:
        v.gross_value_per_share = data.gross_value_per_share
    if data.discount_pct is not None:
        v.discount_pct = data.discount_pct
    if data.source is not None:
        v.source = data.source
    if data.notes is not None:
        v.notes = encrypt_field(data.notes)

    # Recalculate net value
    v.net_value_per_share = round(float(v.gross_value_per_share) * (1 - float(v.discount_pct) / 100), 2)

    h = await _get_holding(db, user.id, holding_id)
    await sync_position(db, user.id, h)
    await db.commit()

    invalidate_portfolio_cache(str(user.id))

    return await get_holding_detail(db, user.id, holding_id)


@router.delete("/{holding_id}/valuations/{valuation_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_valuation(request: Request, holding_id: UUID, valuation_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Delete a valuation."""
    h = await _get_holding(db, user.id, holding_id)

    v = next((v for v in h.valuations if v.id == valuation_id), None)
    if not v:
        raise HTTPException(404, "Bewertung nicht gefunden")

    await db.delete(v)
    await db.flush()

    h = await _get_holding(db, user.id, holding_id)
    await sync_position(db, user.id, h)
    await db.commit()

    invalidate_portfolio_cache(str(user.id))


# --- Dividends CRUD ---

@router.post("/{holding_id}/dividends", status_code=201)
@limiter.limit("30/minute")
async def create_dividend(request: Request, holding_id: UUID, data: DividendCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Add a dividend to a PE holding."""
    h = await _get_holding(db, user.id, holding_id)

    if len(h.dividends) >= MAX_DIVIDENDS_PER_HOLDING:
        raise HTTPException(400, f"Maximal {MAX_DIVIDENDS_PER_HOLDING} Dividenden pro Beteiligung erlaubt")

    gross_amount = round(data.dividend_per_share * h.num_shares, 2)
    wht_amount = round(gross_amount * data.withholding_tax_pct / 100, 2)
    net_amount = round(gross_amount - wht_amount, 2)

    d = PrivateEquityDividend(
        holding_id=h.id,
        payment_date=data.payment_date,
        dividend_per_share=data.dividend_per_share,
        gross_amount=gross_amount,
        withholding_tax_pct=data.withholding_tax_pct,
        withholding_tax_amount=wht_amount,
        net_amount=net_amount,
        fiscal_year=data.fiscal_year,
        notes=encrypt_field(data.notes),
    )
    db.add(d)
    await db.commit()

    invalidate_portfolio_cache(str(user.id))

    return await get_holding_detail(db, user.id, holding_id)


@router.put("/{holding_id}/dividends/{dividend_id}")
@limiter.limit("30/minute")
async def update_dividend(request: Request, holding_id: UUID, dividend_id: UUID, data: DividendUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Update a dividend."""
    h = await _get_holding(db, user.id, holding_id)

    d = next((d for d in h.dividends if d.id == dividend_id), None)
    if not d:
        raise HTTPException(404, "Dividende nicht gefunden")

    if data.payment_date is not None:
        d.payment_date = data.payment_date
    if data.dividend_per_share is not None:
        d.dividend_per_share = data.dividend_per_share
    if data.withholding_tax_pct is not None:
        d.withholding_tax_pct = data.withholding_tax_pct
    if data.fiscal_year is not None:
        d.fiscal_year = data.fiscal_year
    if data.notes is not None:
        d.notes = encrypt_field(data.notes)

    # Recalculate amounts
    d.gross_amount = round(float(d.dividend_per_share) * h.num_shares, 2)
    d.withholding_tax_amount = round(float(d.gross_amount) * float(d.withholding_tax_pct) / 100, 2)
    d.net_amount = round(float(d.gross_amount) - float(d.withholding_tax_amount), 2)

    await db.commit()

    invalidate_portfolio_cache(str(user.id))

    return await get_holding_detail(db, user.id, holding_id)


@router.delete("/{holding_id}/dividends/{dividend_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_dividend(request: Request, holding_id: UUID, dividend_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Delete a dividend."""
    h = await _get_holding(db, user.id, holding_id)

    d = next((d for d in h.dividends if d.id == dividend_id), None)
    if not d:
        raise HTTPException(404, "Dividende nicht gefunden")

    await db.delete(d)
    await db.commit()

    invalidate_portfolio_cache(str(user.id))
