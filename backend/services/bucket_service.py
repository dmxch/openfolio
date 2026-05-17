"""Bucket-Verwaltung: CRUD, System-Init, Soft-Delete, Validierung.

Public API:
  - create_system_buckets(db, user_id)      Idempotent, fuer User-Registrierung
  - list_buckets(db, user_id, include_deleted=False)
  - get_bucket(db, user_id, bucket_id)
  - create_bucket(db, user_id, ...)
  - update_bucket(db, user_id, bucket_id, ...)
  - delete_bucket(db, user_id, bucket_id)   Soft-Delete, mappt Positionen zu liquid_default
  - move_position_to_bucket(db, user_id, position_id, bucket_id, changed_by='user')
  - migration_rollback(db, user_id)         Loescht User-Buckets, mappt zu liquid_default

KISS: keine Validation-Frameworks, einfache Exceptions.
"""
from __future__ import annotations

import logging
import uuid
from typing import Iterable

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dateutils import utcnow
from models.bucket import (
    Bucket,
    BucketAlertLog,  # noqa: F401 — re-export not needed but ensures table is registered
    BucketKind,
    BucketSnapshot,  # noqa: F401
    BucketSystemRole,
    PositionBucketHistory,
    SYSTEM_BUCKET_NAMES,
)
from models.position import Position

logger = logging.getLogger(__name__)


MAX_BUCKETS_PER_USER = 15

_SYSTEM_BUCKET_SORT = {
    BucketSystemRole.liquid_default: 0,
    BucketSystemRole.real_estate: 90,
    BucketSystemRole.private_equity: 91,
    BucketSystemRole.pension: 92,
}

_SYSTEM_BUCKET_COLOR = {
    BucketSystemRole.liquid_default: "#64748b",
    BucketSystemRole.real_estate: "#a3a3a3",
    BucketSystemRole.private_equity: "#a3a3a3",
    BucketSystemRole.pension: "#a3a3a3",
}


class BucketError(Exception):
    """Domain-Fehler im Bucket-Service. User-facing message ist Deutsch."""


# ---------------------------------------------------------------------------
# System-Buckets
# ---------------------------------------------------------------------------

async def create_system_buckets(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Idempotent: erzeugt die 4 System-Buckets fuer einen User.

    Aufrufer ist verantwortlich fuer await db.commit().
    """
    for role in (
        BucketSystemRole.liquid_default,
        BucketSystemRole.real_estate,
        BucketSystemRole.private_equity,
        BucketSystemRole.pension,
    ):
        stmt = pg_insert(Bucket).values(
            user_id=user_id,
            name=SYSTEM_BUCKET_NAMES[role],
            kind=BucketKind.system,
            system_role=role,
            sort_order=_SYSTEM_BUCKET_SORT[role],
            color=_SYSTEM_BUCKET_COLOR[role],
        ).on_conflict_do_nothing(
            index_elements=["user_id", "name"],
            index_where=text("deleted_at IS NULL"),
        )
        await db.execute(stmt)


async def get_liquid_default_bucket(
    db: AsyncSession, user_id: uuid.UUID
) -> Bucket:
    """Garantiert vorhandenen liquid_default-Bucket zurueckgeben.

    Ruft bei Bedarf create_system_buckets nach.
    """
    result = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.system_role == BucketSystemRole.liquid_default,
            Bucket.deleted_at.is_(None),
        )
    )
    bucket = result.scalar_one_or_none()
    if bucket is None:
        await create_system_buckets(db, user_id)
        await db.flush()
        result = await db.execute(
            select(Bucket).where(
                Bucket.user_id == user_id,
                Bucket.system_role == BucketSystemRole.liquid_default,
                Bucket.deleted_at.is_(None),
            )
        )
        bucket = result.scalar_one()
    return bucket


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def list_buckets(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_deleted: bool = False,
) -> list[Bucket]:
    stmt = select(Bucket).where(Bucket.user_id == user_id)
    if not include_deleted:
        stmt = stmt.where(Bucket.deleted_at.is_(None))
    stmt = stmt.order_by(Bucket.sort_order, Bucket.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def load_buckets_map(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Liefert ein str(bucket_id)-Mapping mit den fuer alert_service relevanten
    Feldern. Verwendet von generate_alerts um Bucket-Overrides
    (max_position_pct, alert_loss_pct, max_sector_pct) anzuwenden.

    Returns:
        {"<bucket_uuid_str>": {"name": str, "risk_rules": dict, "kind": str}}
    """
    result = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.deleted_at.is_(None),
        )
    )
    return {
        str(b.id): {
            "name": b.name,
            "risk_rules": b.risk_rules or {},
            "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
        }
        for b in result.scalars().all()
    }


