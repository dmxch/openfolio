import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.property import (
    Property, Mortgage, PropertyExpense, PropertyIncome,
    PropertyType, MortgageType, ExpenseCategory, Frequency,
)
from models.user import User
from services.auth_service import encrypt_value, decrypt_value
from services.property_service import get_properties_summary, get_property_detail

router = APIRouter(prefix="/api/properties", tags=["real_estate"])


def _encrypt_field(value):
    if not value:
        return value
    return encrypt_value(value)


def _decrypt_field(value):
    if not value:
        return value
    try:
        return decrypt_value(value)
    except Exception:
        return value  # Legacy plaintext


async def _verify_property_owner(db: AsyncSession, property_id: uuid.UUID, user_id: uuid.UUID) -> Property:
    """Verify a property exists and belongs to the user. Returns the property or raises 404."""
    result = await db.execute(
        select(Property).where(Property.id == property_id, Property.user_id == user_id)
    )
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden")
    return prop


# --- Pydantic schemas ---

class PropertyCreate(BaseModel):
    name: str
    address: Optional[str] = None
    property_type: PropertyType
    purchase_date: Optional[date] = None
    purchase_price: float
    estimated_value: Optional[float] = None
    estimated_value_date: Optional[date] = None
    land_area_m2: Optional[float] = None
    living_area_m2: Optional[float] = None
    rooms: Optional[float] = None
    year_built: Optional[int] = None
    canton: Optional[str] = None
    notes: Optional[str] = None


class PropertyUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    property_type: Optional[PropertyType] = None
    purchase_date: Optional[date] = None
    purchase_price: Optional[float] = None
    estimated_value: Optional[float] = None
    estimated_value_date: Optional[date] = None
    land_area_m2: Optional[float] = None
    living_area_m2: Optional[float] = None
    rooms: Optional[float] = None
    year_built: Optional[int] = None
    canton: Optional[str] = None
    notes: Optional[str] = None


class MortgageCreate(BaseModel):
    name: str
    type: MortgageType
    amount: float
    interest_rate: float
    margin_rate: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    monthly_payment: Optional[float] = None
    annual_payment: Optional[float] = None
    amortization_monthly: Optional[float] = None
    amortization_annual: Optional[float] = None
    bank: Optional[str] = None
    notes: Optional[str] = None


class MortgageUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[MortgageType] = None
    amount: Optional[float] = None
    interest_rate: Optional[float] = None
    margin_rate: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    monthly_payment: Optional[float] = None
    annual_payment: Optional[float] = None
    amortization_monthly: Optional[float] = None
    amortization_annual: Optional[float] = None
    bank: Optional[str] = None
    notes: Optional[str] = None


class ExpenseCreate(BaseModel):
    date: date
    category: ExpenseCategory
    description: Optional[str] = None
    amount: float
    recurring: bool = False
    frequency: Optional[Frequency] = None


class ExpenseUpdate(BaseModel):
    date: Optional[date] = None
    category: Optional[ExpenseCategory] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    recurring: Optional[bool] = None
    frequency: Optional[Frequency] = None


class IncomeCreate(BaseModel):
    date: date
    description: Optional[str] = None
    amount: float
    tenant: Optional[str] = None
    recurring: bool = False
    frequency: Optional[Frequency] = None


class IncomeUpdate(BaseModel):
    date: Optional[date] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    tenant: Optional[str] = None
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
async def create_property(data: PropertyCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    dump = data.model_dump()
    # Encrypt PII fields before saving
    for field in ("name", "address", "notes"):
        if dump.get(field):
            dump[field] = _encrypt_field(dump[field])
    prop = Property(**dump, user_id=user.id)
    db.add(prop)
    await db.commit()
    await db.refresh(prop)
    return {"id": str(prop.id), "name": _decrypt_field(prop.name)}


@router.put("/{property_id}")
async def update_property(property_id: uuid.UUID, data: PropertyUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    prop = await _verify_property_owner(db, property_id, user.id)
    updates = data.model_dump(exclude_unset=True)
    # Encrypt PII fields before saving
    for field in ("name", "address", "notes"):
        if field in updates:
            updates[field] = _encrypt_field(updates[field]) if updates[field] else None
    for key, value in updates.items():
        setattr(prop, key, value)
    await db.commit()
    return {"id": str(prop.id), "name": _decrypt_field(prop.name)}


@router.delete("/{property_id}", status_code=204)
async def delete_property(property_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    prop = await _verify_property_owner(db, property_id, user.id)
    await db.delete(prop)
    await db.commit()


# --- Mortgage endpoints ---

@router.get("/{property_id}/mortgages")
async def list_mortgages(property_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _verify_property_owner(db, property_id, user.id)
    result = await db.execute(
        select(Mortgage).where(Mortgage.property_id == property_id, Mortgage.is_active == True)
    )
    mortgages = result.scalars().all()
    from services.property_service import _mortgage_to_dict
    return [_mortgage_to_dict(m) for m in mortgages]


@router.post("/{property_id}/mortgages", status_code=201)
async def create_mortgage(property_id: uuid.UUID, data: MortgageCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _verify_property_owner(db, property_id, user.id)
    mortgage = Mortgage(property_id=property_id, **data.model_dump())
    db.add(mortgage)
    await db.commit()
    await db.refresh(mortgage)
    return {"id": str(mortgage.id), "name": mortgage.name}


@router.put("/mortgages/{mortgage_id}")
async def update_mortgage(mortgage_id: uuid.UUID, data: MortgageUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Mortgage).where(Mortgage.id == mortgage_id))
    mortgage = result.scalar_one_or_none()
    if not mortgage:
        raise HTTPException(status_code=404, detail="Hypothek nicht gefunden")
    await _verify_property_owner(db, mortgage.property_id, user.id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(mortgage, key, value)
    await db.commit()
    return {"id": str(mortgage.id), "name": mortgage.name}


@router.delete("/mortgages/{mortgage_id}", status_code=204)
async def delete_mortgage(mortgage_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Mortgage).where(Mortgage.id == mortgage_id))
    mortgage = result.scalar_one_or_none()
    if not mortgage:
        raise HTTPException(status_code=404, detail="Hypothek nicht gefunden")
    await _verify_property_owner(db, mortgage.property_id, user.id)
    await db.delete(mortgage)
    await db.commit()


# --- Expense endpoints ---

@router.post("/{property_id}/expenses", status_code=201)
async def create_expense(property_id: uuid.UUID, data: ExpenseCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _verify_property_owner(db, property_id, user.id)
    expense = PropertyExpense(property_id=property_id, **data.model_dump())
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return {"id": str(expense.id)}


@router.put("/expenses/{expense_id}")
async def update_expense(expense_id: uuid.UUID, data: ExpenseUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(PropertyExpense).where(PropertyExpense.id == expense_id))
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Ausgabe nicht gefunden")
    await _verify_property_owner(db, expense.property_id, user.id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(expense, key, value)
    await db.commit()
    return {"id": str(expense.id)}


@router.delete("/expenses/{expense_id}", status_code=204)
async def delete_expense(expense_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(PropertyExpense).where(PropertyExpense.id == expense_id))
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Ausgabe nicht gefunden")
    await _verify_property_owner(db, expense.property_id, user.id)
    await db.delete(expense)
    await db.commit()


# --- Income endpoints ---

@router.post("/{property_id}/income", status_code=201)
async def create_income(property_id: uuid.UUID, data: IncomeCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _verify_property_owner(db, property_id, user.id)
    income = PropertyIncome(property_id=property_id, **data.model_dump())
    db.add(income)
    await db.commit()
    await db.refresh(income)
    return {"id": str(income.id)}


@router.put("/income/{income_id}")
async def update_income(income_id: uuid.UUID, data: IncomeUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(PropertyIncome).where(PropertyIncome.id == income_id))
    income = result.scalar_one_or_none()
    if not income:
        raise HTTPException(status_code=404, detail="Einnahme nicht gefunden")
    await _verify_property_owner(db, income.property_id, user.id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(income, key, value)
    await db.commit()
    return {"id": str(income.id)}


@router.delete("/income/{income_id}", status_code=204)
async def delete_income(income_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(PropertyIncome).where(PropertyIncome.id == income_id))
    income = result.scalar_one_or_none()
    if not income:
        raise HTTPException(status_code=404, detail="Einnahme nicht gefunden")
    await _verify_property_owner(db, income.property_id, user.id)
    await db.delete(income)
    await db.commit()
