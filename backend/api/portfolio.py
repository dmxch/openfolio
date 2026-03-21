import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.position import Position
from models.user import User
from services.portfolio_service import get_portfolio_summary
from services.auth_service import decrypt_value

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

from services import cache as app_cache
_SUMMARY_TTL = 30  # seconds


def invalidate_portfolio_cache(user_id: str) -> None:
    """Invalidate the cached portfolio summary for a user. Call after any write that changes portfolio data."""
    app_cache.delete(f"portfolio_summary:{user_id}")


def _decrypt_field(value: str | None) -> str | None:
    """Decrypt a Fernet-encrypted field, returning plaintext or the original value for legacy data."""
    if not value:
        return None
    try:
        return decrypt_value(value)
    except Exception:
        return value  # Legacy plaintext


def _decrypt_and_mask_iban(encrypted_iban: str | None) -> str | None:
    """Decrypt an encrypted IBAN and return only the last 4 characters visible."""
    if not encrypted_iban:
        return None
    try:
        plain = decrypt_value(encrypted_iban)
        if len(plain) > 4:
            return "•" * (len(plain) - 4) + plain[-4:]
        return plain
    except Exception as e:
        # If decryption fails, it may be a plaintext IBAN (legacy data)
        logger.debug(f"IBAN decryption failed, treating as plaintext: {e}")
        if len(encrypted_iban) > 4:
            return "•" * (len(encrypted_iban) - 4) + encrypted_iban[-4:]
        return encrypted_iban


@router.get("/summary")
async def portfolio_summary(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cache_key = f"portfolio_summary:{user.id}"
    cached = app_cache.get(cache_key)
    if cached:
        return cached
    summary = await get_portfolio_summary(db, user.id)
    # Enrich positions with bank_name/iban and 24h change (not in portfolio_service)
    if summary.get("positions"):
        pos_ids = [p["id"] for p in summary["positions"]]
        result = await db.execute(
            select(Position.id, Position.bank_name, Position.iban, Position.coingecko_id,
                   Position.yfinance_ticker, Position.ticker)
            .where(Position.id.in_(pos_ids))
        )
        extra = {str(r.id): r for r in result}
        for p in summary["positions"]:
            e = extra.get(p["id"])
            if not e:
                continue
            p["bank_name"] = _decrypt_field(e.bank_name)
            p["iban"] = _decrypt_and_mask_iban(e.iban)
            # 24h change from cached price data
            if e.coingecko_id:
                crypto_data = app_cache.get(f"crypto:{e.coingecko_id}")
                p["change_pct_24h"] = crypto_data.get("change_pct") if crypto_data else None
            else:
                yf_ticker = e.yfinance_ticker or e.ticker
                price_data = app_cache.get(f"price:{yf_ticker}")
                p["change_pct_24h"] = price_data.get("change_pct") if price_data else None
    app_cache.set(cache_key, summary, ttl=_SUMMARY_TTL)
    return summary
