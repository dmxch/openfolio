"""Authentication API endpoints."""

import asyncio
import hashlib
import logging
import re
import secrets
import uuid
from datetime import timedelta

from dateutils import utcnow
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from sqlalchemy import delete as sa_delete, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from api.schemas import (
    LoginResponse, RefreshResponse, RegisterResponse, MeResponse,
    SessionResponse, MfaSetupResponse, MfaVerifyResponse, BackupCodesResponse,
    MessageResponse, OkResponse,
)
from utils import get_client_ip, rate_limit_key
from constants.limits import RL_DEFAULT
from api.schemas import ValidateTokenRequest
from config import settings as app_settings
from db import get_db
from models.user import User, RefreshToken, UserSettings
from models.password_reset_token import PasswordResetToken
from models.app_setting import AppSetting, InviteCode, DEFAULT_REGISTRATION_MODE
from models.backup_code import BackupCode
from services.auth_service import (
    hash_password_async, verify_password_safe_async, validate_password,
    create_access_token, create_refresh_token, hash_refresh_token,
    generate_totp_secret, encrypt_totp_secret, decrypt_totp_secret,
    consume_totp_code, get_totp_uri, generate_backup_codes,
    hash_backup_codes_async, verify_backup_code,
    reserve_mfa_attempt, clear_mfa_attempts,
    bump_token_version, invalidate_reset_tokens,
)

logger = logging.getLogger(__name__)

# Starke Referenzen auf Fire-and-forget-Tasks (GC-Schutz, Muster wie
# services/import_service.py::_industry_bg_tasks).
_bg_tasks: set[asyncio.Task] = set()

# Grace-Window fuer Refresh-Token-Reuse nach Rotation (Two-Tab-Race):
# innerhalb dieses Fensters loest ein Replay des soeben rotierten Tokens
# KEINEN Global-Revoke aus — der Nachzuegler bekommt schlicht 401.
_REFRESH_REUSE_GRACE_SECONDS = 30

def build_limiter(storage_uri: str) -> Limiter:
    """Der Rate-Limiter der App. Eigene Funktion, damit Tests dieselbe
    Konstruktion gegen einen anderen Storage prüfen können.

    - key_func=rate_limit_key: Client-IP aus dem X-Forwarded-For-Eintrag des
      letzten vertrauten Proxys (TRUSTED_PROXY_HOPS), IPv6 auf /64 gekürzt.
      request.client.host taugt nicht: hinter dem Proxy ist das für alle
      Clients dieselbe Adresse (Review 2026-06-10, H6).
    - key_style="endpoint": gezählt wird je Endpunkt-Funktion. Der slowapi-
      Standard "url" zählt je konkretem Pfad; jeder neue Wert eines
      Pfadparameters bekäme ein eigenes Budget (Vollreview 11/2026, X02).
    - default_limits: gilt für Routen ohne @limiter.limit. Durchgesetzt wird es
      über die App-Dependency enforce_default_rate_limit in main.py, weil die
      SlowAPIMiddleware Routen aus include_router nicht findet.
    - Timeouts und Fallback: slowapi fragt Redis synchron im Event-Loop. Ohne
      Timeout stünde bei hängendem Redis jeder Worker, ohne Fallback gäbe jede
      limitierte Route 500 (K074). Bei Ausfall zählt jeder Prozess im Speicher
      weiter, bis Redis wieder antwortet.
    """
    return Limiter(
        key_func=rate_limit_key,
        key_style="endpoint",
        default_limits=[RL_DEFAULT],
        storage_uri=storage_uri,
        storage_options={"socket_connect_timeout": 0.5, "socket_timeout": 0.5},
        in_memory_fallback_enabled=True,
    )


limiter = build_limiter(app_settings.redis_url)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- Schemas ---

class RegisterRequest(BaseModel):
    email: str
    password: str
    invite_code: Optional[str] = None
    terms_accepted: bool = False


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
    return setting.value if setting else DEFAULT_REGISTRATION_MODE


