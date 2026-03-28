"""Authentication API endpoints."""

import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta

from dateutils import utcnow
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from utils import get_client_ip
from api.schemas import ValidateTokenRequest
from config import settings as app_settings
from db import get_db
from models.user import User, RefreshToken, UserSettings
from models.password_reset_token import PasswordResetToken
from models.app_setting import AppSetting, InviteCode
from models.backup_code import BackupCode
from services.auth_service import (
    hash_password, verify_password_safe, validate_password,
    create_access_token, create_refresh_token, hash_refresh_token,
    generate_totp_secret, encrypt_totp_secret, decrypt_totp_secret,
    verify_totp, get_totp_uri, generate_backup_codes,
    hash_backup_code, verify_backup_code,
)

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address, storage_uri=app_settings.redis_url)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- Schemas ---

class RegisterRequest(BaseModel):
    email: str
    password: str
    invite_code: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str
    totp_code: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class MfaVerifyRequest(BaseModel):
    totp_code: str


class MfaDisableRequest(BaseModel):
    password: str
    totp_code: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ChangeEmailRequest(BaseModel):
    password: str
    new_email: str


class DeleteAccountRequest(BaseModel):
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ForceChangePasswordRequest(BaseModel):
    new_password: str


# --- Registration mode check ---


async def _get_registration_mode(db: AsyncSession) -> str:
    result = await db.execute(select(AppSetting).where(AppSetting.key == "registration_mode"))
    setting = result.scalars().first()
    return setting.value if setting else "open"


