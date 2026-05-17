"""Bucket-API: CRUD, Templates, Migration-Rollback, Performance, Drawdown.

Routen (alle JWT-auth):
  GET    /api/portfolio/buckets                              List active+system buckets
  POST   /api/portfolio/buckets                              Create user bucket
  GET    /api/portfolio/buckets/templates                    List bucket templates
  POST   /api/portfolio/buckets/from-template                Apply template (atomar)
  POST   /api/portfolio/buckets/migration-rollback           Soft-delete user buckets
  GET    /api/portfolio/buckets/{id}                         Bucket detail
  PATCH  /api/portfolio/buckets/{id}                         Update bucket
  DELETE /api/portfolio/buckets/{id}                         Soft-delete (with reassign)
  GET    /api/portfolio/buckets/{id}/summary                 Current value & PnL
  GET    /api/portfolio/buckets/{id}/history?period=ytd      Time series
  GET    /api/portfolio/buckets/{id}/drawdown?period=ytd     Drawdown + bremse
  POST   /api/portfolio/positions/{pid}/move-to-bucket       Re-Labeling
  GET    /api/portfolio/positions/{pid}/bucket-change-preview?to_bucket=...
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.portfolio import invalidate_portfolio_cache
from auth import get_current_user
from db import get_db
from models.bucket import Bucket, BucketKind, BucketSystemRole
from models.position import Position
from models.user import User, UserSettings
from services.bucket_service import (
    BucketError,
    MAX_BUCKETS_PER_USER,
    create_bucket,
    create_system_buckets,
    delete_bucket,
    diff_risk_rules,
    get_bucket,
    list_buckets,
    migration_rollback,
    move_position_to_bucket,
    update_bucket,
)
from services.bucket_templates import apply_template, list_templates
from services.bucket_performance_service import (
    compare_to_benchmark,
    get_allocations_by_bucket,
    get_bucket_cashflows,
    get_bucket_history,
    get_bucket_monthly_returns,
    get_bucket_summary,
)
from services.drawdown_service import get_max_drawdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["buckets"])


# --- Schemas ---

class BucketOut(BaseModel):
    id: str
    name: str
    kind: str
    system_role: str | None
    color: str | None
    benchmark: str | None
    target_pct: float | None
    target_chf: float | None
    description: str | None
    sort_order: int
    risk_rules: dict | None
    deleted_at: str | None

    @classmethod
    def from_model(cls, b: Bucket) -> "BucketOut":
        return cls(
            id=str(b.id),
            name=b.name,
            kind=b.kind.value if hasattr(b.kind, "value") else b.kind,
            system_role=(b.system_role.value if b.system_role else None),
            color=b.color,
            benchmark=b.benchmark,
            target_pct=float(b.target_pct) if b.target_pct is not None else None,
            target_chf=float(b.target_chf) if b.target_chf is not None else None,
            description=b.description,
            sort_order=b.sort_order,
            risk_rules=b.risk_rules,
            deleted_at=b.deleted_at.isoformat() if b.deleted_at else None,
        )


class BucketCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str | None = Field(None, max_length=7)
    benchmark: str | None = Field(None, max_length=20)
    target_pct: float | None = Field(None, ge=0, le=100)
    target_chf: float | None = Field(None, ge=0)
    description: str | None = None
    risk_rules: dict | None = None
    sort_order: int | None = None


class BucketUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=50)
    color: str | None = Field(None, max_length=7)
    benchmark: str | None = Field(None, max_length=20)
    target_pct: float | None = Field(None, ge=0, le=100)
    target_chf: float | None = Field(None, ge=0)
    description: str | None = None
    risk_rules: dict | None = None
    sort_order: int | None = None


class TemplateApply(BaseModel):
    template_key: str = Field(..., min_length=1, max_length=50)
    replace_existing: bool = False


class MovePosition(BaseModel):
    target_bucket_id: str
    note: str | None = None


# --- CRUD ---

@router.get("/buckets")
async def list_user_buckets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Falls System-Buckets fehlen (Edge-Case bei vor-Migration-Usern): nachholen
    await create_system_buckets(db, user.id)
    await db.commit()

    buckets = await list_buckets(db, user.id)
    user_bucket_count = sum(
        1 for b in buckets if b.kind == BucketKind.user and b.deleted_at is None
    )
    settings_q = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    settings = settings_q.scalar_one_or_none()
    show_modal = (
        settings is not None
        and not settings.noticed_buckets_migration
        and user_bucket_count >= 2
    )
    return {
        "buckets": [BucketOut.from_model(b).model_dump() for b in buckets],
        "limit": MAX_BUCKETS_PER_USER,
        "active_user_buckets": user_bucket_count,
        "show_onboarding_modal": show_modal,
    }


@router.post("/buckets", status_code=201)
async def create_user_bucket(
    payload: BucketCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        bucket = await create_bucket(
            db,
            user.id,
            name=payload.name,
            color=payload.color,
            benchmark=payload.benchmark,
            target_pct=payload.target_pct,
            target_chf=payload.target_chf,
            description=payload.description,
            risk_rules=payload.risk_rules,
            sort_order=payload.sort_order,
        )
    except BucketError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return BucketOut.from_model(bucket).model_dump()


@router.get("/buckets/templates")
async def get_bucket_templates(
    user: User = Depends(get_current_user),
):
    return {"templates": list_templates()}


@router.get("/buckets/allocations")
async def buckets_allocations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Live-Allokation pro Bucket (fuer AllocationCharts.by_bucket).

    Liefert eine Liste {bucket_id, name, color, value_chf, pct, ...}.
    Endpoint ist additiv — portfolio_service bleibt unangetastet (heilige
    Regel).
    """
    items = await get_allocations_by_bucket(db, user.id)
    return {"items": items}