@router.get("/registration-mode")
async def registration_mode(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns registration mode and whether SMTP is configured."""
    from services.email_service import has_smtp_configured
    mode = await _get_registration_mode(db)
    return {
        "mode": mode,
        "smtp_configured": has_smtp_configured(),
        "legal": {
            "terms_url": app_settings.legal_terms_url or None,
            "privacy_url": app_settings.legal_privacy_url or None,
            "imprint_url": app_settings.legal_imprint_url or None,
        },
    }


# --- Registration ---

@router.post("/register", status_code=201, response_model=RegisterResponse)
@limiter.limit("5/hour")
async def register(request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check registration mode
    mode = await _get_registration_mode(db)
    if mode == "disabled":
        raise HTTPException(status_code=403, detail="Registrierung ist derzeit geschlossen.")

    # Ohne hinterlegte AGB des Betreibers entfaellt die Pflicht.
    if app_settings.legal_terms_url and not data.terms_accepted:
        raise HTTPException(status_code=422, detail="Bitte akzeptiere die AGB.")

    # E-Mail und Passwort VOR dem Einladungscode prüfen: sonst verrät eine
    # ungültige E-Mail (422 statt 400), ob ein geratener Code gilt (K088).
    email = data.email.strip().lower()
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        raise HTTPException(status_code=422, detail="Ungültige E-Mail-Adresse")

    # Validate password
    errors = validate_password(data.password)
    if errors:
        raise HTTPException(status_code=422, detail=f"Passwort ungültig: {', '.join(errors)}")

    invite = None
    if mode == "invite_only":
        if not data.invite_code:
            raise HTTPException(status_code=400, detail="Einladungscode erforderlich.")
        # strip: die neuen Codes sind Zufallszeichen und werden kopiert, nicht getippt.
        result = await db.execute(
            select(InviteCode).where(InviteCode.code == data.invite_code.strip(), InviteCode.is_active == True, InviteCode.used_by == None)
        )
        invite = result.scalars().first()
        if not invite:
            raise HTTPException(status_code=400, detail="Ungültiger oder bereits eingelöster Einladungscode.")

    # Check uniqueness (timing-safe: always hash to prevent timing oracle)
    existing = await db.execute(select(User).where(func.lower(User.email) == email))
    if existing.scalars().first():
        await hash_password_async("dummy")
        raise HTTPException(status_code=409, detail="Registrierung fehlgeschlagen. Prüfe deine Eingaben oder melde dich an.")

    user = User(email=email, password_hash=await hash_password_async(data.password))
    db.add(user)
    await db.flush()

    # Redeem invite code atomically: the conditional UPDATE decides which of two
    # concurrent registrations gets the code; the loser rolls back its user.
    if invite:
        redeemed = await db.execute(
            update(InviteCode)
            .where(InviteCode.id == invite.id, InviteCode.is_active == True, InviteCode.used_by == None)
            .values(used_by=user.id, used_at=utcnow(), is_active=False)
            .returning(InviteCode.id)
        )
        if redeemed.scalar_one_or_none() is None:
            await db.rollback()
            raise HTTPException(status_code=400, detail="Ungültiger oder bereits eingelöster Einladungscode.")

    # Create default settings
    # Neuanlagen ueberspringen das Bucket-Migrations-Modal.
    user_settings = UserSettings(user_id=user.id, noticed_buckets_migration=True)
    db.add(user_settings)

    # System-Buckets fuer den neuen User anlegen (idempotent)
    from services.bucket_service import create_system_buckets
    await create_system_buckets(db, user.id)

    await db.commit()

    return {"user_id": str(user.id), "email": user.email, "created_at": user.created_at.isoformat()}


# --- Second factor: Versuche je Konto (K089) ---

def _reserve_mfa_attempt(user: User) -> None:
    """Zählt einen Versuch am zweiten Faktor; 429, wenn das Konto dafür gesperrt ist."""
    if not reserve_mfa_attempt(user.id):
        logger.warning(f"Second factor locked for user {user.id}: too many failed attempts")
        raise HTTPException(
            status_code=429,
            detail="Zu viele fehlgeschlagene MFA-Versuche. Bitte in 15 Minuten erneut versuchen.",
        )


def _require_totp(user: User, code: str) -> None:
    """Prüft den TOTP-Code eines angemeldeten Nutzers gegen das Versuchsbudget."""
    _reserve_mfa_attempt(user)
    secret = decrypt_totp_secret(user.totp_secret)
    if not consume_totp_code(user.id, secret, code.strip()):
        logger.warning(f"Second factor failed for user {user.id} (TOTP)")
        raise HTTPException(status_code=401, detail="Ungültiger MFA-Code")
    clear_mfa_attempts(user.id)


# --- Login ---

@router.post("/login")
@limiter.limit("10/15minutes")
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    email = data.email.strip().lower()

    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalars().first()

    # Timing-safe password verification
    pw_hash = user.password_hash if user else None
    valid = await verify_password_safe_async(data.password, pw_hash)
    if not valid:
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account gesperrt. Kontaktiere den Administrator.")

    # MFA check
    if user.mfa_enabled:
        if not data.totp_code:
            return {"mfa_required": True}

        # Erst nach gültigem Passwort: eine Sperre vor der Passwortprüfung verriete,
        # dass es das Konto gibt und dass es MFA nutzt.
        _reserve_mfa_attempt(user)

        code = data.totp_code.strip()
        if len(code) == 17 and '-' in code:
            # Backup code attempt
            valid = await verify_backup_code(db, user.id, code)
            if not valid:
                logger.warning(f"Second factor failed for user {user.id} (backup code)")
                raise HTTPException(status_code=401, detail="Ungültiger Backup-Code")
        else:
            # TOTP code
            try:
                secret = decrypt_totp_secret(user.totp_secret)
            except Exception as e:
                logger.warning(f"TOTP secret decryption failed for user {user.id}: {e}")
                raise HTTPException(status_code=500, detail="MFA-Konfiguration fehlerhaft")
            if not consume_totp_code(user.id, secret, code):
                logger.warning(f"Second factor failed for user {user.id} (TOTP)")
                raise HTTPException(status_code=401, detail="Ungültiger MFA-Code")
        clear_mfa_attempts(user.id)

    # Update last login
    user.last_login_at = utcnow()

    # Generate tokens
    access_token, expires_in = create_access_token(str(user.id), user.email, user.token_version)
    raw_refresh, refresh_hash, refresh_expires = create_refresh_token()

    # Store refresh token
    rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=refresh_expires,
        user_agent=request.headers.get("User-Agent", "")[:500],
        ip_address=get_client_ip(request),
        token_version=user.token_version,
    )
    db.add(rt)
    await db.commit()

    from services.mfa_policy_service import get_mfa_policy, mfa_is_required_for
    policy = await get_mfa_policy(db)
    setup_required = (not user.mfa_enabled) and mfa_is_required_for(user, policy)

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "expires_in": expires_in,
        "mfa_setup_required": setup_required,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "mfa_enabled": user.mfa_enabled,
            "mfa_setup_required": setup_required,
            "is_admin": user.is_admin,
            "force_password_change": user.force_password_change,
        },
    }


# --- Refresh ---

@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit("30/minute")
async def refresh(request: Request, data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_refresh_token(data.refresh_token)

    # Atomic consume: a single conditional UPDATE decides who owns the token, so two
    # concurrent refreshes with the same token can never both succeed.
    consumed = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > utcnow(),
        )
        .values(revoked=True)
        .returning(RefreshToken.user_id, RefreshToken.token_version)
    )
    consumed_row = consumed.first()
    consumed_user_id = consumed_row[0] if consumed_row else None
    consumed_tv = consumed_row[1] if consumed_row else None

    if consumed_user_id is None:
        # No row consumed: replay of a revoked token, or unknown/expired token.
        replayed = (await db.execute(
            select(RefreshToken.user_id, RefreshToken.token_version).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == True,
            )
        )).first()
        if replayed is None:
            raise HTTPException(status_code=401, detail="Ungültiger oder abgelaufener Refresh-Token")

        # Rotiert oder bewusst widerrufen? Ohne eigene Spalte entscheidet die
        # token_version (K034): Jeder Widerruf aller Sitzungen (Passwortwechsel,
        # Logout-all, MFA aus, Admin-Sperre, Diebstahl-Erkennung) erhöht
        # users.token_version, Logout und Einzel-Widerruf löschen die Zeile. Eine
        # widerrufene Zeile mit der AKTUELLEN Version ist also rotiert worden. Trägt
        # sie eine ältere Version, sind ihre Sitzungen längst beendet: nur 401. Der
        # Global-Revoke träfe sonst die Sitzungen, die der Nutzer danach neu
        # geöffnet hat — und liesse sich mit einem alten Token beliebig wiederholen.
        current_tv = (await db.execute(
            select(User.token_version).where(User.id == replayed.user_id)
        )).scalar_one_or_none()
        if current_tv is None or replayed.token_version != current_tv:
            raise HTTPException(status_code=401, detail="Ungültiger oder abgelaufener Refresh-Token")

        # Grace-Window (benignes Two-Tab-Race): direkt nach einer Rotation
        # kann ein zweiter Tab denselben, soeben rotierten Token nochmals
        # einreichen. Der Rotations-Marker (Redis, 30s TTL) unterscheidet das
        # von einem echten Replay — kein Global-Revoke, nur 401 fuer den
        # Nachzuegler. Faellt Redis aus, greift konservativ der bisherige
        # Global-Revoke-Pfad (Review 2026-07-02, LOW-auth-refresh-grace).
        from services import cache
        if cache.get(f"refresh_rotation_grace:{token_hash}") is not None:
            logger.info("Refresh token replay within grace window — no global revoke")
            raise HTTPException(status_code=401, detail="Ungültiger oder abgelaufener Refresh-Token")

        # Token was already used and rotated — possible theft, revoke ALL user tokens
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == replayed.user_id, RefreshToken.revoked == False)
            .values(revoked=True)
        )
        # Auch ausgestellte Access-Tokens entwerten (inkl. dem des Rotations-Gewinners)
        await bump_token_version(db, replayed.user_id)
        await db.commit()
        logger.warning(f"Refresh token reuse detected for user {replayed.user_id} — all sessions revoked")
        raise HTTPException(status_code=401, detail="Token kompromittiert. Alle Sessions beendet. Bitte erneut anmelden.")

    # Load user (old token is already consumed above; rolled back on failure)
    user_result = await db.execute(select(User).where(User.id == consumed_user_id, User.is_active == True))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden")

    # Every revoke-all action bumps users.token_version in the same transaction. A token
    # minted by a refresh running in parallel to such a revoke read the version BEFORE the
    # bump (and was invisible to the revoke's UPDATE under READ COMMITTED), so it carries
    # a stale version and is worthless. The UPDATE above (row lock) runs before this read.
    if consumed_tv != user.token_version:
        await db.commit()  # keep the consumed token revoked
        raise HTTPException(status_code=401, detail="Ungültiger oder abgelaufener Refresh-Token")

    access_token, expires_in = create_access_token(str(user.id), user.email, user.token_version)
    raw_refresh, refresh_hash, refresh_expires = create_refresh_token()

    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=refresh_expires,
        user_agent=request.headers.get("User-Agent", "")[:500],
        ip_address=get_client_ip(request),
        token_version=user.token_version,
    )
    db.add(new_rt)

    # Rotations-Marker fuer das Reuse-Grace-Window VOR dem Commit: ein paralleler
    # zweiter Tab wartet in Postgres auf die Zeilensperre des UPDATE oben und sieht
    # den Token direkt nach unserem Commit als revoked — der Marker muss dann schon
    # stehen, sonst loest das benigne Two-Tab-Race den Global-Revoke aus. Scheitert
    # der Commit, kostet der verwaiste Marker nur 30s ohne Global-Revoke.
    from services import cache
    cache.set(
        f"refresh_rotation_grace:{token_hash}", 1, ttl=_REFRESH_REUSE_GRACE_SECONDS
    )
    await db.commit()

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "expires_in": expires_in,
    }


# --- Logout ---

@router.post("/logout", status_code=204)
@limiter.limit("30/minute")
async def logout(request: Request, data: LogoutRequest, db: AsyncSession = Depends(get_db)):
    # Ohne Access-Token (K151): der Besitz des Refresh-Tokens genügt, um ihn zu
    # widerrufen. Sonst bliebe die Sitzung nach Ablauf des Access-Tokens (15 Min.)
    # trotz «Abmelden» bis zu 30 Tage gültig.
    #
    # Löschen statt markieren (K034): eine abgemeldete Sitzung ist kein rotierter
    # Token, ihre Wiedervorlage darf keinen Global-Revoke auslösen. Rotierte
    # Zeilen (revoked) bleiben stehen — sonst könnte ein Dieb die Spur seines
    # Tokens per Logout tilgen und die Diebstahl-Erkennung im Refresh aushebeln.
    token_hash = hash_refresh_token(data.refresh_token)
    await db.execute(
        sa_delete(RefreshToken).where(RefreshToken.token_hash == token_hash, RefreshToken.revoked == False)
    )
    await db.commit()


@router.post("/logout-all", status_code=204)
@limiter.limit("10/15minutes")
async def logout_all(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
    )
    for rt in result.scalars().all():
        rt.revoked = True
    await bump_token_version(db, user.id)
    await db.commit()


# --- MFA ---

@router.post("/mfa/setup", response_model=MfaSetupResponse)
@limiter.limit("10/15minutes")
async def mfa_setup(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA bereits aktiviert")
    secret = generate_totp_secret()
    uri = get_totp_uri(secret, user.email)
    # Store temporarily encrypted — will be finalized on verify-setup
    user.totp_secret = encrypt_totp_secret(secret)
    await db.commit()
    return {"secret": secret, "qr_code_uri": uri}


@router.post("/mfa/verify-setup", response_model=MfaVerifyResponse)
@limiter.limit("10/15minutes")
async def mfa_verify_setup(request: Request, data: MfaVerifyRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA bereits aktiviert")
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Zuerst /mfa/setup aufrufen")

    # Kein Versuchsbudget: das Secret stammt aus dieser Sitzung, hier rät niemand.
    # Der Zeitschritt gilt trotzdem als verbraucht (kein zweiter Einsatz im Login).
    secret = decrypt_totp_secret(user.totp_secret)
    if not consume_totp_code(user.id, secret, data.totp_code.strip()):
        raise HTTPException(status_code=400, detail="Ungültiger Code")

    user.mfa_enabled = True

    # Generate and store backup codes (hashed)
    await db.execute(sa_delete(BackupCode).where(BackupCode.user_id == user.id))

    backup_codes = generate_backup_codes()
    for code_hash in await hash_backup_codes_async(backup_codes):
        db.add(BackupCode(user_id=user.id, code_hash=code_hash))

    await db.commit()
    return {"mfa_enabled": True, "backup_codes": backup_codes}


@router.post("/mfa/disable")
@limiter.limit("5/15minutes")
async def mfa_disable(request: Request, data: MfaDisableRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA nicht aktiviert")

    if not await verify_password_safe_async(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Falsches Passwort")

    _require_totp(user, data.totp_code)

    user.totp_secret = None
    user.mfa_enabled = False
    # Delete backup codes
    await db.execute(sa_delete(BackupCode).where(BackupCode.user_id == user.id))
    # Wie jeder Bump-Pfad: Refresh-Tokens mit widerrufen (sonst stirbt die eigene
    # Session beim naechsten Refresh still an der veralteten token_version).
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        .values(revoked=True)
    )
    await bump_token_version(db, user.id)
    await db.commit()
    return {"mfa_enabled": False}


@router.post("/mfa/regenerate-backup-codes", response_model=BackupCodesResponse)
@limiter.limit("5/15minutes")
async def regenerate_backup_codes_endpoint(request: Request, data: MfaVerifyRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA nicht aktiviert")

    _require_totp(user, data.totp_code)

    await db.execute(sa_delete(BackupCode).where(BackupCode.user_id == user.id))

    backup_codes = generate_backup_codes()
    for code_hash in await hash_backup_codes_async(backup_codes):
        db.add(BackupCode(user_id=user.id, code_hash=code_hash))

    await db.commit()
    return {"backup_codes": backup_codes}


# --- Account management ---

@router.get("/me", response_model=MeResponse)
async def get_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    backup_count = 0
    if user.mfa_enabled:
        result = await db.execute(
            select(func.count()).select_from(BackupCode).where(
                BackupCode.user_id == user.id, BackupCode.used == False
            )
        )
        backup_count = result.scalar() or 0

    from services.mfa_policy_service import user_needs_mfa_setup
    setup_required = await user_needs_mfa_setup(db, user)

    return {
        "id": str(user.id),
        "email": user.email,
        "mfa_enabled": user.mfa_enabled,
        "mfa_setup_required": setup_required,
        "is_admin": user.is_admin,
        "force_password_change": user.force_password_change,
        "created_at": user.created_at.isoformat(),
        "backup_codes_remaining": backup_count,
    }


@router.post("/change-password")
@limiter.limit("5/15minutes")
async def change_password(request: Request, data: ChangePasswordRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await verify_password_safe_async(data.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Aktuelles Passwort falsch")

    errors = validate_password(data.new_password)
    if errors:
        raise HTTPException(status_code=422, detail=f"Neues Passwort ungültig: {', '.join(errors)}")

    user.password_hash = await hash_password_async(data.new_password)

    # Revoke all existing sessions (force re-login)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        .values(revoked=True)
    )
    await bump_token_version(db, user.id)
    await invalidate_reset_tokens(db, user.id)

    await db.commit()
    return {"ok": True}


@router.post("/change-email")
@limiter.limit("5/15minutes")
async def change_email(request: Request, data: ChangeEmailRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await verify_password_safe_async(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Falsches Passwort")

    email = data.new_email.strip().lower()
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        raise HTTPException(status_code=422, detail="Ungültige E-Mail-Adresse")

    existing = await db.execute(select(User).where(func.lower(User.email) == email))
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="E-Mail bereits vergeben")

    user.email = email
    await db.commit()
    return {"ok": True, "email": email}


@router.get("/sessions", response_model=list[SessionResponse])
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
@limiter.limit("10/15minutes")
async def revoke_all_sessions(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Revoke all active sessions for the current user."""
    from sqlalchemy import update
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        .values(revoked=True)
    )
    await bump_token_version(db, user.id)
    await db.commit()


