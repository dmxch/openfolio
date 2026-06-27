"""Rebalancing-Cockpit: Soll/Ist/Delta pro Bucket + Cash-First-Framing.

Bucket-Ebene (Positionen haben keine Einzelziele -> kein Per-Position-Order).
Ist-Allokation = Konzept B (get_allocations_by_bucket, == Allokations-Pie), damit
die Drift-Zahlen mit dem angezeigten Diagramm deckungsgleich sind.
Buckets tragen target_pct XOR target_chf (CHECK-Constraint ck_buckets_target_xor).
Neutrale Sprache, keine imperativen Anweisungen (CLAUDE.md).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bucket import Bucket
from services.bucket_performance_service import get_allocations_by_bucket
from services.portfolio_service import get_portfolio_summary


async def get_rebalancing_plan(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Soll/Ist/Delta je user-Bucket mit Ziel + Cash-First-Zusammenfassung."""
    base = {
        "has_targets": False, "buckets": [], "total_liquid_chf": 0.0,
        "total_underweight_chf": 0.0, "total_overweight_chf": 0.0,
        "available_cash_chf": 0.0, "cash_covers_underweight_pct": None,
    }

    allocations = await get_allocations_by_bucket(db, user_id)
    total = sum(a["value_chf"] for a in allocations)
    if total <= 0:
        return base

    rows = (await db.execute(
        select(Bucket).where(Bucket.user_id == user_id, Bucket.deleted_at.is_(None))
    )).scalars().all()
    bucket_by_id = {str(b.id): b for b in rows}

    plan: list[dict] = []
    total_under = 0.0
    total_over = 0.0
    for a in allocations:
        if a.get("kind") != "user":
            continue
        b = bucket_by_id.get(a["bucket_id"])
        if b is None or (b.target_pct is None and b.target_chf is None):
            continue
        actual_chf = float(a["value_chf"])
        actual_pct = float(a["pct"])
        if b.target_chf is not None:
            target_chf = round(float(b.target_chf), 2)
            target_pct = round(target_chf / total * 100.0, 2)
        else:
            target_pct = round(float(b.target_pct), 2)
            target_chf = round(target_pct / 100.0 * total, 2)
        delta_chf = round(target_chf - actual_chf, 2)   # + = untergewichtet (aufstocken)
        delta_pp = round(target_pct - actual_pct, 2)
        if delta_chf > 0:
            total_under += delta_chf
        elif delta_chf < 0:
            total_over += -delta_chf
        plan.append({
            "bucket_id": a["bucket_id"],
            "name": a["name"],
            "color": a.get("color"),
            "target_pct": target_pct,
            "actual_pct": actual_pct,
            "delta_pp": delta_pp,
            "target_chf": target_chf,
            "actual_chf": round(actual_chf, 2),
            "delta_chf": delta_chf,
            "status": "untergewichtet" if delta_chf > 0 else ("uebergewichtet" if delta_chf < 0 else "im Ziel"),
        })

    if not plan:
        return base

    # Verfuegbares Cash (Cash-Positionen + count_as_cash-ETFs; Vorsorge zaehlt NICHT,
    # nicht disponibel). Quelle: portfolio_service als Single-Source fuer Marktwerte.
    summary = await get_portfolio_summary(db, user_id)
    available_cash = sum(
        float(p.get("market_value_chf") or 0)
        for p in summary.get("positions", [])
        if p.get("type") == "cash" or p.get("count_as_cash")
    )
    cash_covers = round(min(1.0, available_cash / total_under) * 100.0, 1) if total_under > 0 else None

    plan.sort(key=lambda r: abs(r["delta_chf"]), reverse=True)
    return {
        "has_targets": True,
        "buckets": plan,
        "total_liquid_chf": round(total, 2),
        "total_underweight_chf": round(total_under, 2),
        "total_overweight_chf": round(total_over, 2),
        "available_cash_chf": round(available_cash, 2),
        "cash_covers_underweight_pct": cash_covers,
    }
