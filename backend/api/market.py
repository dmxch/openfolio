import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from api.validation import CurrencyCode
from constants.limits import RL_HEAVY, RL_READ, RL_SEARCH
from db import get_db
from auth import get_current_user
from models.user import User
from services.ch_macro_service import ch_macro_cache_ttl, get_ch_macro_snapshot
from services.market_analyzer import get_market_climate
from services.sector_analyzer import get_sector_rotation, get_sector_holdings
from services.price_service import get_stock_price, get_gold_price_chf, get_vix
from services.tradingview_industries_service import (
    get_latest_industries,
    fetch_industry_members,
    get_industry_name_for_slug,
)
from services import cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/climate")
@limiter.limit("10/minute")
async def market_climate(request: Request, user: User = Depends(get_current_user)):
    from services.macro_indicators_service import fetch_all_indicators, fetch_extra_indicators
    from services.macro_gate_service import calculate_macro_gate

    climate, macro, extra = await asyncio.gather(
        asyncio.to_thread(get_market_climate),
        fetch_all_indicators(),
        fetch_extra_indicators(),
    )
    gate = calculate_macro_gate(climate=climate)

    # Tech-Checks + Risk-Headline + Bewertungs-Badge — gemeinsamer Helper mit dem
    # externen Twin (api/external_v1.py) -> Paritaet by construction.
    from services.market_analyzer import assemble_climate
    return assemble_climate(climate, macro, extra, gate)


@router.get("/sectors")
@limiter.limit("10/minute")
async def sectors(request: Request, user: User = Depends(get_current_user)):
    return await asyncio.to_thread(get_sector_rotation)


@router.get("/vix")
async def vix(user: User = Depends(get_current_user)):
    return await asyncio.to_thread(get_vix)