@router.delete("/sessions/{session_id}", status_code=204)
@limiter.limit("30/minute")
async def revoke_session(request: Request, session_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Löschen statt markieren, nur aktive Zeilen: Begründung siehe logout (K034).
    await db.execute(
        sa_delete(RefreshToken).where(
            RefreshToken.id == session_id,
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,
        )
    )
    await db.commit()


@router.delete("/account", status_code=204)
@limiter.limit("3/15minutes")
async def delete_account(request: Request, data: DeleteAccountRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await verify_password_safe_async(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Falsches Passwort")

    # Der letzte aktive Admin bleibt. Ohne Admin legte der nächste Start mit
    # ADMIN_EMAIL und ADMIN_PASSWORD ein neues Admin-Konto an; die Adresse des
    # gelöschten Kontos wäre bis dahin für jeden Nutzer frei (K091).
    if user.is_admin:
        # Zeilensperre in fester Reihenfolge: löschen sich die zwei letzten Admins
        # gleichzeitig, wartet der zweite und sieht danach nur noch sich selbst.
        active_admin_ids = (await db.execute(
            select(User.id)
            .where(User.is_admin == True, User.is_active == True)  # noqa: E712
            .order_by(User.id)
            .with_for_update()
        )).scalars().all()
        if not any(admin_id != user.id for admin_id in active_admin_ids):
            raise HTTPException(
                status_code=409,
                detail="Das letzte Admin-Konto kann nicht gelöscht werden. "
                       "Gib zuerst einem anderen Konto das Admin-Recht.",
            )

    # Delete all user data and the user itself
    from services.user_service import delete_user
    await delete_user(db, user.id)
    await db.commit()


# --- Password Reset ---


async def _send_reset_email_bg(to_email: str, html: str) -> None:
    """Reset-Mail im Hintergrund senden — SMTP-Latenz darf die Response nicht
    verzoegern (timing-basierte Account-Enumeration, Review 2026-07-02).

    Immer über das globale SMTP (smtp_cfg=None, K090): die SMTP-Konfiguration des
    Kontos lässt sich mit einer laufenden Sitzung ohne Passwort ändern. Wer eine
    Sitzung kapert, leitete den Reset-Link sonst auf den eigenen Mailserver um.
    """
    try:
        from services.email_service import send_email
        await send_email(to_email, "OpenFolio — Passwort zurücksetzen", html, smtp_cfg=None)
    except Exception:
        logger.warning("Password reset email send failed", exc_info=True)


@router.post("/forgot-password")
@limiter.limit("3/hour")
async def forgot_password(request: Request, data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    email = data.email.strip().lower()

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

    # Send email — als Background-Task (starke Referenz): die Response bleibt
    # damit account-unabhaengig schnell, SMTP-Roundtrips leaken kein Timing.
    from services.email_service import build_reset_email_html, has_smtp_configured
    if has_smtp_configured():
        reset_url = f"{app_settings.frontend_url}/reset-password?token={raw_token}"
        html = build_reset_email_html(reset_url)

        task = asyncio.create_task(_send_reset_email_bg(user.email, html))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

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

    user.password_hash = await hash_password_async(data.new_password)
    user.force_password_change = False
    prt.used = True

    # Revoke all refresh tokens (force re-login)
    rt_result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
    )
    for rt in rt_result.scalars().all():
        rt.revoked = True

    await bump_token_version(db, user.id)
    await invalidate_reset_tokens(db, user.id)
    # Forgot-password path: the account may have been compromised, so API keys die too.
    from services.api_token_service import revoke_all_tokens
    await revoke_all_tokens(db, user.id)

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
@limiter.limit("5/15minutes")
async def force_change_password(request: Request, data: ForceChangePasswordRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user.force_password_change:
        raise HTTPException(status_code=400, detail="Keine Passwortänderung erforderlich.")

    errors = validate_password(data.new_password)
    if errors:
        raise HTTPException(status_code=422, detail=f"Passwort ungültig: {', '.join(errors)}")

    user.password_hash = await hash_password_async(data.new_password)
    user.force_password_change = False

    # Revoke all existing sessions (force re-login with new password)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        .values(revoked=True)
    )
    await bump_token_version(db, user.id)
    await invalidate_reset_tokens(db, user.id)

    await db.commit()
    return {"ok": True}
