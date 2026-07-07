"""Admin API endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.user import User
from services import admin_service
from services.admin_service import AdminServiceError
from api.schemas import (
    AdminUserListResponse, AdminResetPasswordResponse, AdminTempPasswordResponse,
    AdminSettingsResponse, InviteCodeListResponse, InviteCodeResponse, AuditLogResponse,
    OkResponse,
)
from utils import get_client_ip

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Admin guard ---

async def require_admin(user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    return user


# --- Pydantic models ---

class StatusUpdate(BaseModel):
    is_active: bool


class AdminUpdate(BaseModel):
    is_admin: bool


class MfaRequiredUpdate(BaseModel):
    mfa_required: bool


class AdminSettingsUpdate(BaseModel):
    registration_mode: str | None = None
    mfa_policy: str | None = None


def _ip(request: Request) -> str | None:
    return get_client_ip(request)


# --- User Management ---

@router.get("/users", response_model=AdminUserListResponse)
async def list_users(request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        return await admin_service.list_users(db, admin.id, _ip(request))
    except AdminServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/users/{user_id}/reset-password", response_model=AdminResetPasswordResponse)
@limiter.limit("30/minute")
async def admin_reset_password(user_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        return await admin_service.reset_user_password(db, admin.id, user_id, _ip(request))
    except AdminServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/users/{user_id}/temp-password", response_model=AdminTempPasswordResponse)
@limiter.limit("30/minute")
async def admin_temp_password(user_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        return await admin_service.set_temp_password(db, admin.id, user_id, _ip(request))
    except AdminServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.patch("/users/{user_id}/status")
@limiter.limit("30/minute")
async def update_user_status(user_id: uuid.UUID, data: StatusUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        return await admin_service.update_user_status(db, admin.id, user_id, data.is_active, _ip(request))
    except AdminServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.patch("/users/{user_id}/admin")
@limiter.limit("30/minute")
async def update_user_admin(user_id: uuid.UUID, data: AdminUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        return await admin_service.update_user_admin(db, admin.id, user_id, data.is_admin, _ip(request))
    except AdminServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.patch("/users/{user_id}/mfa-required")
@limiter.limit("30/minute")
async def update_user_mfa_required(user_id: uuid.UUID, data: MfaRequiredUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        return await admin_service.update_user_mfa_required(db, admin.id, user_id, data.mfa_required, _ip(request))
    except AdminServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete("/users/{user_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_user_endpoint(user_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        await admin_service.delete_user(db, admin.id, user_id, _ip(request))
    except AdminServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# --- Admin Settings ---

@router.get("/settings", response_model=AdminSettingsResponse)
async def get_admin_settings(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.get_admin_settings(db)


@router.patch("/settings")
@limiter.limit("30/minute")
async def update_admin_settings(data: AdminSettingsUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        return await admin_service.update_admin_settings(
            db, admin.id,
            registration_mode=data.registration_mode,
            mfa_policy=data.mfa_policy,
            client_ip=_ip(request),
        )
    except AdminServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# --- Invite Codes ---

@router.get("/invite-codes", response_model=InviteCodeListResponse)
async def list_invite_codes(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.list_invite_codes(db)


@router.post("/invite-codes", response_model=InviteCodeResponse)
@limiter.limit("30/minute")
async def create_invite_code(request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        return await admin_service.create_invite_code(db, admin.id, _ip(request))
    except AdminServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete("/invite-codes/{code_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_invite_code(code_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        await admin_service.delete_invite_code(db, admin.id, code_id, _ip(request))
    except AdminServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# --- Audit Log ---

@router.get("/audit-log", response_model=AuditLogResponse)
async def get_audit_log(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return await admin_service.get_audit_log(db, page, per_page)


# --- Worker-Job-Health (Liveness) ---

@router.get("/worker-health")
async def get_worker_health(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Heartbeat-Status aller Worker-Jobs + abgeleitete is_stale/is_failing-Flags.

    Der Worker (eigener Prozess) schreibt pro Lauf eine Zeile; hier wird die
    Staleness aus ``last_run_at`` + ``max_age_s`` berechnet — ohne die
    Schedule-Definition zu kennen.
    """
    from dateutils import utcnow
    from services.worker_health_service import (
        FAILURE_ALERT_THRESHOLD, get_all_health, is_stale_row,
    )
    now = utcnow()
    rows = await get_all_health(db)
    items = []
    stale_n = failing_n = 0
    for r in rows:
        is_stale = is_stale_row(r, now)
        is_failing = (r.get("consecutive_failures") or 0) >= FAILURE_ALERT_THRESHOLD
        stale_n += int(is_stale)
        failing_n += int(is_failing)
        items.append({**r, "is_stale": is_stale, "is_failing": is_failing})
    return {
        "jobs": items,
        "summary": {"total": len(items), "stale": stale_n, "failing": failing_n},
        "as_of": now.isoformat(),
    }
