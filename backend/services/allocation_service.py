"""Core/Satellite allocation calculation service."""

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import Position
from services.utils import get_fx_rates_batch

logger = logging.getLogger(__name__)

# Only include tradable types for core/satellite
TRADABLE_TYPES = {"stock", "etf"}
# Exclude types from liquid view
EXCLUDE_LIQUID = {"pension", "real_estate", "private_equity"}


async def get_core_satellite_allocation(
    db: AsyncSession, user_id: UUID, view: str = "liquid"
) -> dict:
    """Return core/satellite/unassigned allocation breakdown.

    Args:
        db: Async database session.
        user_id: The current user's ID.
        view: 'liquid' excludes pension/real_estate/private_equity.

    Returns:
        Dict with core, satellite, and unassigned breakdowns.
    """
    result = await db.execute(
        select(Position).where(Position.is_active == True, Position.user_id == user_id)
    )
    positions = result.scalars().all()

    fx_rates = await asyncio.to_thread(get_fx_rates_batch)

    core: dict = {"value_chf": 0, "positions": []}
    satellite: dict = {"value_chf": 0, "positions": []}
    unassigned: dict = {"value_chf": 0, "positions": []}

    for pos in positions:
        if float(pos.shares) <= 0:
            continue
        if view == "liquid" and pos.type.value in EXCLUDE_LIQUID:
            continue
        if pos.type.value not in TRADABLE_TYPES:
            continue

        # Use current_price from DB (updated by cache refresh) — no blocking API calls
        shares = float(pos.shares)
        price = float(pos.current_price) if pos.current_price else 0
        if price > 0:
            fx = fx_rates.get(pos.currency, 1.0) if pos.currency != "CHF" else 1.0
            value_chf = round(price * shares * fx, 2)
        else:
            value_chf = round(float(pos.cost_basis_chf), 2)

        pos_info = {
            "ticker": pos.ticker,
            "name": pos.name,
            "value_chf": value_chf,
            "type": pos.type.value,
            "position_type": pos.position_type,
        }

        if pos.position_type == "core":
            core["value_chf"] += value_chf
            core["positions"].append(pos_info)
        elif pos.position_type == "satellite":
            satellite["value_chf"] += value_chf
            satellite["positions"].append(pos_info)
        else:
            unassigned["value_chf"] += value_chf
            unassigned["positions"].append(pos_info)

    total = core["value_chf"] + satellite["value_chf"] + unassigned["value_chf"]
    core["pct"] = round(core["value_chf"] / total * 100, 1) if total > 0 else 0
    satellite["pct"] = round(satellite["value_chf"] / total * 100, 1) if total > 0 else 0
    unassigned["pct"] = round(unassigned["value_chf"] / total * 100, 1) if total > 0 else 0

    # Sort positions by value descending
    core["positions"].sort(key=lambda p: p["value_chf"], reverse=True)
    satellite["positions"].sort(key=lambda p: p["value_chf"], reverse=True)
    unassigned["positions"].sort(key=lambda p: p["value_chf"], reverse=True)

    return {"core": core, "satellite": satellite, "unassigned": unassigned}
