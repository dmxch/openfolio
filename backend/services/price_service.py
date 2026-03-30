import asyncio
import logging
import time

import yfinance as yf
from yf_patch import yf_download

from config import settings
from services import cache
from services.api_utils import fetch_json, fetch_json_coingecko

logger = logging.getLogger(__name__)


def _in_event_loop() -> bool:
    """Check if we're running inside an asyncio event loop (would block on sync HTTP)."""
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def get_stock_price(ticker: str, allow_live_fetch: bool = True) -> dict | None:
    cache_key = f"price:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # DB cache (today)
    from services.cache_service import get_cached_price_sync
    db_cached = get_cached_price_sync(ticker, fallback_days=0)
    if db_cached and not db_cached.get("stale"):
        result = {"price": db_cached["price"], "currency": db_cached["currency"], "change_pct": 0}
        cache.set(cache_key, result)
        return result

    # Skip blocking yfinance call if running on the event loop —
    # the Worker refreshes prices every 60s, so we fall through to DB fallback.
    if not allow_live_fetch or _in_event_loop():
        db_fallback = get_cached_price_sync(ticker, fallback_days=5)
        if db_fallback:
            result = {"price": db_fallback["price"], "currency": db_fallback["currency"], "change_pct": 0}
            cache.set(cache_key, result)
            return result
        return None

    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        result = {
            "price": round(float(info.last_price), 4),
            "currency": getattr(info, "currency", "USD"),
            "change_pct": round(float((info.last_price - info.previous_close) / info.previous_close * 100), 2)
            if info.previous_close else 0,
        }
        cache.set(cache_key, result)
        return result
    except Exception:
        logger.debug(f"yfinance price fetch failed for {ticker}", exc_info=True)

    # DB fallback (last 5 days)
    db_fallback = get_cached_price_sync(ticker, fallback_days=5)
    if db_fallback:
        result = {"price": db_fallback["price"], "currency": db_fallback["currency"], "change_pct": 0}
        cache.set(cache_key, result)
        return result

    return None


async def get_crypto_price_chf_async(coingecko_id: str) -> dict | None:
    """Async version of get_crypto_price_chf using httpx."""
    cache_key = f"crypto:{coingecko_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        url = f"{settings.coingecko_base_url}/simple/price"
        params = {"ids": coingecko_id, "vs_currencies": "chf", "include_24hr_change": "true"}
        data = await fetch_json_coingecko(url, params=params)
        if coingecko_id not in data:
            return None
        coin = data[coingecko_id]
        result = {
            "price": coin["chf"],
            "currency": "CHF",
            "change_pct": round(coin.get("chf_24h_change", 0), 2),
        }
        cache.set(cache_key, result)
        return result
    except Exception:
        return None


def get_crypto_price_chf(coingecko_id: str) -> dict | None:
    """Sync wrapper — used from sync contexts (portfolio_service etc.)."""
    cache_key = f"crypto:{coingecko_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Don't block the event loop — Worker refreshes crypto prices every 60s
    if _in_event_loop():
        return None

    try:
        import httpx
        url = f"{settings.coingecko_base_url}/simple/price"
        params = {"ids": coingecko_id, "vs_currencies": "chf", "include_24hr_change": "true"}
        resp = httpx.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if coingecko_id not in data:
            return None
        coin = data[coingecko_id]
        result = {
            "price": coin["chf"],
            "currency": "CHF",
            "change_pct": round(coin.get("chf_24h_change", 0), 2),
        }
        cache.set(cache_key, result)
        return result
    except Exception:
        return None


async def get_gold_price_chf_async() -> dict | None:
    """Async version of get_gold_price_chf using httpx."""
    cached = cache.get("gold_chf")
    if cached is not None:
        return cached

    try:
        since = int((time.time() - 7 * 86400) * 1000)
        url = f"https://fsapi.gold.org/api/goldprice/v11/chart/price/chf/oz/{since},"
        data = await fetch_json(url)
        prices = data["chartData"]["CHF"]
        if not prices:
            return None
        current = prices[-1][1]
        prev = prices[-2][1] if len(prices) > 1 else current
        change_pct = ((current / prev) - 1) * 100 if prev else 0
        result = {
            "price": round(current, 2),
            "currency": "CHF",
            "change_pct": round(change_pct, 2),
        }
        logger.info(f"Gold spot price: CHF {current:,.2f}/oz (Gold.org)")
        cache.set("gold_chf", result)
        return result
    except Exception as e:
        logger.warning(f"Gold.org API failed: {e}")
        return None


def get_gold_price_chf() -> dict | None:
    """Sync version — used from sync contexts (portfolio_service, cache_service threads)."""
    cached = cache.get("gold_chf")
    if cached is not None:
        return cached

    # Don't block the event loop — Worker refreshes gold prices every 60s
    if _in_event_loop():
        return None

    try:
        import httpx
        since = int((time.time() - 7 * 86400) * 1000)
        url = f"https://fsapi.gold.org/api/goldprice/v11/chart/price/chf/oz/{since},"
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        prices = data["chartData"]["CHF"]
        if not prices:
            return None
        current = prices[-1][1]
        prev = prices[-2][1] if len(prices) > 1 else current
        change_pct = ((current / prev) - 1) * 100 if prev else 0
        result = {
            "price": round(current, 2),
            "currency": "CHF",
            "change_pct": round(change_pct, 2),
        }
        logger.info(f"Gold spot price: CHF {current:,.2f}/oz (Gold.org)")
        cache.set("gold_chf", result)
        return result
    except Exception as e:
        logger.warning(f"Gold.org API failed: {e}")
        return None


def get_vix() -> dict | None:
    cached = cache.get("vix")
    if cached is not None:
        return cached

    # DB cache
    from services.cache_service import get_cached_price_sync
    db_cached = get_cached_price_sync("^VIX", fallback_days=0)
    if db_cached and not db_cached.get("stale"):
        current = db_cached["price"]
        result = {
            "value": round(current, 2),
            "change": 0,
            "level": "low" if current < 15 else "normal" if current < 20 else "elevated" if current < 30 else "high",
        }
        cache.set("vix", result)
        return result

    try:
        data = yf_download("^VIX", period="5d", progress=False)
        if data.empty:
            return None
        close = data["Close"].squeeze()
        current = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else current
        result = {
            "value": round(current, 2),
            "change": round(current - prev, 2),
            "level": "low" if current < 15 else "normal" if current < 20 else "elevated" if current < 30 else "high",
        }
        cache.set("vix", result)
        return result
    except Exception:
        pass

    # DB fallback
    db_fallback = get_cached_price_sync("^VIX", fallback_days=5)
    if db_fallback:
        current = db_fallback["price"]
        return {
            "value": round(current, 2),
            "change": 0,
            "level": "low" if current < 15 else "normal" if current < 20 else "elevated" if current < 30 else "high",
        }

    return None
