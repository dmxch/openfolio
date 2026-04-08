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
    """Authenticate via X-API-Key header for the external read-only API.

    Returns 401 with a generic message for any failure (missing header,
    invalid token, expired, revoked, or inactive user) — no information leak.
    """
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="API-Key fehlt oder ungültig")

    # Local import to avoid circular dependencies
    from services.api_token_service import verify_token

    user = await verify_token(db, api_key)
    if not user:
        raise HTTPException(status_code=401, detail="API-Key fehlt oder ungültig")

    return user
