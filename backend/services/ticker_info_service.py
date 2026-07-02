"""Slim yfinance-Ticker-Info (Name/Currency) mit Redis-Cache.

Genutzt von den Positions-Neuanlage-Pfaden in ``api.transactions`` und
``api.orders`` (Audit 2026-07-02, Nit #6: gehört fachlich in services/,
nicht als Router-zu-Router-Import).
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def get_ticker_info_cached(ticker: str) -> dict:
    """Slim yfinance-Info (Name/Currency) fuer Positions-Neuanlagen.

    Geht ueber den thread-safe ``yf_ticker_attr``-Wrapper (statt rohem
    ``yf.Ticker().info``) und cached das Ergebnis 24h in Redis unter
    ``ticker_info:{ticker}`` — Positions-Neuanlagen treffen yfinance damit
    nicht pro Request (Review 2026-07-02, LOW-raw-yf-info). Raises on lookup
    failure — caller handles best-effort fallback.
    """
    from services import cache

    cache_key = f"ticker_info:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from yf_patch import yf_ticker_attr

    info = await asyncio.to_thread(yf_ticker_attr, ticker, "info") or {}
    slim = {
        "shortName": info.get("shortName"),
        "longName": info.get("longName"),
        "currency": info.get("currency"),
    }
    # Leere Lookups (transienter Fehler/unbekannter Ticker) nicht 24h pinnen.
    if any(slim.values()):
        cache.set(cache_key, slim, ttl=86400)
    return slim
