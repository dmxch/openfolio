"""Bucket-Templates fuer Phase 1 (Core/Satellite, FIRE/Spielgeld).

Templates erzeugen mehrere User-Buckets atomar via apply_template().
Weitere Templates (Time-Horizon, Risk-Tiers) folgen in Phase 2.
"""
from __future__ import annotations

import uuid
from copy import deepcopy

from sqlalchemy.ext.asyncio import AsyncSession

from services.bucket_service import BucketError, create_bucket, count_active_user_buckets

# Risk-Rules-Werte werden vom drawdown_service / alert_service konsumiert.
# stop_loss_method_default und stop_loss_default_pct sind in MVP nur als
# Vorschlagswerte fuer das Add-Position-Modal gedacht — keine Enforcement.
TEMPLATES: dict[str, dict] = {
    "core_satellite": {
        "label": "Core / Satellite",
        "description": "Passive Core-ETFs + aktive Satellite-Picks. "
        "Core hat eine vorsichtige 6%-Drawdown-Bremse, Satellite tolerantere 15%.",
        "buckets": [
            {
                "name": "Core",
                "color": "#3b82f6",
                "benchmark": "URTH",
                "sort_order": 10,
                "risk_rules": {
                    "drawdown_brake_pct": 6.0,
                    "drawdown_brake_active": True,
                    "stop_loss_method_default": None,
                },
            },
            {
                "name": "Satellite",
                "color": "#f59e0b",
                "benchmark": "^GSPC",
                "sort_order": 20,
                "risk_rules": {
                    "drawdown_brake_pct": 15.0,
                    "drawdown_brake_active": True,
                    "stop_loss_method_default": "trailing_pct",
                    "stop_loss_default_pct": 8.0,
                },
            },
        ],
    },
    "fire_spielgeld": {
        "label": "FIRE / Spielgeld",
        "description": "Langfristiger FIRE-Bucket mit konservativer Drawdown-Bremse "
        "und ein Spielgeld-Bucket mit hoher Risikotoleranz.",
        "buckets": [
            {
                "name": "FIRE",
                "color": "#10b981",
                "benchmark": "URTH",
                "sort_order": 10,
                "risk_rules": {
                    "drawdown_brake_pct": 6.0,
                    "drawdown_brake_active": True,
                    "stop_loss_method_default": None,
                },
            },
            {
                "name": "Spielgeld",
                "color": "#ef4444",
                "benchmark": "^GSPC",
                "sort_order": 20,
                "risk_rules": {
                    "drawdown_brake_pct": 25.0,
                    "drawdown_brake_active": True,
                    "stop_loss_method_default": "trailing_pct",
                    "stop_loss_default_pct": 10.0,
                },
            },
        ],
    },
}


def list_templates() -> list[dict]:
    """Templates fuer Frontend-Auswahl (ohne Risk-Rule-Details)."""
    return [
        {
            "key": key,
            "label": tpl["label"],
            "description": tpl["description"],
            "bucket_names": [b["name"] for b in tpl["buckets"]],
            "bucket_count": len(tpl["buckets"]),
        }
        for key, tpl in TEMPLATES.items()
    ]


async def apply_template(
    db: AsyncSession,
    user_id: uuid.UUID,
    template_key: str,
    *,
    replace_existing: bool = False,
) -> list:
    """Erzeugt alle Buckets eines Templates atomar.

    Caller commits. Bei Fehler (Limit-Ueberschreitung, Naming-Konflikt) wird
    eine BucketError geworfen — Caller soll mit await db.rollback() reagieren.

    replace_existing=True: bestehende gleichnamige User-Buckets werden zuerst
    soft-deletet (Positionen wandern zu liquid_default). Erlaubt Template-
    Wechsel ohne manuelles Loeschen.
    """
    if template_key not in TEMPLATES:
        raise BucketError(f"Unbekanntes Template: {template_key}")

    spec = TEMPLATES[template_key]
    from sqlalchemy import select
    from models.bucket import Bucket, BucketKind
    from services.bucket_service import delete_bucket
    names = [b["name"] for b in spec["buckets"]]
    existing_q = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.name.in_(names),
            Bucket.deleted_at.is_(None),
        )
    )
    existing_buckets = list(existing_q.scalars().all())
    existing_names = {b.name for b in existing_buckets}

    if existing_names and not replace_existing:
        raise BucketError(
            f"Bucket-Namen existieren bereits: {', '.join(sorted(existing_names))}"
        )

    if replace_existing:
        for b in existing_buckets:
            if b.kind != BucketKind.user:
                raise BucketError(
                    f"Bucket '{b.name}' ist ein System-Bucket und kann nicht ersetzt werden"
                )
            await delete_bucket(db, user_id, b.id)

    created = []
    for b in spec["buckets"]:
        bucket = await create_bucket(
            db,
            user_id,
            name=b["name"],
            color=b.get("color"),
            benchmark=b.get("benchmark"),
            description=b.get("description"),
            risk_rules=deepcopy(b.get("risk_rules")),
            sort_order=b.get("sort_order"),
        )
        created.append(bucket)
    return created
