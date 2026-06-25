"""Core/Satellite allocation calculation service.

Phase 3: Klassifizierung kommt aus bucket.risk_rules statt position_type.
- Bucket mit stop_loss_method_default oder stop_loss_default_pct → 'satellite'
- Sonstiger User-Bucket → 'core'
- Liquid-Default-Bucket → 'unassigned'

API-Schema bleibt unveraendert (core/satellite/unassigned) fuer Backward-Compat
mit externen Konsumenten. Neue Konsumenten sollten /buckets/allocations nutzen.
"""

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bucket import Bucket, BucketKind, BucketSystemRole
from models.position import Position
from services.utils import get_fx_rates_batch

logger = logging.getLogger(__name__)

TRADABLE_TYPES = {"stock", "etf"}
EXCLUDE_LIQUID = {"pension", "real_estate", "private_equity"}


def _classify_bucket(bucket: Bucket | None) -> str:
    """Mappe Bucket auf core/satellite/unassigned-Bezeichnung.

    Frueher: position_type=core/satellite/null.
    Heute: Bucket-Rules + system_role als Klassifikator.
    """
    if bucket is None:
        return "unassigned"
    if bucket.system_role == BucketSystemRole.liquid_default:
        return "unassigned"
    if bucket.kind != BucketKind.user:
        return "unassigned"
    rules = bucket.risk_rules or {}
    if rules.get("stop_loss_method_default") or rules.get("stop_loss_default_pct") is not None:
        return "satellite"
    return "core"


async def get_core_satellite_allocation(
    db: AsyncSession, user_id: UUID, view: str = "liquid"
) -> dict:
    """Return core/satellite/unassigned allocation breakdown.

    Phase 3: Klassifikation aus bucket.risk_rules; siehe Modul-Docstring.
    """
    pos_q = await db.execute(
        select(Position).where(Position.is_active == True, Position.user_id == user_id)
    )
    positions = pos_q.scalars().all()

    bucket_q = await db.execute(
        select(Bucket).where(Bucket.user_id == user_id, Bucket.deleted_at.is_(None))
    )
    buckets_by_id = {b.id: b for b in bucket_q.scalars().all()}

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
        # Geldmarkt-/T-Bill-ETFs (count_as_cash) zaehlen als Cash, nicht als
        # Aktien-Exposure — aus der Core/Satellite-Aufteilung ausnehmen.
        if getattr(pos, "count_as_cash", False):
            continue

        shares = float(pos.shares)
        price = float(pos.current_price) if pos.current_price else 0
        if price > 0:
            fx = fx_rates.get(pos.currency, 1.0) if pos.currency != "CHF" else 1.0
            value_chf = round(price * shares * fx, 2)
        else:
            value_chf = round(float(pos.cost_basis_chf), 2)

        bucket = buckets_by_id.get(pos.bucket_id) if pos.bucket_id else None
        classification = _classify_bucket(bucket)

        pos_info = {
            "ticker": pos.ticker,
            "name": pos.name,
            "value_chf": value_chf,
            "type": pos.type.value,
            "bucket_id": str(pos.bucket_id) if pos.bucket_id else None,
            "bucket_name": bucket.name if bucket else None,
        }

        if classification == "core":
            core["value_chf"] += value_chf
            core["positions"].append(pos_info)
        elif classification == "satellite":
            satellite["value_chf"] += value_chf
            satellite["positions"].append(pos_info)
        else:
            unassigned["value_chf"] += value_chf
            unassigned["positions"].append(pos_info)

    total = core["value_chf"] + satellite["value_chf"] + unassigned["value_chf"]
    core["pct"] = round(core["value_chf"] / total * 100, 1) if total > 0 else 0
    satellite["pct"] = round(satellite["value_chf"] / total * 100, 1) if total > 0 else 0
    unassigned["pct"] = round(unassigned["value_chf"] / total * 100, 1) if total > 0 else 0

    core["positions"].sort(key=lambda p: p["value_chf"], reverse=True)
    satellite["positions"].sort(key=lambda p: p["value_chf"], reverse=True)
    unassigned["positions"].sort(key=lambda p: p["value_chf"], reverse=True)

    return {"core": core, "satellite": satellite, "unassigned": unassigned}
