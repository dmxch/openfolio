"""Per-Position-Rebalancing (lean): bricht den Bucket-Ueberhang aus dem
Rebalancing-Cockpit auf konkrete Trim-Kandidaten herunter (groesste Position
zuerst) und flaggt Klumpenrisiken.

BEWUSST KEINE Positions-Ziele (die gibt es im Modell nicht) -> nur die
"reduzieren"-Seite ist eindeutig ableitbar; die "aufstocken"-Seite bleibt auf
Bucket-Ebene (dort fehlt der Zielpunkt je Position). Read-only, neutrale Sprache,
beruehrt keine Korrektheits-Invariante. Heuristik: einen Bucket-Ueberhang
groesste-Position-zuerst zuteilen reduziert gleichzeitig Drift UND Konzentration.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.portfolio_service import get_portfolio_summary
from services.rebalancing_service import get_rebalancing_plan

# Handelbare Typen (Cash/Vorsorge/PE/Immobilien sind nicht trimmbar).
_TRADABLE = {"stock", "etf", "bond", "crypto", "commodity"}
# Einzelposition > Schwelle (% des liquiden Werts) -> Klumpenrisiko-Flag.
_CONCENTRATION_PCT = 10.0
# Rest-Ueberhang darunter gilt als ausgeglichen (Rundungs-Rauschen, keine Zeile).
_TRIM_FLOOR_CHF = 0.005


def _is_tradable(p: dict) -> bool:
    return p.get("type") in _TRADABLE and not p.get("count_as_cash")


async def get_position_rebalancing(db: AsyncSession, user_id: uuid.UUID) -> dict:
    plan = await get_rebalancing_plan(db, user_id)
    summary = await get_portfolio_summary(db, user_id)
    positions = summary.get("positions", [])

    by_bucket: dict[str, list] = {}
    for p in positions:
        if not _is_tradable(p):
            continue
        bid = p.get("bucket_id")
        if bid:
            by_bucket.setdefault(bid, []).append(p)

    trim_candidates: list[dict] = []
    if plan.get("has_targets"):
        overweight_buckets = [b for b in plan.get("buckets", []) if b["delta_chf"] < 0]
        for b in overweight_buckets:
            overweight = round(-b["delta_chf"], 2)
            holdings = sorted(
                by_bucket.get(b["bucket_id"], []),
                key=lambda p: float(p.get("market_value_chf") or 0),
                reverse=True,
            )
            remaining = overweight
            for p in holdings:
                if remaining <= _TRIM_FLOOR_CHF:
                    break
                value = float(p.get("market_value_chf") or 0)
                trim = round(min(remaining, value), 2)
                remaining = round(remaining - trim, 2)
                trim_candidates.append({
                    "ticker": p.get("ticker"),
                    "name": p.get("name"),
                    "bucket_name": b["name"],
                    "current_chf": round(value, 2),
                    "weight_pct": p.get("weight_pct"),
                    "trim_chf": trim,
                    "bucket_overweight_chf": overweight,
                })

    concentration_flags = sorted(
        [
            {
                "ticker": p.get("ticker"),
                "name": p.get("name"),
                "weight_pct": p.get("weight_pct"),
                "value_chf": round(float(p.get("market_value_chf") or 0), 2),
            }
            for p in positions
            if _is_tradable(p) and float(p.get("weight_pct") or 0) >= _CONCENTRATION_PCT
        ],
        key=lambda x: -(x.get("weight_pct") or 0),
    )

    return {
        "has_data": bool(trim_candidates or concentration_flags),
        "concentration_threshold_pct": _CONCENTRATION_PCT,
        "trim_candidates": trim_candidates,
        "concentration_flags": concentration_flags,
    }
