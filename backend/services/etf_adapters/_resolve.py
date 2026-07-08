"""OpenFIGI ISIN -> yfinance-Ticker fuer ETF-Holdings-Adapter.

Zweck: Anbieter, deren Holdings-Feed nur eine ISIN traegt (Xtrackers/SPDR/HSBC/
Fidelity), fuer die zwei Ticker-abhaengigen Consumer nutzbar machen:
  - Core-Overlap-Reverse-Lookup (holding_ticker),
  - Sektor-Fallback via classify_tickers_bulk (US-zentrisch).

Deshalb wird — wie beim CUSIP-Resolver (sec_13f_service) — das US-Composite-Listing
bevorzugt; ohne US-Listing bleibt die Row auf dem ISIN-Key (Land/Sektor sind bei
diesen Anbietern ohnehin meist Issuer-nativ und unabhaengig von der Aufloesung).

Keyless-Limits (beobachtet): 10 Jobs/Request, 25 Requests/60s -> 2.5s Pause.
Ergebnisse 30d in Redis gecacht (ISIN->Ticker ist stabile Referenzdaten),
inkl. Negativ-Cache (leerer String) gegen wiederholte Misses.
"""
from __future__ import annotations

import asyncio
import logging

from services import cache
from services.api_utils import get_async_client

logger = logging.getLogger(__name__)

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
_JOBS_PER_REQ = 10
_DELAY = 2.5
_CACHE_TTL = 60 * 60 * 24 * 30  # 30d
_CACHE_PREFIX = "figi:isin:"

_SECTYPE_PRIORITY = [
    "Common Stock", "ADR", "GDR", "Depositary Receipt", "NY Reg Shrs",
    "REIT", "ETP", "Closed-End Fund", "Mutual Fund", "Tracking Stk",
]
_SECTYPE_REJECT = {"Warrant", "Right", "Rights", "Preferred", "Unit"}


def _pick_us_ticker(records: list[dict]) -> str | None:
    """US-Composite-Hauptpapier waehlen (Common Stock vor ADR ...), sonst None."""
    best: str | None = None
    best_rank = 999
    for r in records:
        if r.get("exchCode") != "US":
            continue
        sectype = (r.get("securityType") or "").strip()
        if sectype in _SECTYPE_REJECT:
            continue
        ticker = (r.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        rank = (_SECTYPE_PRIORITY.index(sectype)
                if sectype in _SECTYPE_PRIORITY else 100)
        if rank < best_rank:
            best, best_rank = ticker, rank
    return best.replace("/", "-") if best else None


async def _openfigi_isin_lookup(isins: list[str]) -> dict[str, str]:
    client = get_async_client()
    out: dict[str, str] = {}
    for i in range(0, len(isins), _JOBS_PER_REQ):
        batch = isins[i:i + _JOBS_PER_REQ]
        payload = [{"idType": "ID_ISIN", "idValue": v} for v in batch]
        try:
            resp = await client.post(
                OPENFIGI_URL, json=payload,
                headers={"Content-Type": "application/json"}, timeout=15,
            )
            if resp.status_code == 429:
                logger.warning("OpenFIGI(ISIN) rate-limited (429) — backing off 60s")
                await asyncio.sleep(60)
                resp = await client.post(
                    OPENFIGI_URL, json=payload,
                    headers={"Content-Type": "application/json"}, timeout=15,
                )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("OpenFIGI(ISIN) lookup failed for batch of %d: %s", len(batch), e)
            if i + _JOBS_PER_REQ < len(isins):
                await asyncio.sleep(_DELAY)
            continue
        for isin, entry in zip(batch, data):
            records = entry.get("data") if isinstance(entry, dict) else None
            if records:
                ticker = _pick_us_ticker(records)
                if ticker:
                    out[isin] = ticker
        if i + _JOBS_PER_REQ < len(isins):
            await asyncio.sleep(_DELAY)
    return out


async def resolve_isins(isins: list[str]) -> dict[str, str]:
    """ISIN -> US-yfinance-Ticker (nur Treffer im Dict). Redis-Cache vor OpenFIGI."""
    out: dict[str, str] = {}
    misses: list[str] = []
    seen: set[str] = set()
    for raw in isins:
        v = (raw or "").strip().upper()
        if not v or v in seen:
            continue
        seen.add(v)
        cached = cache.get(f"{_CACHE_PREFIX}{v}")
        if cached is not None:
            if cached:
                out[v] = cached
        else:
            misses.append(v)
    if misses:
        fetched = await _openfigi_isin_lookup(misses)
        for v in misses:
            ticker = fetched.get(v, "")
            cache.set(f"{_CACHE_PREFIX}{v}", ticker, ttl=_CACHE_TTL)
            if ticker:
                out[v] = ticker
    return out