@router.get("/registration-mode")
async def registration_mode(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns registration mode and whether SMTP is configured."""
    from services.email_service import has_smtp_configured
    mode = await _get_registration_mode(db)
    return {"mode": mode, "smtp_configured": has_smtp_configured()}


# --- Registration ---

@router.post("/register", status_code=201)
@limiter.limit("5/hour")
async def register(request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check registration mode
    mode = await _get_registration_mode(db)
    if mode == "disabled":
        raise HTTPException(status_code=403, detail="Registrierung ist derzeit geschlossen.")

    invite = None
    if mode == "invite_only":
        if not data.invite_code:
            raise HTTPException(status_code=400, detail="Einladungscode erforderlich.")
        result = await db.execute(
            select(InviteCode).where(InviteCode.code == data.invite_code, InviteCode.is_active == True, InviteCode.used_by == None)
        )
        invite = result.scalars().first()
        if not invite:
            raise HTTPException(status_code=400, detail="Ungültiger oder bereits eingelöster Einladungscode.")

    # Validate email format
    email = data.email.strip().lower()
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        raise HTTPException(status_code=422, detail="Ungültige E-Mail-Adresse")

    # Validate password
    errors = validate_password(data.password)
    if errors:
        raise HTTPException(status_code=422, detail=f"Passwort ungültig: {', '.join(errors)}")

    # Check uniqueness (timing-safe: always hash to prevent timing oracle)
    existing = await db.execute(select(User).where(func.lower(User.email) == email))
    if existing.scalars().first():
        hash_password("dummy")
        raise HTTPException(status_code=409, detail="Registrierung fehlgeschlagen. Prüfe deine Eingaben oder melde dich an.")

    user = User(email=email, password_hash=hash_password(data.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Redeem invite code
    if invite:
        invite.used_by = user.id
        invite.used_at = utcnow()
        invite.is_active = False

    # Create default settings
    user_settings = UserSettings(user_id=user.id)
    db.add(user_settings)
    await db.commit()

    return {"user_id": str(user.id), "email": user.email, "created_at": user.created_at.isoformat()}


# --- Login ---

@router.post("/login")
@limiter.limit("10/15minutes")
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    email = data.email.strip().lower()

    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalars().first()

    # Timing-safe password verification
    pw_hash = user.password_hash if user else None
    valid = verify_password_safe(data.password, pw_hash)
    if not valid:
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

    # Check if account is locked
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account gesperrt. Kontaktiere den Administrator.")

    # MFA check
    if user.mfa_enabled:
        if not data.totp_code:
            return {"mfa_required": True}

        code = data.totp_code.strip()
        if len(code) == 17 and '-' in code:
            # Backup code attempt
            valid = await verify_backup_code(db, user.id, code)
            if not valid:
                raise HTTPException(status_code=401, detail="Ungültiger Backup-Code")
        else:
            # TOTP code
            try:
                secret = decrypt_totp_secret(user.totp_secret)
            except Exception as e:
                logger.warning(f"TOTP secret decryption failed for user {user.id}: {e}")
                raise HTTPException(status_code=500, detail="MFA-Konfiguration fehlerhaft")
            if not verify_totp(secret, code):
                raise HTTPException(status_code=401, detail="Ungültiger MFA-Code")

    # Update last login
    user.last_login_at = utcnow()

    # Generate tokens
    access_token, expires_in = create_access_token(str(user.id), user.email)
    raw_refresh, refresh_hash, refresh_expires = create_refresh_token()

    # Store refresh token
    rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=refresh_expires,
        user_agent=request.headers.get("User-Agent", "")[:500],
        ip_address=get_client_ip(request),
    )
    db.add(rt)
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "expires_in": expires_in,
        "mfa_setup_required": user.is_admin and not user.mfa_enabled,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "mfa_enabled": user.mfa_enabled,
            "mfa_setup_required": user.is_admin and not user.mfa_enabled,
            "is_admin": user.is_admin,
            "force_password_change": user.force_password_change,
        },
    }


# --- Refresh ---

@router.post("/refresh")
@limiter.limit("30/minute")
async def refresh(request: Request, data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_refresh_token(data.refresh_token)

    # Check for token reuse (revoked token replay = potential theft)
    revoked_result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == True,
        )
    )
    if revoked_result.scalars().first():
        # Token was already used and revoked — possible theft, revoke ALL user tokens
        revoked_token = (await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )).scalars().first()
        if revoked_token:
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == revoked_token.user_id, RefreshToken.revoked == False)
                .values(revoked=True)
            )
            await db.commit()
            logger.warning(f"Refresh token reuse detected for user {revoked_token.user_id} — all sessions revoked")
        raise HTTPException(status_code=401, detail="Token kompromittiert. Alle Sessions beendet. Bitte erneut anmelden.")

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > utcnow(),
        )
    )
    rt = result.scalars().first()
    if not rt:
        raise HTTPException(status_code=401, detail="Ungültiger oder abgelaufener Refresh-Token")

    # Load user
    user_result = await db.execute(select(User).where(User.id == rt.user_id, User.is_active == True))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden")

    # Revoke old token (rotation)
    rt.revoked = True

    # Create new token pair
    access_token, expires_in = create_access_token(str(user.id), user.email)
    raw_refresh, refresh_hash, refresh_expires = create_refresh_token()

    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=refresh_expires,
        user_agent=request.headers.get("User-Agent", "")[:500],
        ip_address=get_client_ip(request),
    )
    db.add(new_rt)
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "expires_in": expires_in,
    }


# --- Logout ---

@router.post("/logout", status_code=204)
async def logout(data: LogoutRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    token_hash = hash_refresh_token(data.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash, RefreshToken.user_id == user.id)
    )
    rt = result.scalars().first()
    if rt:
        rt.revoked = True
        await db.commit()


@router.post("/logout-all", status_code=204)
async def logout_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
    )
    for rt in result.scalars().all():
        rt.revoked = True
    await db.commit()


# --- MFA ---

@router.post("/mfa/setup")
async def mfa_setup(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA bereits aktiviert")
    secret = generate_totp_secret()
    uri = get_totp_uri(secret, user.email)
    # Store temporarily encrypted — will be finalized on verify-setup
    user.totp_secret = encrypt_totp_secret(secret)
    await db.commit()
    return {"secret": secret, "qr_code_uri": uri}


@router.post("/mfa/verify-setup")
async def mfa_verify_setup(data: MfaVerifyRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA bereits aktiviert")
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Zuerst /mfa/setup aufrufen")

    secret = decrypt_totp_secret(user.totp_secret)
    if not verify_totp(secret, data.totp_code):
        raise HTTPException(status_code=400, detail="Ungültiger Code")

    user.mfa_enabled = True

    # Generate and store backup codes (hashed)
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(BackupCode).where(BackupCode.user_id == user.id))

    backup_codes = generate_backup_codes()
    for code in backup_codes:
        bc = BackupCode(user_id=user.id, code_hash=hash_backup_code(code))
        db.add(bc)

    await db.commit()
    return {"mfa_enabled": True, "backup_codes": backup_codes}


@router.post("/mfa/disable")
async def mfa_disable(data: MfaDisableRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA nicht aktiviert")

    if not verify_password_safe(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Falsches Passwort")

    secret = decrypt_totp_secret(user.totp_secret)
    if not verify_totp(secret, data.totp_code):
        raise HTTPException(status_code=401, detail="Ungültiger MFA-Code")

    user.totp_secret = None
    user.mfa_enabled = False
    # Delete backup codes
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(BackupCode).where(BackupCode.user_id == user.id))
    await db.commit()
    return {"mfa_enabled": False}


@router.post("/mfa/regenerate-backup-codes")
async def regenerate_backup_codes_endpoint(data: MfaVerifyRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA nicht aktiviert")

    secret = decrypt_totp_secret(user.totp_secret)
    if not verify_totp(secret, data.totp_code):
        raise HTTPException(status_code=401, detail="Ungültiger MFA-Code")

    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(BackupCode).where(BackupCode.user_id == user.id))

    backup_codes = generate_backup_codes()
    for code in backup_codes:
        bc = BackupCode(user_id=user.id, code_hash=hash_backup_code(code))
        db.add(bc)

    await db.commit()
    return {"backup_codes": backup_codes}


# --- Account management ---

@router.get("/me")
async def get_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    backup_count = 0
    if user.mfa_enabled:
        result = await db.execute(
            select(func.count()).select_from(BackupCode).where(
                BackupCode.user_id == user.id, BackupCode.used == False
            )
        )
        backup_count = result.scalar() or 0

    return {
        "id": str(user.id),
        "email": user.email,
        "mfa_enabled": user.mfa_enabled,
        "is_admin": user.is_admin,
        "force_password_change": user.force_password_change,
        "created_at": user.created_at.isoformat(),
        "backup_codes_remaining": backup_count,
    }


@router.post("/change-password")
async def change_password(data: ChangePasswordRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not verify_password_safe(data.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Aktuelles Passwort falsch")

    errors = validate_password(data.new_password)
    if errors:
        raise HTTPException(status_code=422, detail=f"Neues Passwort ungültig: {', '.join(errors)}")

    user.password_hash = hash_password(data.new_password)

    # Revoke all existing sessions (force re-login)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        .values(revoked=True)
    )

    await db.commit()
    return {"ok": True}


@router.post("/change-email")
async def change_email(data: ChangeEmailRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not verify_password_safe(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Falsches Passwort")

    email = data.new_email.strip().lower()
    existing = await db.execute(select(User).where(func.lower(User.email) == email))
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="E-Mail bereits vergeben")

    user.email = email
    await db.commit()
    return {"ok": True, "email": email}


@router.get("/sessions")
async def list_sessions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > utcnow(),
        ).order_by(RefreshToken.created_at.desc())
    )
    tokens = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "user_agent": t.user_agent,
            "ip_address": t.ip_address,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tokens
    ]


@router.delete("/sessions", status_code=204)
async def revoke_all_sessions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Revoke all active sessions for the current user."""
    from sqlalchemy import update
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        .values(revoked=True)
    )
    await db.commit()


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(session_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.id == session_id, RefreshToken.user_id == user.id)
    )
    rt = result.scalars().first()
    if rt:
        rt.revoked = True
        await db.commit()


