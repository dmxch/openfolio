import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.property import (
    Mortgage,
    PropertyType, MortgageType, ExpenseCategory, Frequency,
)
from models.user import User
from services.property_service import (
    get_properties_summary, get_property_detail,
    create_property as svc_create_property,
    update_property as svc_update_property,
    delete_property as svc_delete_property,
    create_mortgage as svc_create_mortgage,
    update_mortgage as svc_update_mortgage,
    delete_mortgage as svc_delete_mortgage,
    create_expense as svc_create_expense,
    update_expense as svc_update_expense,
    delete_expense as svc_delete_expense,
    create_income as svc_create_income,
    update_income as svc_update_income,
    delete_income as svc_delete_income,
    _verify_property_owner,
    _mortgage_to_dict,
)

router = APIRouter(prefix="/api/properties", tags=["real_estate"])


# --- Pydantic schemas ---

class PropertyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: Optional[str] = Field(default=None, max_length=500)
    property_type: PropertyType
    purchase_date: Optional[date] = None
    purchase_price: float = Field(ge=0)
    estimated_value: Optional[float] = Field(default=None, ge=0)
    estimated_value_date: Optional[date] = None
    land_area_m2: Optional[float] = Field(default=None, ge=0)
    living_area_m2: Optional[float] = Field(default=None, ge=0)
    rooms: Optional[float] = Field(default=None, ge=0, le=100)
    year_built: Optional[int] = Field(default=None, ge=1800, le=2100)
    canton: Optional[str] = Field(default=None, max_length=2)
    notes: Optional[str] = Field(default=None, max_length=2000)


class PropertyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    address: Optional[str] = Field(default=None, max_length=500)
    property_type: Optional[PropertyType] = None
    purchase_date: Optional[date] = None
    purchase_price: Optional[float] = Field(default=None, ge=0)
    estimated_value: Optional[float] = Field(default=None, ge=0)
    estimated_value_date: Optional[date] = None
    land_area_m2: Optional[float] = Field(default=None, ge=0)
    living_area_m2: Optional[float] = Field(default=None, ge=0)
    rooms: Optional[float] = Field(default=None, ge=0, le=100)
    year_built: Optional[int] = Field(default=None, ge=1800, le=2100)
    canton: Optional[str] = Field(default=None, max_length=2)
    notes: Optional[str] = Field(default=None, max_length=2000)


class MortgageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: MortgageType
    amount: float = Field(gt=0)
    interest_rate: float = Field(ge=0, le=100)
    margin_rate: Optional[float] = Field(default=None, ge=0, le=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    monthly_payment: Optional[float] = Field(default=None, ge=0)
    annual_payment: Optional[float] = Field(default=None, ge=0)
    amortization_monthly: Optional[float] = Field(default=None, ge=0)
    amortization_annual: Optional[float] = Field(default=None, ge=0)
    bank: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)


class MortgageUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    type: Optional[MortgageType] = None
    amount: Optional[float] = Field(default=None, gt=0)
    interest_rate: Optional[float] = Field(default=None, ge=0, le=100)
    margin_rate: Optional[float] = Field(default=None, ge=0, le=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    monthly_payment: Optional[float] = Field(default=None, ge=0)
    annual_payment: Optional[float] = Field(default=None, ge=0)
    amortization_monthly: Optional[float] = Field(default=None, ge=0)
    amortization_annual: Optional[float] = Field(default=None, ge=0)
    bank: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ExpenseCreate(BaseModel):
    date: date
    category: ExpenseCategory
    description: Optional[str] = Field(default=None, max_length=500)
    amount: float = Field(gt=0)
    recurring: bool = False
    frequency: Optional[Frequency] = None


class ExpenseUpdate(BaseModel):
    date: Optional[date] = None
    category: Optional[ExpenseCategory] = None
    description: Optional[str] = Field(default=None, max_length=500)
    amount: Optional[float] = Field(default=None, gt=0)
    recurring: Optional[bool] = None
    frequency: Optional[Frequency] = None


class IncomeCreate(BaseModel):
    date: date
    description: Optional[str] = Field(default=None, max_length=500)
    amount: float = Field(gt=0)
    tenant: Optional[str] = Field(default=None, max_length=200)
    recurring: bool = False
    frequency: Optional[Frequency] = None


class IncomeUpdate(BaseModel):
    date: Optional[date] = None
    description: Optional[str] = Field(default=None, max_length=500)
    amount: Optional[float] = Field(default=None, gt=0)
    tenant: Optional[str] = Field(default=None, max_length=200)
    recurring: Optional[bool] = None
    frequency: Optional[Frequency] = None


# --- Property endpoints ---

@router.get("")
async def list_properties(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await get_properties_summary(db, user.id)


@router.get("/{property_id}")
async def get_property(property_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await get_property_detail(db, property_id, user.id)
    if not result:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden")
    return result


@router.post("", status_code=201)
@limiter.limit("30/minute")
async def create_property(request: Request, data: PropertyCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await svc_create_property(db, user.id, data.model_dump())


@router.put("/{property_id}")
@limiter.limit("30/minute")
async def update_property(request: Request, property_id: uuid.UUID, data: PropertyUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await svc_update_property(db, user.id, property_id, data.model_dump(exclude_unset=True))


@router.delete("/{property_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_property(request: Request, property_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await svc_delete_property(db, user.id, property_id)


# --- Mortgage endpoints ---

@router.get("/{property_id}/mortgages")
async def list_mortgages(property_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _verify_property_owner(db, property_id, user.id)
    result = await db.execute(
        select(Mortgage).where(Mortgage.property_id == property_id, Mortgage.is_active == True)
    )
    mortgages = result.scalars().all()
    return [_mortgage_to_dict(m) for m in mortgages]


@router.post("/{property_id}/mortgages", status_code=201)
@limiter.limit("30/minute")
async def create_mortgage(request: Request, property_id: uuid.UUID, data: MortgageCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await svc_create_mortgage(db, user.id, property_id, data.model_dump())


@router.put("/mortgages/{mortgage_id}")
@limiter.limit("30/minute")
async def update_mortgage(request: Request, mortgage_id: uuid.UUID, data: MortgageUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await svc_update_mortgage(db, user.id, uuid.UUID(int=0), mortgage_id, data.model_dump(exclude_unset=True))


@router.delete("/mortgages/{mortgage_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_mortgage(request: Request, mortgage_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await svc_delete_mortgage(db, user.id, uuid.UUID(int=0), mortgage_id)


# --- Expense endpoints ---

@router.post("/{property_id}/expenses", status_code=201)
@limiter.limit("30/minute")
async def create_expense(request: Request, property_id: uuid.UUID, data: ExpenseCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await svc_create_expense(db, user.id, property_id, data.model_dump())


@router.put("/expenses/{expense_id}")
@limiter.limit("30/minute")
async def update_expense(request: Request, expense_id: uuid.UUID, data: ExpenseUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await svc_update_expense(db, user.id, uuid.UUID(int=0), expense_id, data.model_dump(exclude_unset=True))


@router.delete("/expenses/{expense_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_expense(request: Request, expense_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await svc_delete_expense(db, user.id, uuid.UUID(int=0), expense_id)


# --- Income endpoints ---

@router.post("/{property_id}/income", status_code=201)
@limiter.limit("30/minute")
async def create_income(request: Request, property_id: uuid.UUID, data: IncomeCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await svc_create_income(db, user.id, property_id, data.model_dump())


@router.put("/income/{income_id}")
@limiter.limit("30/minute")
async def update_income(request: Request, income_id: uuid.UUID, data: IncomeUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await svc_update_income(db, user.id, uuid.UUID(int=0), income_id, data.model_dump(exclude_unset=True))


@router.delete("/income/{income_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_income(request: Request, income_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await svc_delete_income(db, user.id, uuid.UUID(int=0), income_id)
