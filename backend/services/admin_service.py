"""Admin business logic service."""

import hashlib
import secrets
import uuid
from datetime import timedelta

from dateutils import utcnow
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings as app_settings
from models.admin_audit_log import AdminAuditLog
from models.app_setting import AppSetting, InviteCode
from models.password_reset_token import PasswordResetToken
from models.user import User, RefreshToken
from services.audit_service import log_admin_action
from services.auth_service import hash_password


class AdminServiceError(Exception):
    """Base exception for admin service errors."""
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def list_users(db: AsyncSession, admin_id: uuid.UUID, client_ip: str | None = None) -> dict:
    """Return all users with basic metadata (no portfolio data)."""
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

    await log_admin_action(db, admin_id, "list_users", client_ip=client_ip)
    await db.commit()
    return {"users": user_list, "total": len(user_list)}


async def reset_user_password(
    db: AsyncSession,
    admin_id: uuid.UUID,
    user_id: uuid.UUID,
    client_ip: str | None = None,
) -> dict:
    """Send password reset email to user."""
    user = await db.get(User, user_id)
    if not user:
        raise AdminServiceError("User nicht gefunden", status_code=404)

    from services.email_service import send_email, build_reset_email_html, has_smtp_configured

    if not has_smtp_configured():
        raise AdminServiceError("SMTP nicht konfiguriert")

    # Invalidate existing tokens
    existing = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used == False,
        )
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

    await log_admin_action(
        db, admin_id, "reset_password",
        target_user_id=user_id, details={"email": user.email}, client_ip=client_ip,
    )
    await db.commit()

    reset_url = f"{app_settings.frontend_url}/reset-password?token={raw_token}"
    html = build_reset_email_html(reset_url)
    sent = await send_email(user.email, "OpenFolio \u2014 Passwort zur\u00fccksetzen", html)

    return {
        "ok": sent,
        "message": "Reset-Link wurde gesendet." if sent else "E-Mail konnte nicht gesendet werden.",
    }


async def set_temp_password(
    db: AsyncSession,
    admin_id: uuid.UUID,
    user_id: uuid.UUID,
    client_ip: str | None = None,
) -> dict:
    """Set a temporary password for a user and revoke all sessions."""
    user = await db.get(User, user_id)
    if not user:
        raise AdminServiceError("User nicht gefunden", status_code=404)

    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789!@#$%"
    temp_pw = "".join(secrets.choice(alphabet) for _ in range(12))

    user.password_hash = hash_password(temp_pw)
    user.force_password_change = True

    # Revoke all sessions
    rt_result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,
        )
    )
    for rt in rt_result.scalars().all():
        rt.revoked = True

    await log_admin_action(
        db, admin_id, "temp_password",
        target_user_id=user_id, details={"email": user.email}, client_ip=client_ip,
    )
    await db.commit()

    return {"ok": True, "temp_password": temp_pw}


async def update_user_status(
    db: AsyncSession,
    admin_id: uuid.UUID,
    user_id: uuid.UUID,
    is_active: bool,
    client_ip: str | None = None,
) -> dict:
    """Activate or deactivate a user. Revokes sessions on deactivation."""
    user = await db.get(User, user_id)
    if not user:
        raise AdminServiceError("User nicht gefunden", status_code=404)

    if user.id == admin_id:
        raise AdminServiceError("Du kannst dich nicht selbst sperren.")

    user.is_active = is_active

    # If deactivating, revoke all sessions
    if not is_active:
        rt_result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked == False,
            )
        )
        for rt in rt_result.scalars().all():
            rt.revoked = True

    await log_admin_action(
        db, admin_id, "update_user_status",
        target_user_id=user_id,
        details={"email": user.email, "is_active": is_active},
        client_ip=client_ip,
    )
    await db.commit()
    return {"ok": True, "is_active": user.is_active}


async def update_user_admin(
    db: AsyncSession,
    admin_id: uuid.UUID,
    user_id: uuid.UUID,
    is_admin: bool,
    client_ip: str | None = None,
) -> dict:
    """Update admin flag with safety checks (at least one admin must remain)."""
    user = await db.get(User, user_id)
    if not user:
        raise AdminServiceError("User nicht gefunden", status_code=404)

    if user.id == admin_id and not is_admin:
        raise AdminServiceError("Du kannst dir nicht selbst das Admin-Recht entziehen.")

    # Ensure at least one admin remains
    if not is_admin:
        admin_count = await db.execute(
            select(func.count()).select_from(User).where(
                User.is_admin == True,
                User.id != user.id,
            )
        )
        if (admin_count.scalar() or 0) < 1:
            raise AdminServiceError("Mindestens ein Admin muss existieren.")

    user.is_admin = is_admin
    await log_admin_action(
        db, admin_id, "update_user_admin",
        target_user_id=user_id,
        details={"email": user.email, "is_admin": is_admin},
        client_ip=client_ip,
    )
    await db.commit()
    return {"ok": True, "is_admin": user.is_admin}


