"""Admin API endpoints."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from dateutils import utcnow

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from config import settings as app_settings
from db import get_db
from models.user import User, RefreshToken, UserSettings
from models.password_reset_token import PasswordResetToken
from models.app_setting import AppSetting, InviteCode
from models.admin_audit_log import AdminAuditLog
from services.auth_service import hash_password, validate_password
from services.audit_service import log_admin_action

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Admin guard ---

async def require_admin(user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    return user


# --- User Management ---

@router.get("/users")
async def list_users(request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    result = await db.execute(select(User).order_by(User.created_at.asc()))
    users = result.scalars().all()

    user_list = []
    for u in users:
        user_list.append({
            "id": str(u.id),
            "email": u.email,
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "mfa_enabled": u.mfa_enabled,
            "force_password_change": u.force_password_change,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        })

    await log_admin_action(db, admin.id, "list_users", request=request)
    await db.commit()
    return {"users": user_list, "total": len(user_list)}


@router.post("/users/{user_id}/reset-password")
@limiter.limit("30/minute")
async def admin_reset_password(user_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Send password reset email to user."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    from services.email_service import send_email, build_reset_email_html, has_smtp_configured
    if not has_smtp_configured():
        raise HTTPException(status_code=400, detail="SMTP nicht konfiguriert")

    # Invalidate existing tokens
    existing = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used == False)
    )
    for t in existing.scalars().all():
        t.used = True

    # Generate token
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    prt = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    db.add(prt)

    await log_admin_action(db, admin.id, "reset_password", target_user_id=user_id, details={"email": user.email}, request=request)
    await db.commit()

    reset_url = f"{app_settings.frontend_url}/reset-password?token={raw_token}"
    html = build_reset_email_html(reset_url)
    sent = await send_email(user.email, "OpenFolio — Passwort zurücksetzen", html)

    return {"ok": sent, "message": "Reset-Link wurde gesendet." if sent else "E-Mail konnte nicht gesendet werden."}


@router.post("/users/{user_id}/temp-password")
@limiter.limit("30/minute")
async def admin_temp_password(user_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Set a temporary password for a user."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    # Generate random password (8 chars, mix of letters, digits, special)
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789!@#$%"
    temp_pw = "".join(secrets.choice(alphabet) for _ in range(12))

    user.password_hash = hash_password(temp_pw)
    user.force_password_change = True

    # Revoke all sessions
    rt_result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
    )
    for rt in rt_result.scalars().all():
        rt.revoked = True

    await log_admin_action(db, admin.id, "temp_password", target_user_id=user_id, details={"email": user.email}, request=request)
    await db.commit()

    return {"ok": True, "temp_password": temp_pw}


class StatusUpdate(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}/status")
@limiter.limit("30/minute")
async def update_user_status(user_id: uuid.UUID, data: StatusUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Du kannst dich nicht selbst sperren.")

    user.is_active = data.is_active

    # If deactivating, revoke all sessions
    if not data.is_active:
        rt_result = await db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        )
        for rt in rt_result.scalars().all():
            rt.revoked = True

    await log_admin_action(db, admin.id, "update_user_status", target_user_id=user_id,
                           details={"email": user.email, "is_active": data.is_active}, request=request)
    await db.commit()
    return {"ok": True, "is_active": user.is_active}


class AdminUpdate(BaseModel):
    is_admin: bool


@router.patch("/users/{user_id}/admin")
@limiter.limit("30/minute")
async def update_user_admin(user_id: uuid.UUID, data: AdminUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    if user.id == admin.id and not data.is_admin:
        raise HTTPException(status_code=400, detail="Du kannst dir nicht selbst das Admin-Recht entziehen.")

    # Ensure at least one admin remains
    if not data.is_admin:
        admin_count = await db.execute(
            select(func.count()).select_from(User).where(User.is_admin == True, User.id != user.id)
        )
        if (admin_count.scalar() or 0) < 1:
            raise HTTPException(status_code=400, detail="Mindestens ein Admin muss existieren.")

    user.is_admin = data.is_admin
    await log_admin_action(db, admin.id, "update_user_admin", target_user_id=user_id,
                           details={"email": user.email, "is_admin": data.is_admin}, request=request)
    await db.commit()
    return {"ok": True, "is_admin": user.is_admin}


@router.delete("/users/{user_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_user_endpoint(user_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Du kannst deinen eigenen Account nicht löschen.")

    await log_admin_action(db, admin.id, "delete_user", target_user_id=user_id,
                           details={"email": user.email}, request=request)

    from services.user_service import delete_user
    await delete_user(db, user.id)
    await db.commit()


# --- Admin Settings ---

@router.get("/settings")
async def get_admin_settings(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    result = await db.execute(select(AppSetting))
    settings = {s.key: s.value for s in result.scalars().all()}
    return {"registration_mode": settings.get("registration_mode", "open")}


class AdminSettingsUpdate(BaseModel):
    registration_mode: str


@router.patch("/settings")
@limiter.limit("30/minute")
async def update_admin_settings(data: AdminSettingsUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    if data.registration_mode not in ("open", "invite_only", "disabled"):
        raise HTTPException(status_code=400, detail="Ungültiger Registrierungsmodus")

    result = await db.execute(select(AppSetting).where(AppSetting.key == "registration_mode"))
    setting = result.scalars().first()
    if setting:
        setting.value = data.registration_mode
        setting.updated_at = utcnow()
        setting.updated_by = admin.id
    else:
        db.add(AppSetting(key="registration_mode", value=data.registration_mode, updated_at=utcnow(), updated_by=admin.id))

    await log_admin_action(db, admin.id, "update_settings",
                           details={"registration_mode": data.registration_mode}, request=request)
    await db.commit()
    return {"ok": True, "registration_mode": data.registration_mode}


# --- Invite Codes ---

@router.get("/invite-codes")
async def list_invite_codes(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    result = await db.execute(select(InviteCode).order_by(InviteCode.created_at.desc()))
    codes = result.scalars().all()

    code_list = []
    for c in codes:
        used_email = None
        if c.used_by:
            user_result = await db.execute(select(User.email).where(User.id == c.used_by))
            used_email = user_result.scalar()

        code_list.append({
            "id": str(c.id),
            "code": c.code,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "used_by_email": used_email,
            "used_at": c.used_at.isoformat() if c.used_at else None,
            "is_active": c.is_active and c.used_by is None,
        })

    return {"codes": code_list}


@router.post("/invite-codes")
@limiter.limit("30/minute")
async def create_invite_code(request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    year = utcnow().strftime("%Y")
    suffix = secrets.token_hex(2).upper()
    code = f"OPEN-FO-{year}-{suffix}"

    invite = InviteCode(code=code, created_by=admin.id)
    db.add(invite)
    await log_admin_action(db, admin.id, "create_invite_code", details={"code": code}, request=request)
    await db.commit()
    await db.refresh(invite)

    return {"id": str(invite.id), "code": invite.code, "created_at": invite.created_at.isoformat()}


@router.delete("/invite-codes/{code_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_invite_code(code_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    invite = await db.get(InviteCode, code_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Code nicht gefunden")
    invite.is_active = False
    await log_admin_action(db, admin.id, "delete_invite_code", details={"code": invite.code}, request=request)
    await db.commit()


# --- Audit Log ---

@router.get("/audit-log")
async def get_audit_log(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Return paginated admin audit log entries."""
    offset = (page - 1) * per_page

    # Total count
    count_result = await db.execute(select(func.count()).select_from(AdminAuditLog))
    total = count_result.scalar() or 0

    # Fetch entries with admin email via join
    result = await db.execute(
        select(AdminAuditLog, User.email)
        .outerjoin(User, AdminAuditLog.admin_id == User.id)
        .order_by(desc(AdminAuditLog.created_at))
        .offset(offset)
        .limit(per_page)
    )

    entries = []
    for entry, admin_email in result:
        entries.append({
            "id": str(entry.id),
            "admin_id": str(entry.admin_id) if entry.admin_id else None,
            "admin_email": admin_email,
            "action": entry.action,
            "target_user_id": str(entry.target_user_id) if entry.target_user_id else None,
            "details": entry.details,
            "ip_address": entry.ip_address,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        })

    return {
        "entries": entries,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }
