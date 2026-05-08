"""FastAPI dependency for authentication."""

import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.user import User
from services.auth_service import decode_access_token


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
