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
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db import async_session
from models.api_token import ApiToken
from models.user import User

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "ofk_"
TOKEN_BYTES = 32  # 256 bit entropy
PREFIX_LEN = 12  # first 12 chars shown in UI (e.g. "ofk_a1b2c3d4")

# Starke Referenzen auf Fire-and-forget-Tasks: ohne sie kann der GC einen
# laufenden Task einsammeln und last_used_at wird sporadisch nicht
# aktualisiert (Muster wie ntfy_service._pending; Review 2026-07-02).
_bg_tasks: set[asyncio.Task] = set()

# ``last_used_at`` höchstens einmal je Token und Intervall schreiben. Ohne die
# Drossel kostete jeder externe Request eine zweite Pool-Verbindung und einen
# Commit auf ``api_tokens`` (Vollreview 11/2026, K128).
LAST_USED_WRITE_INTERVAL = timedelta(seconds=60)
# Zeitpunkt des letzten angestossenen Schreibens je Token in diesem Prozess.
# Gleichzeitige Requests sehen alle denselben alten DB-Wert; ohne dieses
# Gedächtnis schriebe jeder von ihnen.
_last_touch: dict[uuid.UUID, datetime] = {}
_LAST_TOUCH_MAX_ENTRIES = 10_000


def _should_touch(token_id: uuid.UUID, last_used_at: datetime | None, now: datetime) -> bool:
    """True, wenn ``last_used_at`` des Tokens jetzt geschrieben werden soll."""
    cutoff = now - LAST_USED_WRITE_INTERVAL
    if last_used_at is not None and last_used_at > cutoff:
        return False
    scheduled = _last_touch.get(token_id)
    if scheduled is not None and scheduled > cutoff:
        return False
    if len(_last_touch) >= _LAST_TOUCH_MAX_ENTRIES:
        _last_touch.clear()
    _last_touch[token_id] = now
    return True


def _hash_token(plaintext: str) -> str:
    """Stable sha256 hash for token lookup."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _generate_token() -> str:
    """Generate a new plaintext API token."""
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(TOKEN_BYTES)}"


VALID_SCOPES = {"read", "write"}


def _normalize_scopes(scopes: list[str] | None) -> list[str]:
    """Validate and normalize a scopes list. Always includes 'read'."""
    if not scopes:
        return ["read"]
    out = []
    for s in scopes:
        s = (s or "").strip()
        if not s:
            continue
        if s not in VALID_SCOPES:
            raise ValueError(f"Ungueltiger Scope: {s}")
        if s not in out:
            out.append(s)
    if "read" not in out:
        out.insert(0, "read")
    return out


async def create_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    expires_in_days: int | None = None,
    scopes: list[str] | None = None,
) -> tuple[ApiToken, str]:
    """Create a new API token. Returns (model, plaintext).

    ``scopes`` defaults to ``['read']`` when omitted. ``'read'`` is always
    included; passing ``['write']`` yields ``['read', 'write']``.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Name darf nicht leer sein")
    if len(name) > 100:
        raise ValueError("Name darf max. 100 Zeichen lang sein")

    normalized_scopes = _normalize_scopes(scopes)

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
        scopes=normalized_scopes,
        expires_at=expires_at,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    return token, plaintext


async def revoke_all_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Revoke (flag, not delete) every API token of a user. Does not commit."""
    from sqlalchemy import update
    await db.execute(
        update(ApiToken).where(ApiToken.user_id == user_id, ApiToken.revoked == False).values(revoked=True)
    )


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
            "scopes": list(t.scopes or ["read"]),
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


async def verify_token(db: AsyncSession, plaintext: str) -> tuple[User, ApiToken] | None:
    """Verify a plaintext token. Returns ``(user, token)`` tuple or ``None``.

    The token instance is returned alongside the user so callers can inspect
    scopes (e.g., ``"write"``) before authorizing mutations. ``last_used_at``
    is updated fire-and-forget (never blocking the request), at most once per
    ``LAST_USED_WRITE_INTERVAL`` and token — the value is accurate to the minute.
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

    # Fire-and-forget ``last_used_at`` update with its own session.
    # We use a separate session intentionally so the request's transaction
    # isolation is not coupled to a side-effect (and so write-tokens can
    # still be verified read-only). In tests with SQLite/StaticPool, the
    # parallel session shares the connection — to avoid racing the
    # request's own commit against this update, the test fixture
    # monkeypatches ``_touch_last_used`` to a no-op.
    if _should_touch(token.id, token.last_used_at, now):
        task = asyncio.create_task(_touch_last_used(token.id, now))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

    return user, token


async def _touch_last_used(token_id: uuid.UUID, ts: datetime) -> None:
    """Update last_used_at in a separate session — never blocks the request."""
    try:
        async with async_session() as db:
            # Ein einzelnes UPDATE: der Token ist in verify_token schon geprüft,
            # ein SELECT davor brächte nur einen weiteren Roundtrip.
            await db.execute(
                update(ApiToken).where(ApiToken.id == token_id).values(last_used_at=ts)
            )
            await db.commit()
    except Exception as e:
        # Der nächste Request darf es wieder versuchen.
        _last_touch.pop(token_id, None)
        logger.debug(f"Failed to update last_used_at for token {token_id}: {e}")
