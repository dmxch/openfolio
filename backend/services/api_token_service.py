"""External API token service — create, list, revoke, verify.

Tokens are generated as `ofk_<32-byte-urlsafe-base64>` (256 bit entropy).
The plaintext is only ever returned ONCE at creation. Verification uses
sha256 hashing for fast per-request lookup.
"""

import asyncio
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta

from dateutils import utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import async_session
from models.api_token import ApiToken
from models.user import User

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "ofk_"
TOKEN_BYTES = 32  # 256 bit entropy
PREFIX_LEN = 12  # first 12 chars shown in UI (e.g. "ofk_a1b2c3d4")


def _hash_token(plaintext: str) -> str:
    """Stable sha256 hash for token lookup."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _generate_token() -> str:
    """Generate a new plaintext API token."""
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(TOKEN_BYTES)}"


async def create_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    expires_in_days: int | None = None,
) -> tuple[ApiToken, str]:
    """Create a new API token. Returns (model, plaintext)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Name darf nicht leer sein")
    if len(name) > 100:
        raise ValueError("Name darf max. 100 Zeichen lang sein")

    plaintext = _generate_token()
    token_hash = _hash_token(plaintext)
    token_prefix = plaintext[:PREFIX_LEN]

    expires_at: datetime | None = None
    if expires_in_days is not None and expires_in_days > 0:
        expires_at = utcnow() + timedelta(days=int(expires_in_days))

    token = ApiToken(
        user_id=user_id,
        name=name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        expires_at=expires_at,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    return token, plaintext


async def list_tokens(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """List all (non-revoked) tokens for a user — without hash, with prefix only."""
    result = await db.execute(
        select(ApiToken)
        .where(ApiToken.user_id == user_id, ApiToken.revoked == False)
        .order_by(ApiToken.created_at.desc())
    )
    tokens = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "prefix": t.token_prefix,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        }
        for t in tokens
    ]


async def revoke_token(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> bool:
    """Revoke a token. Returns True if found and revoked."""
    result = await db.execute(
        select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user_id)
    )
    token = result.scalars().first()
    if not token:
        return False
    token.revoked = True
    await db.commit()
    return True


async def verify_token(db: AsyncSession, plaintext: str) -> User | None:
    """Verify a plaintext token. Returns the active User or None.

    Updates `last_used_at` fire-and-forget (never blocking the request).
    """
    if not plaintext or not plaintext.startswith(TOKEN_PREFIX):
        return None

    token_hash = _hash_token(plaintext)
    now = utcnow()

    result = await db.execute(
        select(ApiToken, User)
        .join(User, User.id == ApiToken.user_id)
        .where(
            ApiToken.token_hash == token_hash,
            ApiToken.revoked == False,
            User.is_active == True,
        )
    )
    row = result.first()
    if not row:
        return None

    token, user = row
    if token.expires_at is not None and token.expires_at < now:
        return None

    # Fire-and-forget last_used_at update with its own session
    asyncio.create_task(_touch_last_used(token.id, now))

    return user


async def _touch_last_used(token_id: uuid.UUID, ts: datetime) -> None:
    """Update last_used_at in a separate session — never blocks the request."""
    try:
        async with async_session() as db:
            token = await db.get(ApiToken, token_id)
            if token is not None:
                token.last_used_at = ts
                await db.commit()
    except Exception as e:
        logger.debug(f"Failed to update last_used_at for token {token_id}: {e}")