async def delete_user(
    db: AsyncSession,
    admin_id: uuid.UUID,
    user_id: uuid.UUID,
    client_ip: str | None = None,
) -> None:
    """Delete a user account (cascade). Admin cannot delete themselves."""
    user = await db.get(User, user_id)
    if not user:
        raise AdminServiceError("User nicht gefunden", status_code=404)

    if user.id == admin_id:
        raise AdminServiceError("Du kannst deinen eigenen Account nicht l\u00f6schen.")

    await log_admin_action(
        db, admin_id, "delete_user",
        target_user_id=user_id, details={"email": user.email}, client_ip=client_ip,
    )

    from services.user_service import delete_user as _delete_user
    await _delete_user(db, user.id)
    await db.commit()


async def get_admin_settings(db: AsyncSession) -> dict:
    """Return current admin settings."""
    result = await db.execute(select(AppSetting))
    settings = {s.key: s.value for s in result.scalars().all()}
    return {"registration_mode": settings.get("registration_mode", "open")}


async def update_admin_settings(
    db: AsyncSession,
    admin_id: uuid.UUID,
    registration_mode: str,
    client_ip: str | None = None,
) -> dict:
    """Update admin settings (registration mode)."""
    if registration_mode not in ("open", "invite_only", "disabled"):
        raise AdminServiceError("Ung\u00fcltiger Registrierungsmodus")

    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "registration_mode")
    )
    setting = result.scalars().first()
    if setting:
        setting.value = registration_mode
        setting.updated_at = utcnow()
        setting.updated_by = admin_id
    else:
        db.add(AppSetting(
            key="registration_mode",
            value=registration_mode,
            updated_at=utcnow(),
            updated_by=admin_id,
        ))

    await log_admin_action(
        db, admin_id, "update_settings",
        details={"registration_mode": registration_mode}, client_ip=client_ip,
    )
    await db.commit()
    return {"ok": True, "registration_mode": registration_mode}


async def list_invite_codes(db: AsyncSession) -> dict:
    """Return all invite codes with used_by email (batch-loaded)."""
    result = await db.execute(
        select(InviteCode).order_by(InviteCode.created_at.desc())
    )
    codes = result.scalars().all()

    # Batch-load used_by emails to avoid N+1 queries
    used_by_ids = [c.used_by for c in codes if c.used_by]
    email_map: dict[uuid.UUID, str] = {}
    if used_by_ids:
        email_result = await db.execute(
            select(User.id, User.email).where(User.id.in_(used_by_ids))
        )
        email_map = {row.id: row.email for row in email_result}

    code_list = []
    for c in codes:
        code_list.append({
            "id": str(c.id),
            "code": c.code,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "used_by_email": email_map.get(c.used_by) if c.used_by else None,
            "used_at": c.used_at.isoformat() if c.used_at else None,
            "is_active": c.is_active and c.used_by is None,
        })

    return {"codes": code_list}


async def create_invite_code(
    db: AsyncSession,
    admin_id: uuid.UUID,
    client_ip: str | None = None,
) -> dict:
    """Generate a new invite code."""
    year = utcnow().strftime("%Y")
    suffix = secrets.token_hex(2).upper()
    code = f"OPEN-FO-{year}-{suffix}"

    invite = InviteCode(code=code, created_by=admin_id)
    db.add(invite)
    await log_admin_action(
        db, admin_id, "create_invite_code",
        details={"code": code}, client_ip=client_ip,
    )
    await db.commit()
    await db.refresh(invite)

    return {
        "id": str(invite.id),
        "code": invite.code,
        "created_at": invite.created_at.isoformat(),
        "is_active": True,
        "used_by_email": None,
        "used_at": None,
    }


async def delete_invite_code(
    db: AsyncSession,
    admin_id: uuid.UUID,
    code_id: uuid.UUID,
    client_ip: str | None = None,
) -> None:
    """Deactivate an invite code."""
    invite = await db.get(InviteCode, code_id)
    if not invite:
        raise AdminServiceError("Code nicht gefunden", status_code=404)

    invite.is_active = False
    await log_admin_action(
        db, admin_id, "delete_invite_code",
        details={"code": invite.code}, client_ip=client_ip,
    )
    await db.commit()


async def get_audit_log(
    db: AsyncSession,
    page: int,
    per_page: int,
) -> dict:
    """Return paginated admin audit log entries."""
    offset = (page - 1) * per_page

    # Total count
    count_result = await db.execute(
        select(func.count()).select_from(AdminAuditLog)
    )
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
