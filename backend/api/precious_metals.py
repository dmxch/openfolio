import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from api.portfolio import invalidate_portfolio_cache
from constants.limits import MAX_PRECIOUS_METAL_ITEMS_PER_USER
from services.snapshot_trigger import trigger_snapshot_regen
from services.encryption_helpers import encrypt_field, decrypt_field
from services.precious_metals_service import sync_metal_position, METAL_TICKERS, METAL_NAMES
from db import get_db
from models.precious_metal_item import PreciousMetalItem
from models.user import User

router = APIRouter(prefix="/api/precious-metals", tags=["precious-metals"])


class PreciousMetalCreate(BaseModel):
    metal_type: str = Field(min_length=1, max_length=20)
    form: str = Field(min_length=1, max_length=20)
    manufacturer: Optional[str] = Field(default=None, max_length=200)
    weight_grams: float = Field(gt=0)
    serial_number: Optional[str] = Field(default=None, max_length=100)
    fineness: Optional[str] = Field(default=None, max_length=10)
    purchase_date: date
    purchase_price_chf: float = Field(ge=0)
    storage_location: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)


class PreciousMetalUpdate(BaseModel):
    metal_type: Optional[str] = Field(default=None, max_length=20)
    form: Optional[str] = Field(default=None, max_length=20)
    manufacturer: Optional[str] = Field(default=None, max_length=200)
    weight_grams: Optional[float] = Field(default=None, gt=0)
    serial_number: Optional[str] = Field(default=None, max_length=100)
    fineness: Optional[str] = Field(default=None, max_length=10)
    purchase_date: Optional[date] = None
    purchase_price_chf: Optional[float] = Field(default=None, ge=0)
    storage_location: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)
    is_sold: Optional[bool] = None
    sold_date: Optional[date] = None
    sold_price_chf: Optional[float] = Field(default=None, ge=0)


def _item_to_dict(item: PreciousMetalItem) -> dict:
    return {
        "id": str(item.id),
        "metal_type": item.metal_type,
        "form": item.form,
        "manufacturer": item.manufacturer,
        "weight_grams": float(item.weight_grams),
        "weight_oz": item.weight_oz,
        "serial_number": decrypt_field(item.serial_number),
        "fineness": item.fineness,
        "purchase_date": item.purchase_date.isoformat(),
        "purchase_price_chf": float(item.purchase_price_chf),
        "storage_location": decrypt_field(item.storage_location),
        "is_sold": item.is_sold,
        "sold_date": item.sold_date.isoformat() if item.sold_date else None,
        "sold_price_chf": float(item.sold_price_chf) if item.sold_price_chf else None,
        "notes": decrypt_field(item.notes),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("")
async def list_items(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """List all precious metal items grouped by metal type."""
    result = await db.execute(
        select(PreciousMetalItem)
        .where(PreciousMetalItem.user_id == user.id, PreciousMetalItem.is_sold == False)
        .order_by(PreciousMetalItem.metal_type, PreciousMetalItem.purchase_date)
    )
    items = result.scalars().all()

    # Group by metal_type
    groups = {}
    for item in items:
        mt = item.metal_type
        if mt not in groups:
            groups[mt] = {
                "metal_type": mt,
                "total_weight_grams": 0,
                "total_weight_oz": 0,
                "total_cost_chf": 0,
                "item_count": 0,
                "items": [],
            }
        groups[mt]["total_weight_grams"] += float(item.weight_grams)
        groups[mt]["total_weight_oz"] += item.weight_oz
        groups[mt]["total_cost_chf"] += float(item.purchase_price_chf)
        groups[mt]["item_count"] += 1
        groups[mt]["items"].append(_item_to_dict(item))

    # Round totals
    for g in groups.values():
        g["total_weight_grams"] = round(g["total_weight_grams"], 4)
        g["total_weight_oz"] = round(g["total_weight_oz"], 4)
        g["total_cost_chf"] = round(g["total_cost_chf"], 2)

    return {"groups": list(groups.values())}


@router.post("", status_code=201)
@limiter.limit("30/minute")
async def create_item(request: Request, data: PreciousMetalCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Create a new precious metal item."""
    if data.metal_type not in ("gold", "silver", "platinum", "palladium"):
        raise HTTPException(422, "Ungültiger Metall-Typ")
    if data.form not in ("bar", "coin", "other"):
        raise HTTPException(422, "Ungültige Form")
    if data.weight_grams <= 0:
        raise HTTPException(422, "Gewicht muss positiv sein")

    # Per-user limit
    count_result = await db.execute(
        select(func.count()).select_from(PreciousMetalItem).where(PreciousMetalItem.user_id == user.id)
    )
    if (count_result.scalar() or 0) >= MAX_PRECIOUS_METAL_ITEMS_PER_USER:
        raise HTTPException(400, f"Limit erreicht (max. {MAX_PRECIOUS_METAL_ITEMS_PER_USER} Edelmetall-Einträge)")

    item = PreciousMetalItem(
        user_id=user.id,
        metal_type=data.metal_type,
        form=data.form,
        manufacturer=data.manufacturer,
        weight_grams=data.weight_grams,
        serial_number=encrypt_field(data.serial_number),
        fineness=data.fineness or "999.9",
        purchase_date=data.purchase_date,
        purchase_price_chf=data.purchase_price_chf,
        storage_location=encrypt_field(data.storage_location),
        notes=encrypt_field(data.notes),
    )
    db.add(item)
    await db.flush()
    await sync_metal_position(db, user.id, data.metal_type)
    await db.commit()
    await db.refresh(item)
    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user.id, data.purchase_date)
    return _item_to_dict(item)


@router.put("/{item_id}")
@limiter.limit("30/minute")
async def update_item(request: Request, item_id: uuid.UUID, data: PreciousMetalUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Update a precious metal item."""
    item = await db.get(PreciousMetalItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Nicht gefunden")
    updates = data.model_dump(exclude_unset=True)
    # Encrypt PII fields before saving
    for field in ("serial_number", "storage_location", "notes"):
        if field in updates:
            updates[field] = encrypt_field(updates[field]) if updates[field] else None
    for key, val in updates.items():
        setattr(item, key, val)
    await db.flush()
    await sync_metal_position(db, user.id, item.metal_type)
    await db.commit()
    await db.refresh(item)
    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user.id, item.purchase_date)
    return _item_to_dict(item)


@router.delete("/{item_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_item(request: Request, item_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Delete a precious metal item."""
    item = await db.get(PreciousMetalItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Nicht gefunden")
    metal_type = item.metal_type
    await db.delete(item)
    await db.flush()
    await sync_metal_position(db, user.id, metal_type)
    await db.commit()
    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user.id, item.purchase_date)


@router.get("/sold")
async def list_sold(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """List sold precious metal items."""
    result = await db.execute(
        select(PreciousMetalItem)
        .where(PreciousMetalItem.user_id == user.id, PreciousMetalItem.is_sold == True)
        .order_by(PreciousMetalItem.sold_date.desc())
    )
    return [_item_to_dict(i) for i in result.scalars().all()]