@router.delete("/account", status_code=204)
async def delete_account(data: DeleteAccountRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not verify_password_safe(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Falsches Passwort")

    # Delete all user data and the user itself
    from services.user_service import delete_user
    await delete_user(db, user.id)
    await db.commit()


# --- Password Reset ---

# Rate limit tracking (in-memory, simple)
from cachetools import TTLCache as _TTLCache
_reset_rate_limit = _TTLCache(maxsize=10000, ttl=3600)


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    import time

    email = data.email.strip().lower()

    # Rate limiting: max 3 per email per hour
    now = time.time()
    if email in _reset_rate_limit:
        _reset_rate_limit[email] = [t for t in _reset_rate_limit[email] if now - t < 3600]
        if len(_reset_rate_limit[email]) >= 3:
            return {"message": "Falls ein Account mit dieser E-Mail existiert, wurde ein Link gesendet."}
    else:
        _reset_rate_limit[email] = []

    _reset_rate_limit[email].append(now)

    # Always return same message (timing attack prevention)
    response_msg = "Falls ein Account mit dieser E-Mail existiert, wurde ein Link gesendet."

    # Find user
    result = await db.execute(select(User).where(func.lower(User.email) == email, User.is_active == True))
    user = result.scalars().first()
    if not user:
        return {"message": response_msg}

    # Invalidate existing unused tokens
    existing = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used == False)
    )
    for t in existing.scalars().all():
        t.used = True

    # Generate new token
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    prt = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    db.add(prt)
    await db.commit()

    # Send email
    from services.email_service import send_email, build_reset_email_html, has_smtp_configured
    if has_smtp_configured():
        reset_url = f"{app_settings.frontend_url}/reset-password?token={raw_token}"
        html = build_reset_email_html(reset_url)

        # Try user SMTP first, fall back to global
        from models.smtp_config import SmtpConfig
        smtp_cfg = await db.get(SmtpConfig, user.id)
        await send_email(user.email, "OpenFolio — Passwort zurücksetzen", html, smtp_cfg=smtp_cfg)

    return {"message": response_msg}