@router.post("/buckets/from-template", status_code=201)
async def create_from_template(
    payload: TemplateApply,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        created = await apply_template(
            db,
            user.id,
            payload.template_key,
            replace_existing=payload.replace_existing,
        )
    except BucketError as e:
        await db.rollback()
        # Naming-Konflikt → 409 mit machine-readable detail, damit das Frontend
        # einen Bestaetigungs-Dialog "Bestehende ersetzen?" zeigen kann.
        msg = str(e)
        if msg.startswith("Bucket-Namen existieren bereits"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "bucket_name_conflict",
                    "message": msg,
                    "can_replace": True,
                },
            )
        raise HTTPException(status_code=400, detail=msg)
    await db.commit()
    return {
        "created": [BucketOut.from_model(b).model_dump() for b in created],
        "count": len(created),
    }


@router.post("/buckets/migration-rollback")
async def migration_rollback_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await migration_rollback(db, user.id)
    await db.commit()
    if result.get("positions_moved", 0) > 0:
        invalidate_portfolio_cache(str(user.id))
    return result


@router.get("/buckets/{bucket_id}")
async def get_user_bucket(
    bucket_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        bucket = await get_bucket(db, user.id, bucket_id)
    except BucketError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return BucketOut.from_model(bucket).model_dump()


@router.patch("/buckets/{bucket_id}")
async def update_user_bucket(
    bucket_id: uuid.UUID,
    payload: BucketUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        bucket = await update_bucket(
            db,
            user.id,
            bucket_id,
            name=payload.name,
            color=payload.color,
            benchmark=payload.benchmark,
            target_pct=payload.target_pct,
            target_chf=payload.target_chf,
            description=payload.description,
            risk_rules=payload.risk_rules,
            sort_order=payload.sort_order,
        )
    except BucketError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return BucketOut.from_model(bucket).model_dump()


@router.delete("/buckets/{bucket_id}")
async def delete_user_bucket(
    bucket_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        moved = await delete_bucket(db, user.id, bucket_id)
    except BucketError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    if moved > 0:
        invalidate_portfolio_cache(str(user.id))
    return {"deleted": True, "positions_moved": moved}


# --- Performance / Drawdown ---

@router.get("/buckets/{bucket_id}/summary")
async def bucket_summary(
    bucket_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await get_bucket_summary(db, user.id, bucket_id)
    if not data:
        raise HTTPException(status_code=404, detail="Bucket nicht gefunden")
    return data


@router.get("/buckets/{bucket_id}/history")
async def bucket_history(
    bucket_id: uuid.UUID,
    period: str = "ytd",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return {
            "bucket_id": str(bucket_id),
            "period": period,
            "history": await get_bucket_history(
                db, user.id, bucket_id, period=period
            ),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/buckets/{bucket_id}/drawdown")
async def bucket_drawdown(
    bucket_id: uuid.UUID,
    period: str = "ytd",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Threshold aus Bucket.risk_rules
    try:
        bucket = await get_bucket(db, user.id, bucket_id)
    except BucketError as e:
        raise HTTPException(status_code=404, detail=str(e))
    threshold = None
    if bucket.risk_rules:
        threshold = bucket.risk_rules.get("drawdown_brake_pct")
    return await get_max_drawdown(
        db,
        user.id,
        period=period,
        bucket_id=bucket_id,
        brake_threshold_pct=threshold,
    )


@router.get("/buckets/{bucket_id}/monthly-returns")
async def bucket_monthly_returns_endpoint(
    bucket_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Monatliche Returns + Jahres-Totale fuer einen Bucket.

    Schema identisch zu /api/portfolio/monthly-returns — direkt nutzbar
    fuer den MonthlyHeatmap-Component im Bucket-Mode.
    """
    return await get_bucket_monthly_returns(db, user.id, bucket_id)


@router.get("/buckets/{bucket_id}/benchmark-comparison")
async def bucket_benchmark_comparison(
    bucket_id: uuid.UUID,
    period: str = "ytd",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bucket-Return vs konfigurierter Benchmark (period=ytd|1m|3m|6m|1y|all)."""
    try:
        result = await compare_to_benchmark(db, user.id, bucket_id, period=period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="Bucket nicht gefunden")
    return result


@router.get("/buckets/{bucket_id}/cashflows")
async def bucket_cashflows(
    bucket_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_bucket_cashflows(db, user.id, bucket_id)


# --- Position-Move ---

@router.get("/positions/{position_id}/bucket-change-preview")
async def bucket_change_preview(
    position_id: uuid.UUID,
    to_bucket: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pos_q = await db.execute(
        select(Position).where(
            Position.id == position_id, Position.user_id == user.id
        )
    )
    position = pos_q.scalar_one_or_none()
    if position is None:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")

    from_bucket: Bucket | None = None
    if position.bucket_id:
        try:
            from_bucket = await get_bucket(db, user.id, position.bucket_id)
        except BucketError:
            from_bucket = None
    try:
        target = await get_bucket(db, user.id, to_bucket)
    except BucketError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "position_id": str(position_id),
        "ticker": position.ticker,
        "from_bucket": (
            BucketOut.from_model(from_bucket).model_dump() if from_bucket else None
        ),
        "to_bucket": BucketOut.from_model(target).model_dump(),
        "diff": diff_risk_rules(from_bucket, target),
    }


@router.post("/positions/{position_id}/move-to-bucket")
async def move_position(
    position_id: uuid.UUID,
    payload: MovePosition,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        target_uuid = uuid.UUID(payload.target_bucket_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungueltige Bucket-ID")
    try:
        position = await move_position_to_bucket(
            db,
            user.id,
            position_id,
            target_uuid,
            changed_by="user",
            note=payload.note,
        )
    except BucketError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    invalidate_portfolio_cache(str(user.id))
    return {
        "position_id": str(position.id),
        "ticker": position.ticker,
        "bucket_id": str(position.bucket_id),
    }


# --- User-Setting fuer Onboarding-Modal (separate Route, kurz hier) ---

@router.post("/buckets/onboarding-dismiss")
async def onboarding_dismiss(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Schliesst das Migrations-Modal ohne Rollback (User behaelt Buckets)."""
    settings_q = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    settings = settings_q.scalar_one_or_none()
    if settings is not None:
        settings.noticed_buckets_migration = True
    await db.commit()
    return {"noticed_buckets_migration": True}
