"""FastAPI dependency for authentication."""

import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.user import User
from services.auth_service import decode_access_token

# Endpoints, die ein User mit offener MFA-Pflicht noch erreichen darf — um
# seinen Status zu lesen, MFA einzurichten, das Passwort (force-)zu aendern oder
# sich abzumelden. Alles andere wird vom MFA-Policy-Gate in get_current_user
# geblockt, bis MFA aktiv ist.
#
# WICHTIG (Lockout-Sicherheit): Diese Pfade muessen exakt die vom Backend
# gesehene /api/...-Form treffen. Das stimmt, weil nginx (frontend/nginx.conf)
# `proxy_pass http://backend:8000;` OHNE Prefix-Strip nutzt und kein root_path
# gesetzt ist. Wird je ein /api-Rewrite oder root_path eingefuehrt, MUESSEN diese
# Pfade angepasst werden — sonst 403en die Enrollment-Endpoints selbst und
# niemand kann sich mehr einrichten (harter Lockout). Test: tests/test_mfa_policy.py.
_MFA_SETUP_EXEMPT_PATHS = frozenset({
    "/api/auth/me",
    "/api/auth/mfa/setup",
    "/api/auth/mfa/verify-setup",
    "/api/auth/logout",
    "/api/auth/logout-all",
    "/api/auth/change-password",
    "/api/auth/force-change-password",
})


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Extract and validate JWT from Authorization header, return User."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")

    token = auth_header[7:]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token ungültig oder abgelaufen")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token ungültig")

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Token ungültig")

    result = await db.execute(select(User).where(User.id == uid, User.is_active == True))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden")

    # MFA-Policy-Erzwingung: Wer laut Policy MFA haben MUSS, es aber noch nicht
    # aktiviert hat, wird von allen geschuetzten Endpoints hart geblockt (403) —
    # ausser den wenigen Enrollment-/Logout-Endpoints (Allowlist oben), sonst
    # koennte sich niemand mehr einrichten. Die externe API (get_api_user) ist
    # bewusst NICHT betroffen. Nur User ohne aktives MFA zahlen die Policy-Abfrage.
    if not user.mfa_enabled and request.url.path not in _MFA_SETUP_EXEMPT_PATHS:
        from services.mfa_policy_service import user_needs_mfa_setup
        if await user_needs_mfa_setup(db, user):
            raise HTTPException(
                status_code=403,
                detail="MFA-Einrichtung erforderlich",
                headers={"X-MFA-Setup-Required": "1"},
            )

    return user


async def get_api_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Authenticate via X-API-Key header for the external API.

    Returns 401 with a generic message for any failure (missing header,
    invalid token, expired, revoked, or inactive user) — no information leak.

    Also stashes the verified ``ApiToken`` instance in ``request.state.api_token``
    so endpoint handlers can call :func:`require_scope` before authorizing
    mutations.
    """
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="API-Key fehlt oder ungültig")

    # Local import to avoid circular dependencies
    from services.api_token_service import verify_token

    result = await verify_token(db, api_key)
    if not result:
        raise HTTPException(status_code=401, detail="API-Key fehlt oder ungültig")

    user, token = result
    request.state.api_token = token
    return user


def require_scope(request: Request, scope: str) -> None:
    """Raise 403 if the API token in this request lacks ``scope``.

    Must be called from inside an endpoint already protected by
    :func:`get_api_user`. The token is read from ``request.state.api_token``;
    if absent (e.g., endpoint misconfigured) we fail closed with 403.
    """
    token = getattr(request.state, "api_token", None)
    scopes = list(getattr(token, "scopes", None) or [])
    if scope not in scopes:
        raise HTTPException(
            status_code=403,
            detail=f"Dieser Token hat keine Schreib-Berechtigung (fehlender Scope: {scope})",
        )