@router.post("/reset-password")
@limiter.limit("10/15minutes")
async def reset_password(request: Request, data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hashlib.sha256(data.token.encode()).hexdigest()

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used == False,
            PasswordResetToken.expires_at > utcnow(),
        )
    )
    prt = result.scalars().first()
    if not prt:
        raise HTTPException(status_code=400, detail="Token ungültig oder abgelaufen.")

    # Validate password
    errors = validate_password(data.new_password)
    if errors:
        raise HTTPException(status_code=422, detail=f"Passwort ungültig: {', '.join(errors)}")

    # Update password
    user = await db.get(User, prt.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Token ungültig oder abgelaufen.")

    user.password_hash = hash_password(data.new_password)
    user.force_password_change = False
    prt.used = True

    # Revoke all refresh tokens (force re-login)
    rt_result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
    )
    for rt in rt_result.scalars().all():
        rt.revoked = True

    await db.commit()
    return {"message": "Passwort erfolgreich geändert."}


@router.post("/validate-reset-token")
@limiter.limit("10/15minutes")
async def validate_reset_token(request: Request, data: ValidateTokenRequest, db: AsyncSession = Depends(get_db)):
    """Check if a reset token is still valid (for frontend UX)."""
    token = data.token
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used == False,
            PasswordResetToken.expires_at > utcnow(),
        )
    )
    return {"valid": result.scalars().first() is not None}


# --- Force Password Change ---

@router.post("/force-change-password")
async def force_change_password(data: ForceChangePasswordRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user.force_password_change:
        raise HTTPException(status_code=400, detail="Keine Passwortänderung erforderlich.")

    errors = validate_password(data.new_password)
    if errors:
        raise HTTPException(status_code=422, detail=f"Passwort ungültig: {', '.join(errors)}")

    user.password_hash = hash_password(data.new_password)
    user.force_password_change = False

    # Revoke all existing sessions (force re-login with new password)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        .values(revoked=True)
    )

    await db.commit()
    return {"ok": True}