async def count_active_user_buckets(
    db: AsyncSession, user_id: uuid.UUID
) -> int:
    """Anzahl aktiver kind='user' Buckets — bestimmt UI-Sichtbarkeit."""
    result = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.kind == BucketKind.user,
            Bucket.deleted_at.is_(None),
        )
    )
    return len(result.scalars().all())


async def get_bucket(
    db: AsyncSession, user_id: uuid.UUID, bucket_id: uuid.UUID
) -> Bucket:
    result = await db.execute(
        select(Bucket).where(
            Bucket.id == bucket_id,
            Bucket.user_id == user_id,
        )
    )
    bucket = result.scalar_one_or_none()
    if bucket is None:
        raise BucketError("Bucket nicht gefunden")
    return bucket


async def create_bucket(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    color: str | None = None,
    benchmark: str | None = None,
    target_pct: float | None = None,
    target_chf: float | None = None,
    description: str | None = None,
    risk_rules: dict | None = None,
    sort_order: int | None = None,
) -> Bucket:
    name = (name or "").strip()
    if not name:
        raise BucketError("Bucket-Name darf nicht leer sein")
    if len(name) > 50:
        raise BucketError("Bucket-Name darf maximal 50 Zeichen haben")

    if target_pct is not None and target_chf is not None:
        raise BucketError("Pro Bucket nur Ziel-Prozent ODER Ziel-CHF setzen")

    # Limit pruefen (nur user-buckets zaehlen)
    active = await count_active_user_buckets(db, user_id)
    if active >= MAX_BUCKETS_PER_USER:
        raise BucketError(
            f"Maximal {MAX_BUCKETS_PER_USER} Buckets erlaubt. Loesche oder reaktiviere bestehende."
        )

    # Naming-Konflikt mit System-Bucket vermeiden
    existing = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.name == name,
            Bucket.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise BucketError(f"Bucket-Name '{name}' bereits vergeben")

    if sort_order is None:
        # haengt unten an
        max_sort = await db.execute(
            select(Bucket.sort_order).where(
                Bucket.user_id == user_id,
                Bucket.kind == BucketKind.user,
                Bucket.deleted_at.is_(None),
            )
        )
        existing_orders = [row for row in max_sort.scalars().all()]
        sort_order = (max(existing_orders) + 10) if existing_orders else 10

    bucket = Bucket(
        user_id=user_id,
        name=name,
        kind=BucketKind.user,
        color=color,
        benchmark=benchmark,
        target_pct=target_pct,
        target_chf=target_chf,
        description=description,
        risk_rules=risk_rules,
        sort_order=sort_order,
    )
    db.add(bucket)
    await db.flush()
    return bucket


