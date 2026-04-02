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


class AdminSettingsUpdate(BaseModel):
    registration_mode: str


# --- User Management ---

@router.get("/users")
async def list_users(request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.list_users(db, admin.id, request)


@router.post("/users/{user_id}/reset-password")
@limiter.limit("30/minute")
async def admin_reset_password(user_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.reset_user_password(db, admin.id, user_id, request)


@router.post("/users/{user_id}/temp-password")
@limiter.limit("30/minute")
async def admin_temp_password(user_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.set_temp_password(db, admin.id, user_id, request)


@router.patch("/users/{user_id}/status")
@limiter.limit("30/minute")
async def update_user_status(user_id: uuid.UUID, data: StatusUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.update_user_status(db, admin.id, user_id, data.is_active, request)


@router.patch("/users/{user_id}/admin")
@limiter.limit("30/minute")
async def update_user_admin(user_id: uuid.UUID, data: AdminUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.update_user_admin(db, admin.id, user_id, data.is_admin, request)


@router.delete("/users/{user_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_user_endpoint(user_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    await admin_service.delete_user(db, admin.id, user_id, request)


# --- Admin Settings ---

@router.get("/settings")
async def get_admin_settings(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.get_admin_settings(db)


@router.patch("/settings")
@limiter.limit("30/minute")
async def update_admin_settings(data: AdminSettingsUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.update_admin_settings(db, admin.id, data.registration_mode, request)


# --- Invite Codes ---

@router.get("/invite-codes")
async def list_invite_codes(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.list_invite_codes(db)


@router.post("/invite-codes")
@limiter.limit("30/minute")
async def create_invite_code(request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.create_invite_code(db, admin.id, request)


@router.delete("/invite-codes/{code_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_invite_code(code_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    await admin_service.delete_invite_code(db, admin.id, code_id, request)


# --- Audit Log ---

@router.get("/audit-log")
async def get_audit_log(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return await admin_service.get_audit_log(db, page, per_page)
