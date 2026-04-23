import asyncio
import logging
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from config import settings
from db import get_db
from auth import get_current_user
from models.user import User
from services.ch_macro_service import get_ch_macro_snapshot
from services.market_analyzer import get_market_climate
from services.sector_analyzer import get_sector_rotation, get_sector_holdings
from services.price_service import get_stock_price, get_gold_price_chf, get_vix
from services.tradingview_industries_service import get_latest_industries
from services import cache
from services.api_utils import fetch_json

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

    # 4 key technical checks for display
    checks = climate.get("checks", {})
    tech_checks = [
        {"id": "above_200dma", "label": "S&P 500 über 200-DMA", "passed": checks.get("price_above_ma200")},
        {"id": "above_150dma", "label": "S&P 500 über 150-DMA", "passed": checks.get("price_above_ma150")},
        {"id": "above_50dma", "label": "S&P 500 über 50-DMA", "passed": checks.get("price_above_ma50")},
        {"id": "hh_hl", "label": "S&P 500 HH/HL Struktur", "passed": (
            checks.get("price_above_ma50") is True and checks.get("ma50_above_ma150") is True
        ) if checks.get("price_above_ma50") is not None and checks.get("ma50_above_ma150") is not None else None},
    ]
    tech_score = sum(1 for c in tech_checks if c["passed"] is True)

    # Combined label: macro dominates
    macro_status = macro.get("overall_status", "green")
    if macro_status == "red":
        combined_status = "red"
        combined_label = "Risk Off"
        combined_hint = "Marktumfeld: Kritisch"
    elif macro_status == "yellow" and tech_score >= 3:
        combined_status = "yellow"
        combined_label = "Vorsicht"
        combined_hint = "Marktumfeld: Vorsicht (erhöhte Volatilität)"
    elif macro_status == "yellow" and tech_score < 3:
        combined_status = "red"
        combined_label = "Bearish"
        combined_hint = "Marktumfeld: Negativ (Risk-Off)"
    elif macro_status == "green" and tech_score >= 3:
        combined_status = "green"
        combined_label = "Bullish"
        combined_hint = "Marktumfeld: Positiv (Risk-On)"
    elif macro_status == "green" and tech_score < 3:
        combined_status = "yellow"
        combined_label = "Vorsicht"
        combined_hint = "Marktumfeld: Vorsicht (erhöhte Volatilität)"
    else:
        combined_status = "yellow"
        combined_label = "Neutral"
        combined_hint = "Marktumfeld: Neutral"

    climate["tech_checks"] = tech_checks
    climate["tech_score"] = tech_score
    climate["macro"] = macro
    climate["extra_indicators"] = extra
    climate["gate"] = gate
    climate["combined_status"] = combined_status
    climate["combined_label"] = combined_label
    climate["combined_hint"] = combined_hint
    return climate


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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Branchen-Rotation (US-Industries von TradingView, taeglicher Snapshot).

    Query-Parameter:
    - `period`: Sortier-/Metric-Spalte (1w, 1m, 3m, 6m, ytd, 1y, 5y, 10y).
    - `top=N`: nur die N besten nach `period`.
    - `bottom=N`: nur die N schlechtesten nach `period` (ueberschreibt `order`).
    - `order`: desc (default) oder asc.
    """
    cache_key = (
        f"market:industries:{period}:t{top or 'all'}:b{bottom or 'none'}:{order}:v1"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = await get_latest_industries(
            db, period=period, top=top, bottom=bottom, order=order,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cache.set(cache_key, data, ttl=3600)
    return data


@router.get("/sectors/{etf_ticker}/holdings")
async def sector_holdings(etf_ticker: str, db=Depends(get_db), user: User = Depends(get_current_user)):
    result = await get_sector_holdings(etf_ticker.upper(), db)
    if result is None:
        from fastapi import HTTPException
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
        for ticker in tickers:
            # Check per-ticker cache first (24h TTL)
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
                cache.set(ticker_cache_key, score_data, ttl=86400)
                results[ticker] = score_data
            except Exception as e:
                logger.debug(f"Score failed for {ticker}: {e}")
                results[ticker] = {"score": 0, "max_score": 0, "rating": "", "mansfield_rs": None}
        return results

    scores = await asyncio.to_thread(_compute_all)
    cache.set(batch_cache_key, scores, ttl=86400)
    return scores


@router.get("/macro-indicators")
async def macro_indicators(user: User = Depends(get_current_user)):
    """Get all 5 macro crash indicators with traffic light status."""
    from services.macro_indicators_service import fetch_all_indicators
    from services.macro_gate_service import calculate_macro_gate
    result = await fetch_all_indicators()
    gate = calculate_macro_gate()
    result["gate_passed"] = gate["passed"]
    result["gate"] = gate
    return result


@router.get("/fx/{from_currency}")
async def fx_rate(from_currency: str, to_currency: str = "CHF", user: User = Depends(get_current_user)):
    from services.utils import get_fx_rate
    rate = await asyncio.to_thread(get_fx_rate, from_currency.upper(), to_currency.upper())
    return {"from": from_currency.upper(), "to": to_currency.upper(), "rate": rate}


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
    cached = cache.get("crypto_metrics")
    if cached is not None:
        return cached

    result = {"tier1": {}, "tier2": {}}

    # Fire all independent API calls in parallel
    async def _fetch_global():
        try:
            data = await fetch_json(f"{settings.coingecko_base_url}/global")
            return data.get("data", {})
        except Exception as e:
            logger.warning(f"CoinGecko global failed: {e}")
            return None

    async def _fetch_fng():
        try:
            return await fetch_json("https://api.alternative.me/fng/?limit=1")
        except Exception as e:
            logger.warning(f"Fear & Greed API failed: {e}")
            return None

    async def _fetch_btc_ath():
        try:
            return await fetch_json(
                f"{settings.coingecko_base_url}/coins/bitcoin",
                params={"localization": "false", "tickers": "false", "community_data": "false", "developer_data": "false"},
            )
        except Exception as e:
            logger.warning(f"CoinGecko BTC ATH failed: {e}")
            return None

    global_data, fng_data, btc_data, dxy = await asyncio.gather(
        _fetch_global(),
        _fetch_fng(),
        _fetch_btc_ath(),
        asyncio.to_thread(get_stock_price, "DX-Y.NYB"),
    )

    # Process results
    if global_data:
        result["tier1"]["btc_dominance"] = round(global_data.get("market_cap_percentage", {}).get("btc", 0), 1)

    if fng_data:
        fng = fng_data.get("data", [{}])[0]
        result["tier1"]["fear_greed_value"] = int(fng.get("value", 0))
        result["tier1"]["fear_greed_label"] = fng.get("value_classification", "")

    # Halving countdown (no API call needed)
    halving_date = date(2028, 4, 15)
    days_to_halving = (halving_date - date.today()).days
    result["tier1"]["next_halving_days"] = max(days_to_halving, 0)
    result["tier1"]["next_halving_date"] = "April 2028"

    if dxy:
        result["tier1"]["dxy_value"] = dxy["price"]
        result["tier1"]["dxy_change_pct"] = dxy.get("change_pct", 0)

    if btc_data:
        market = btc_data.get("market_data", {})
        ath_chf = market.get("ath", {}).get("chf")
        current_chf = market.get("current_price", {}).get("chf")
        if ath_chf and current_chf:
            result["tier2"]["btc_ath_chf"] = round(ath_chf, 0)
            result["tier2"]["btc_ath_distance_pct"] = round(((current_chf / ath_chf) - 1) * 100, 1)

    cache.set("crypto_metrics", result, ttl=900)
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
    cache.set(cache_key, data, ttl=21600)  # 6h, gleicher Key wie External
    return data