async def update_bucket(
    db: AsyncSession,
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
    *,
    name: str | None = None,
    color: str | None = None,
    benchmark: str | None = None,
    target_pct: float | None = None,
    target_chf: float | None = None,
    description: str | None = None,
    risk_rules: dict | None = None,
    sort_order: int | None = None,
) -> Bucket:
    bucket = await get_bucket(db, user_id, bucket_id)

    if bucket.deleted_at is not None:
        raise BucketError("Geloeschter Bucket kann nicht bearbeitet werden")

    # System-Bucket: Name nicht editierbar
    if bucket.kind == BucketKind.system and name is not None and name != bucket.name:
        raise BucketError("System-Bucket-Name kann nicht geaendert werden")

    if name is not None:
        name = name.strip()
        if not name:
            raise BucketError("Bucket-Name darf nicht leer sein")
        if len(name) > 50:
            raise BucketError("Bucket-Name darf maximal 50 Zeichen haben")
        # Eindeutigkeit pruefen
        if name != bucket.name:
            conflict = await db.execute(
                select(Bucket).where(
                    Bucket.user_id == user_id,
                    Bucket.name == name,
                    Bucket.deleted_at.is_(None),
                    Bucket.id != bucket_id,
                )
            )
            if conflict.scalar_one_or_none() is not None:
                raise BucketError(f"Bucket-Name '{name}' bereits vergeben")
        bucket.name = name

    if target_pct is not None and target_chf is not None:
        raise BucketError("Pro Bucket nur Ziel-Prozent ODER Ziel-CHF setzen")

    if color is not None:
        bucket.color = color or None
    if benchmark is not None:
        bucket.benchmark = benchmark or None
    if target_pct is not None:
        bucket.target_pct = target_pct
        bucket.target_chf = None
    if target_chf is not None:
        bucket.target_chf = target_chf
        bucket.target_pct = None
    if description is not None:
        bucket.description = description or None
    if risk_rules is not None:
        bucket.risk_rules = risk_rules
    if sort_order is not None:
        bucket.sort_order = sort_order

    bucket.updated_at = utcnow()
    return bucket


async def delete_bucket(
    db: AsyncSession,
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
) -> int:
    """Soft-Delete: Positionen wandern zu liquid_default. Returns count moved."""
    bucket = await get_bucket(db, user_id, bucket_id)
    if bucket.kind == BucketKind.system:
        raise BucketError("System-Bucket kann nicht geloescht werden")
    if bucket.deleted_at is not None:
        return 0  # idempotent

    fallback = await get_liquid_default_bucket(db, user_id)

    # Positionen umlabeln
    moved = await db.execute(
        select(Position).where(
            Position.bucket_id == bucket_id,
            Position.user_id == user_id,
        )
    )
    positions = list(moved.scalars().all())
    for p in positions:
        await _record_position_move(
            db,
            position_id=p.id,
            from_bucket_id=bucket_id,
            to_bucket_id=fallback.id,
            changed_by="user",
            note=f"Bucket '{bucket.name}' geloescht",
        )
        p.bucket_id = fallback.id

    bucket.deleted_at = utcnow()
    await db.flush()
    return len(positions)


# ---------------------------------------------------------------------------
# Position-Wechsel
# ---------------------------------------------------------------------------

async def _record_position_move(
    db: AsyncSession,
    *,
    position_id: uuid.UUID,
    from_bucket_id: uuid.UUID | None,
    to_bucket_id: uuid.UUID,
    changed_by: str,
    note: str | None = None,
) -> None:
    db.add(
        PositionBucketHistory(
            position_id=position_id,
            from_bucket_id=from_bucket_id,
            to_bucket_id=to_bucket_id,
            changed_by=changed_by,
            note=note,
        )
    )


async def move_position_to_bucket(
    db: AsyncSession,
    user_id: uuid.UUID,
    position_id: uuid.UUID,
    target_bucket_id: uuid.UUID,
    *,
    changed_by: str = "user",
    note: str | None = None,
) -> Position:
    """Re-Labeling: keine Trades, kein realized P&L. Cost-Basis wandert mit."""
    result = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.user_id == user_id,
        )
    )
    position = result.scalar_one_or_none()
    if position is None:
        raise BucketError("Position nicht gefunden")

    target = await get_bucket(db, user_id, target_bucket_id)
    if target.deleted_at is not None:
        raise BucketError("Ziel-Bucket ist geloescht")

    if position.bucket_id == target_bucket_id:
        return position  # idempotent

    await _record_position_move(
        db,
        position_id=position.id,
        from_bucket_id=position.bucket_id,
        to_bucket_id=target_bucket_id,
        changed_by=changed_by,
        note=note,
    )
    position.bucket_id = target_bucket_id
    await db.flush()
    return position


# ---------------------------------------------------------------------------
# Migration-Rollback (fuer Onboarding-Modal "Buckets aufheben")
# ---------------------------------------------------------------------------

async def migration_rollback(
    db: AsyncSession, user_id: uuid.UUID
) -> dict:
    """Soft-Delete aller User-Buckets dieses Users, Positionen zu liquid_default.

    Wird vom Onboarding-Modal "Buckets aufheben" gerufen. System-Buckets
    bleiben unangetastet.
    """
    fallback = await get_liquid_default_bucket(db, user_id)
    result = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.kind == BucketKind.user,
            Bucket.deleted_at.is_(None),
        )
    )
    user_buckets = list(result.scalars().all())

    moved_positions = 0
    for ub in user_buckets:
        pos_result = await db.execute(
            select(Position).where(
                Position.user_id == user_id,
                Position.bucket_id == ub.id,
            )
        )
        positions = list(pos_result.scalars().all())
        for p in positions:
            await _record_position_move(
                db,
                position_id=p.id,
                from_bucket_id=ub.id,
                to_bucket_id=fallback.id,
                changed_by="migration_rollback",
                note=f"Onboarding: User-Buckets aufgehoben (von '{ub.name}')",
            )
            p.bucket_id = fallback.id
            moved_positions += 1
        ub.deleted_at = utcnow()

    # Flag setzen: Modal nicht mehr zeigen
    from models.user import UserSettings
    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = settings_result.scalar_one_or_none()
    if settings is not None:
        settings.noticed_buckets_migration = True

    await db.flush()
    return {
        "buckets_deleted": len(user_buckets),
        "positions_moved": moved_positions,
    }


# ---------------------------------------------------------------------------
# Risk-Rules-Diff (fuer Bucket-Wechsel-Confirmation-Modal)
# ---------------------------------------------------------------------------

_DEFAULT_RISK_RULES = {
    "drawdown_brake_pct": 6.0,
    "drawdown_brake_active": True,
    "stop_loss_method_default": None,
    "stop_loss_default_pct": None,
}


def _effective_rules(bucket: Bucket) -> dict:
    rules = dict(_DEFAULT_RISK_RULES)
    if bucket.risk_rules:
        rules.update(bucket.risk_rules)
    return rules


def diff_risk_rules(from_bucket: Bucket | None, to_bucket: Bucket) -> list[dict]:
    """Erzeugt zeilenweise Diff fuer das Wechsel-Modal.

    Returns:
        Liste von {key, label, old, new, changed: bool}.
        Vom Frontend gerendert als Tabelle.
    """
    labels = {
        "drawdown_brake_pct": "Drawdown-Bremse (%)",
        "drawdown_brake_active": "Drawdown-Bremse aktiv",
        "stop_loss_method_default": "Stop-Loss-Methode (Vorschlag)",
        "stop_loss_default_pct": "Stop-Loss-Default (%)",
    }
    old_rules = _effective_rules(from_bucket) if from_bucket else dict(_DEFAULT_RISK_RULES)
    new_rules = _effective_rules(to_bucket)
    diff = []
    for key, label in labels.items():
        old_val = old_rules.get(key)
        new_val = new_rules.get(key)
        diff.append({
            "key": key,
            "label": label,
            "old": old_val,
            "new": new_val,
            "changed": old_val != new_val,
        })
    # Benchmark separat (kein risk_rule, aber relevant fuer Modal)
    diff.append({
        "key": "benchmark",
        "label": "Benchmark",
        "old": from_bucket.benchmark if from_bucket else None,
        "new": to_bucket.benchmark,
        "changed": (from_bucket.benchmark if from_bucket else None) != to_bucket.benchmark,
    })
    return diff