@router.get("/industries")
@limiter.limit("60/minute")
async def industries(
    request: Request,
    period: str = Query("ytd", pattern="^(1w|1m|3m|6m|ytd|1y|5y|10y)$"),
    top: int | None = Query(None, ge=1, le=200),
    bottom: int | None = Query(None, ge=1, le=200),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    min_mcap: float | None = Query(None, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Branchen-Rotation (US-Industries von TradingView, taeglicher Snapshot).

    Query-Parameter:
    - `period`: Sortier-/Metric-Spalte (1w, 1m, 3m, 6m, ytd, 1y, 5y, 10y).
    - `top=N`: nur die N besten nach `period`.
    - `bottom=N`: nur die N schlechtesten nach `period` (ueberschreibt `order`).
    - `order`: desc (default) oder asc.
    - `min_mcap`: untere MCap-Schwelle in USD (z.B. 1_000_000_000 = $1B). Null/fehlend = kein Filter.

    Kein Antwort-Cache: die Quelle ist ein DB-Snapshot mit rund 129 Zeilen, und
    ein Schlüssel aus `top`, `bottom` und dem frei wählbaren Float `min_mcap`
    legte je Wert einen eigenen Eintrag in Redis und im Prozess-Cache an (K137).
    """
    try:
        return await get_latest_industries(
            db, period=period, top=top, bottom=bottom, order=order,
            min_mcap=min_mcap,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/industries/{slug}/members")
@limiter.limit("30/minute")
async def industry_members(
    request: Request,
    slug: str,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Einzelaktien einer Branche (Drill-down).

    Live von der TradingView-Scanner-API, nach Branche gefiltert und nach
    Marktkapitalisierung absteigend sortiert. 1h gecacht. Der `slug` wird
    serverseitig gegen den letzten Snapshot in einen Branchennamen aufgeloest.
    """
    cache_key = f"market:industry_members:{slug}:l{limit}:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    name = await get_industry_name_for_slug(db, slug)
    if not name:
        raise HTTPException(status_code=404, detail="Branche nicht gefunden")

    try:
        members = await fetch_industry_members(name, limit=limit)
    except Exception as e:  # noqa: BLE001 — Scanner-Fehler/Schema-Aenderung
        logger.warning("industry members fetch failed for %s: %s", slug, e)
        raise HTTPException(status_code=502, detail="Branchen-Daten momentan nicht verfügbar")

    data = {"slug": slug, "name": name, "count": len(members), "members": members}
    cache.set(cache_key, data, ttl=3600)
    return data


@router.get("/sectors/{etf_ticker}/holdings")
@limiter.limit(RL_READ)
async def sector_holdings(request: Request, etf_ticker: str, db=Depends(get_db), user: User = Depends(get_current_user)):
    result = await get_sector_holdings(etf_ticker.upper(), db, user_id=user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="ETF nicht gefunden")
    return result


@router.get("/sectors/{etf_ticker}/scores")
@limiter.limit("5/minute")
async def sector_holding_scores(request: Request, etf_ticker: str, user: User = Depends(get_current_user)):
    """Batch-compute setup scores for all holdings in a sector ETF. Cached 24h."""
    from services.sector_analyzer import SECTOR_ETF_HOLDINGS
    from services.scoring_service import assess_ticker

    holdings = SECTOR_ETF_HOLDINGS.get(etf_ticker.upper())
    if not holdings:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="ETF nicht gefunden")

    # Check for fully cached result
    batch_cache_key = f"sector_scores:{etf_ticker.upper()}"
    cached = cache.get(batch_cache_key)
    if cached is not None:
        return cached

    # Compute scores in thread (blocking yfinance calls)
    tickers = [t for t, _, _ in holdings]

    # Map ETF ticker to sector name for gate check
    etf_sector_map = {
        "XLK": "Technology", "XLV": "Healthcare", "XLF": "Financial Services",
        "XLY": "Consumer Cyclical", "XLP": "Consumer Defensive", "XLE": "Energy",
        "XLI": "Industrials", "XLB": "Basic Materials", "XLRE": "Real Estate",
        "XLU": "Utilities", "XLC": "Communication Services",
    }
    sector = etf_sector_map.get(etf_ticker.upper())

    def _compute_all():
        results = {}
        any_broken = False
        for ticker in tickers:
            # Check per-ticker cache first (24h TTL; broken results are never cached here)
            ticker_cache_key = f"setup_score:{ticker}"
            ticker_cached = cache.get(ticker_cache_key)
            if ticker_cached is not None:
                results[ticker] = ticker_cached
                continue
            try:
                data = assess_ticker(ticker, sector=sector)
                score_data = {
                    "score": data.get("score", 0),
                    "max_score": data.get("max_score", 0),
                    "rating": data.get("rating", ""),
                    "mansfield_rs": data.get("mansfield_rs"),
                    "signal": data.get("signal", ""),
                    "gate_blocked": data.get("gate_blocked", False),
                }
                if data.get("price") is None:
                    # Broken result (transienter yfinance-Fehler/429): NICHT
                    # 24h pinnen — assess_ticker cached den Fall intern bewusst
                    # nur 60s (Review 2026-07-02, M15).
                    any_broken = True
                else:
                    cache.set(ticker_cache_key, score_data, ttl=86400)
                results[ticker] = score_data
            except Exception as e:
                logger.debug(f"Score failed for {ticker}: {e}")
                any_broken = True
                results[ticker] = {"score": 0, "max_score": 0, "rating": "", "mansfield_rs": None}
        return results, any_broken

    scores, any_broken = await asyncio.to_thread(_compute_all)
    # Batch-Key darf Broken-Eintraege ebenfalls nicht 24h einfrieren (M15).
    cache.set(batch_cache_key, scores, ttl=60 if any_broken else 86400)
    return scores


@router.get("/macro-indicators")
@limiter.limit(RL_HEAVY)  # kalter Cache: sieben externe Abrufe im Request-Pfad
async def macro_indicators(request: Request, user: User = Depends(get_current_user)):
    """Get all 5 macro crash indicators with traffic light status."""
    from services.macro_indicators_service import fetch_all_indicators
    from services.macro_gate_service import calculate_macro_gate
    result = await fetch_all_indicators()
    # to_thread: calculate_macro_gate() laedt bei kaltem Cache synchron
    # get_market_climate() -> yf_download() — darf nicht auf dem Event-Loop
    # laufen (Review 2026-07-02, H7).
    gate = await asyncio.to_thread(calculate_macro_gate)
    result["gate_passed"] = gate["passed"]
    result["gate"] = gate
    return result


@router.get("/fx/{from_currency}")
@limiter.limit(RL_SEARCH)  # je neuem Währungscode ein möglicher Yahoo-Abruf
async def fx_rate(
    request: Request,
    from_currency: CurrencyCode,
    to_currency: CurrencyCode = "CHF",
    user: User = Depends(get_current_user),
):
    # CurrencyCode: genau drei Buchstaben, bereits in Grossschreibung.
    from services.utils import get_fx_rate
    rate = await asyncio.to_thread(get_fx_rate, from_currency, to_currency)
    return {"from": from_currency, "to": to_currency, "rate": rate}


@router.get("/precious-metals")
async def precious_metals(user: User = Depends(get_current_user)):
    gold_spot, gold_comex, silver_comex = await asyncio.gather(
        asyncio.to_thread(get_gold_price_chf),
        asyncio.to_thread(get_stock_price, "GC=F"),
        asyncio.to_thread(get_stock_price, "SI=F"),
    )

    gold_silver_ratio = None
    if gold_comex and silver_comex and silver_comex["price"] > 0:
        gold_silver_ratio = round(gold_comex["price"] / silver_comex["price"], 1)

    return {
        "gold_spot_chf": gold_spot,
        "gold_comex_usd": gold_comex,
        "silver_comex_usd": silver_comex,
        "gold_silver_ratio": gold_silver_ratio,
    }


@router.get("/real-estate")
async def real_estate_market(user: User = Depends(get_current_user)):
    from services.property_service import get_real_estate_market_data
    return await get_real_estate_market_data()



@router.get("/crypto-metrics")
@limiter.limit("10/minute")
async def crypto_metrics(request: Request, user: User = Depends(get_current_user)):
    """Krypto-Metriken (BTC-Dominanz, F&G, Halving, DXY, BTC-ATH-Distanz).

    Cache-Schlüssel und Lader teilt sich die Route mit dem externen v1-Endpunkt:
    beide schreiben dieselbe Antwortform unter ``crypto_metrics``.
    """
    cached = cache.get("crypto_metrics")
    if cached is not None:
        return cached
    # Import im Rumpf: api.external_v1 lädt beim Import fast alle API-Module.
    from api.external_v1 import (
        _CRYPTO_METRICS_PARTIAL_TTL,
        _CRYPTO_METRICS_TTL,
        _load_crypto_metrics,
    )
    # Ein Abruf je Prozess: ohne Sperre startete bei kaltem Cache jeder
    # gleichzeitige Request seine eigenen Abrufe bei CoinGecko (K139).
    async with cache.get_key_lock("crypto_metrics"):
        cached = cache.get("crypto_metrics")
        if cached is not None:
            return cached
        result, complete = await _load_crypto_metrics()
        # Ein lückenhaftes Ergebnis (CoinGecko-429) nur kurz halten.
        cache.set(
            "crypto_metrics", result,
            ttl=_CRYPTO_METRICS_TTL if complete else _CRYPTO_METRICS_PARTIAL_TTL,
        )
        return result


@router.get("/macro/ch")
@limiter.limit("60/minute")
async def macro_ch(request: Request, user: User = Depends(get_current_user)) -> dict:
    """Schweizer Makro-Snapshot (SNB, SARON, FX, CH-Inflation, CH-10Y, SMI vs S&P 500).

    Cache-Key wird mit dem externen v1-Endpoint geteilt.
    """
    cache_key = "external:macro:ch:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = await get_ch_macro_snapshot()
    except Exception:
        logger.exception("ch macro snapshot failed")
        raise HTTPException(status_code=503, detail="ch_macro_unavailable")
    # Gleicher Key wie External. Lückenhafte Snapshots nur kurz halten (K146).
    cache.set(cache_key, data, ttl=ch_macro_cache_ttl(data))
    return data
