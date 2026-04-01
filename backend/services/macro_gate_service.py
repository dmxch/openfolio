"""Macro Gate: 7 weighted checks that determine if the market environment is suitable for buying."""

import logging

from services import cache
from services.macro_indicators_service import get_indicator
from services.market_analyzer import get_market_climate
from services.sector_analyzer import get_sector_rotation

logger = logging.getLogger(__name__)

MAX_GATE_SCORE = 9  # Sum of all weights when all data available


def _check_sp500_above_150dma(climate: dict) -> bool:
    """G1: S&P 500 above 150-DMA (weight 2)."""
    checks = climate.get("checks", {})
    return checks.get("price_above_ma150") is True


def _check_sp500_structure(climate: dict) -> bool:
    """G2: S&P 500 shows higher highs / higher lows — approximated by MA50 > MA150 (weight 1)."""
    checks = climate.get("checks", {})
    # HH/HL is approximated by price above MA50 AND MA50 above MA150
    return (checks.get("price_above_ma50") is True and
            checks.get("ma50_above_ma150") is True)


def _check_vix_below_20(climate: dict) -> bool:
    """G3: VIX below 20 (weight 2)."""
    vix = climate.get("vix")
    if vix and vix.get("value") is not None:
        return vix["value"] < 20
    return False


def _check_sector_strong(sector_etf: str | None, rotation: list | None = None) -> bool:
    """G4: Sector 1M return > 0% (weight 1). Individual per ticker's sector."""
    if not sector_etf:
        return True  # No sector info = pass (don't penalize)
    try:
        if rotation is None:
            rotation = get_sector_rotation()
        if isinstance(rotation, list):
            for s in rotation:
                if s.get("etf", "").upper() == sector_etf.upper():
                    return (s.get("perf_1m") or 0) > 0
        return True  # Sector not found = pass
    except Exception as e:
        logger.debug(f"Sector strength check failed for {sector_etf}: {e}")
        return True


def _check_shiller_pe_ok() -> bool | None:
    """G5: Shiller PE below 30 (weight 1). Returns None if data unavailable."""
    ind = get_indicator("shiller_pe")
    if ind and ind.get("value") is not None and ind.get("status") != "unavailable":
        return ind["value"] < 30
    return None  # Not available = exclude from gate


def _check_buffett_ok() -> bool | None:
    """G6: Buffett Indicator below 150% (weight 1). Returns None if data unavailable."""
    ind = get_indicator("buffett_indicator")
    if ind and ind.get("value") is not None and ind.get("status") != "unavailable":
        return ind["value"] < 150
    return None


def _check_yield_curve_ok() -> bool | None:
    """G7: Yield curve not inverted, spread > 0 (weight 1). Returns None if data unavailable."""
    ind = get_indicator("yield_curve")
    if ind and ind.get("value") is not None and ind.get("status") != "unavailable":
        return ind["value"] > 0
    return None


# Map sector names to SPDR ETF tickers
SECTOR_TO_ETF = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Financials": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}


def calculate_macro_gate(sector: str | None = None, climate: dict | None = None, rotation: list | None = None) -> dict:
    """Calculate the macro gate score with 7 weighted checks.

    Args:
        sector: Sector name (e.g. "Technology") to check sector strength.
                Will be mapped to SPDR ETF ticker.
        climate: Pre-loaded market climate dict (avoids redundant get_market_climate calls).
        rotation: Pre-loaded sector rotation list (avoids redundant get_sector_rotation calls).

    Returns:
        Dict with checks, score, max_score, passed, and details.
    """
    cache_key = f"macro_gate:{sector or 'none'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Load climate once if not provided (avoids 3× redundant calls)
    if climate is None:
        climate = get_market_climate()

    sector_etf = SECTOR_TO_ETF.get(sector) if sector else None

    checks = []
    available_max = 0

    gate_definitions = [
        ("sp500_above_150dma", "S&P 500 über 150-DMA", lambda: _check_sp500_above_150dma(climate), 2),
        ("sp500_hh_hl", "S&P 500 HH/HL Struktur", lambda: _check_sp500_structure(climate), 1),
        ("vix_below_20", "VIX unter 20", lambda: _check_vix_below_20(climate), 2),
        ("sector_strong", f"Sektor stark (1M > 0%)", lambda: _check_sector_strong(sector_etf, rotation), 1),
        ("shiller_pe_ok", "Shiller PE unter 30", _check_shiller_pe_ok, 1),
        ("buffett_ok", "Buffett Indicator unter 150%", _check_buffett_ok, 1),
        ("yield_curve_ok", "Zinsstruktur nicht invertiert", _check_yield_curve_ok, 1),
    ]

    import math

    score = 0
    unavailable_count = 0
    for check_id, label, check_fn, weight in gate_definitions:
        try:
            passed = check_fn()
        except Exception as e:
            logger.warning(f"Gate check {check_id} failed: {e}")
            passed = None  # Error = treat as unavailable

        if passed is None:
            # Unavailable — exclude from scoring
            unavailable_count += 1
            checks.append({
                "id": check_id,
                "label": label,
                "passed": None,
                "weight": weight,
                "unavailable": True,
            })
        else:
            if passed:
                score += weight
            available_max += weight
            checks.append({
                "id": check_id,
                "label": label,
                "passed": passed,
                "weight": weight,
                "unavailable": False,
            })

    # Dynamic threshold: ceil(available_max × 2/3)
    threshold = math.ceil(available_max * 2 / 3) if available_max > 0 else 0
    passed = score >= threshold

    result = {
        "checks": checks,
        "score": score,
        "max_score": available_max,
        "threshold": threshold,
        "passed": passed,
        "label": "Bestanden" if passed else "Nicht bestanden",
        "unavailable_count": unavailable_count,
    }

    cache.set(cache_key, result, ttl=900)  # 15 min cache
    return result
