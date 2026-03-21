import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from api.portfolio import invalidate_portfolio_cache
from services.snapshot_trigger import trigger_snapshot_regen
from services.auth_service import encrypt_value, decrypt_value
from db import get_db
from models.position import AssetType, Position, PricingMode, PriceSource
from models.precious_metal_item import PreciousMetalItem, GRAMS_PER_TROY_OZ
from models.user import User

router = APIRouter(prefix="/api/precious-metals", tags=["precious-metals"])


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

# Metal type → ticker mapping
METAL_TICKERS = {
    "gold": "XAUCHF=X",
    "silver": "XAGCHF=X",
    "platinum": "XPTCHF=X",
    "palladium": "XPDCHF=X",
}

METAL_NAMES = {
    "gold": "Gold (physisch)",
    "silver": "Silber (physisch)",
    "platinum": "Platin (physisch)",
    "palladium": "Palladium (physisch)",
}


async def _sync_position(db: AsyncSession, user_id, metal_type: str):
    """Sync the commodity position for a metal type from precious_metal_items."""
    import logging
    logger = logging.getLogger(__name__)
    ticker = METAL_TICKERS.get(metal_type)
    if not ticker:
        return

    # Sum all unsold items for this metal
    result = await db.execute(
        select(
            func.coalesce(func.sum(PreciousMetalItem.weight_grams), 0),
            func.coalesce(func.sum(PreciousMetalItem.purchase_price_chf), 0),
            func.count(PreciousMetalItem.id),
        ).where(
            PreciousMetalItem.user_id == user_id,
            PreciousMetalItem.metal_type == metal_type,
            PreciousMetalItem.is_sold == False,
        )
    )
    total_grams, total_cost, item_count = result.one()
    total_oz = round(float(total_grams) / GRAMS_PER_TROY_OZ, 8)
    total_cost = round(float(total_cost), 2)

    # Find or create position
    pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.ticker == ticker,
        )
    )
    pos = pos_result.scalars().first()

    if item_count == 0 and pos:
        # No items left — deactivate position
        pos.shares = 0
        pos.cost_basis_chf = 0
        pos.is_active = False
    elif item_count > 0 and pos:
        # Update existing position
        old_shares = float(pos.shares)
        pos.shares = total_oz
        pos.cost_basis_chf = total_cost
        pos.is_active = True
        if old_shares != total_oz:
            logger.info(f"Metal sync {ticker}: shares {old_shares} -> {total_oz} ({item_count} items, {float(total_grams)}g)")
    elif item_count > 0 and not pos:
        # Create new position
        is_gold = metal_type == "gold"
        pos = Position(
            user_id=user_id,
            ticker=ticker,
            name=METAL_NAMES.get(metal_type, f"{metal_type.title()} (physisch)"),
            type=AssetType.commodity,
            sector="Commodities",
            currency="CHF",
            pricing_mode=PricingMode.auto,
            price_source=PriceSource.gold_org if is_gold else PriceSource.yahoo,
            gold_org=is_gold,
            shares=total_oz,
            cost_basis_chf=total_cost,
            risk_class=2,
        )
        db.add(pos)

    await db.flush()


class PreciousMetalCreate(BaseModel):
    metal_type: str  # gold, silver, platinum, palladium
    form: str  # bar, coin, other
    manufacturer: Optional[str] = None
    weight_grams: float
    serial_number: Optional[str] = None
    fineness: Optional[str] = None
    purchase_date: date
    purchase_price_chf: float
    storage_location: Optional[str] = None
    notes: Optional[str] = None


class PreciousMetalUpdate(BaseModel):
    metal_type: Optional[str] = None
    form: Optional[str] = None
    manufacturer: Optional[str] = None
    weight_grams: Optional[float] = None
    serial_number: Optional[str] = None
    fineness: Optional[str] = None
    purchase_date: Optional[date] = None
    purchase_price_chf: Optional[float] = None
    storage_location: Optional[str] = None
    notes: Optional[str] = None
    is_sold: Optional[bool] = None
    sold_date: Optional[date] = None
    sold_price_chf: Optional[float] = None


def _item_to_dict(item: PreciousMetalItem) -> dict:
    return {
        "id": str(item.id),
        "metal_type": item.metal_type,
        "form": item.form,
        "manufacturer": item.manufacturer,
        "weight_grams": float(item.weight_grams),
        "weight_oz": item.weight_oz,
        "serial_number": _decrypt_field(item.serial_number),
        "fineness": item.fineness,
        "purchase_date": item.purchase_date.isoformat(),
        "purchase_price_chf": float(item.purchase_price_chf),
        "storage_location": _decrypt_field(item.storage_location),
        "is_sold": item.is_sold,
        "sold_date": item.sold_date.isoformat() if item.sold_date else None,
        "sold_price_chf": float(item.sold_price_chf) if item.sold_price_chf else None,
        "notes": _decrypt_field(item.notes),
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
async def create_item(data: PreciousMetalCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Create a new precious metal item."""
    if data.metal_type not in ("gold", "silver", "platinum", "palladium"):
        raise HTTPException(422, "Ungültiger Metall-Typ")
    if data.form not in ("bar", "coin", "other"):
        raise HTTPException(422, "Ungültige Form")
    if data.weight_grams <= 0:
        raise HTTPException(422, "Gewicht muss positiv sein")

    item = PreciousMetalItem(
        user_id=user.id,
        metal_type=data.metal_type,
        form=data.form,
        manufacturer=data.manufacturer,
        weight_grams=data.weight_grams,
        serial_number=_encrypt_field(data.serial_number),
        fineness=data.fineness or "999.9",
        purchase_date=data.purchase_date,
        purchase_price_chf=data.purchase_price_chf,
        storage_location=_encrypt_field(data.storage_location),
        notes=_encrypt_field(data.notes),
    )
    db.add(item)
    await db.flush()
    await _sync_position(db, user.id, data.metal_type)
    await db.commit()
    await db.refresh(item)
    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user.id, data.purchase_date)
    return _item_to_dict(item)


@router.put("/{item_id}")
async def update_item(item_id: uuid.UUID, data: PreciousMetalUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Update a precious metal item."""
    item = await db.get(PreciousMetalItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Nicht gefunden")
    updates = data.model_dump(exclude_unset=True)
    # Encrypt PII fields before saving
    for field in ("serial_number", "storage_location", "notes"):
        if field in updates:
            updates[field] = _encrypt_field(updates[field]) if updates[field] else None
    for key, val in updates.items():
        setattr(item, key, val)
    await db.flush()
    await _sync_position(db, user.id, item.metal_type)
    await db.commit()
    await db.refresh(item)
    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user.id, item.purchase_date)
    return _item_to_dict(item)


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Delete a precious metal item."""
    item = await db.get(PreciousMetalItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Nicht gefunden")
    metal_type = item.metal_type
    await db.delete(item)
    await db.flush()
    await _sync_position(db, user.id, metal_type)
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
