"""Macro Gate: 7 weighted checks that determine if the market environment is suitable for buying."""

import logging

from services import cache
from services.macro_indicators_service import get_indicator
from services.market_analyzer import get_market_climate
from services.sector_analyzer import get_sector_rotation

logger = logging.getLogger(__name__)

MAX_GATE_SCORE = 9  # Sum of all weights when all data available


def _check_sp500_above_150dma(climate: dict) -> bool | None:
    """G1: S&P 500 above 150-DMA (weight 2). None = Daten fehlen (aus dem Nenner)."""
    val = climate.get("checks", {}).get("price_above_ma150")
    if val is None:
        return None
    return val is True


def _check_sp500_structure(climate: dict) -> bool | None:
    """G2: S&P 500 shows higher highs / higher lows — approximated by MA50 > MA150 (weight 1).

    Missing-Data-Semantik wie G5-G7: None wenn die Inputs fehlen. Kleene-AND —
    ein sicheres False entscheidet auch dann, wenn der zweite Wert fehlt.
    """
    checks = climate.get("checks", {})
    # HH/HL is approximated by price above MA50 AND MA50 above MA150
    price_above_ma50 = checks.get("price_above_ma50")
    ma50_above_ma150 = checks.get("ma50_above_ma150")
    if price_above_ma50 is False or ma50_above_ma150 is False:
        return False
    if price_above_ma50 is None or ma50_above_ma150 is None:
        return None
    return True


def _check_vix_below_20(climate: dict) -> bool | None:
    """G3: VIX below 20 (weight 2). None = Daten fehlen (aus dem Nenner)."""
    vix = climate.get("vix")
    if not vix or vix.get("value") is None:
        return None
    return vix["value"] < 20


def _check_sector_strong(sector_etf: str | None, rotation: list | None = None) -> bool | None:
    """G4: Sector 1M return > 0% (weight 1). Individual per ticker's sector.

    None statt fail-open True bei fehlenden Daten (kein Sektor bekannt, Sektor
    nicht in der Rotation, perf_1m fehlt, Fetch-Fehler) — konsistent mit G5-G7:
    fehlende Daten fallen aus dem Nenner, statt einen Gratis-Punkt zu vergeben.
    """
    if not sector_etf:
        return None  # No sector info = not assessable (exclude from denominator)
    try:
        if rotation is None:
            rotation = get_sector_rotation()
        if isinstance(rotation, list):
            for s in rotation:
                if s.get("etf", "").upper() == sector_etf.upper():
                    perf_1m = s.get("perf_1m")
                    if perf_1m is None:
                        return None
                    return perf_1m > 0
        return None  # Sector not found = not assessable
    except Exception as e:
        logger.debug(f"Sector strength check failed for {sector_etf}: {e}")
        return None


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
    # available_max == 0 (alle Checks ohne Daten) darf NICHT als bestanden
    # durchgehen — vorher unmoeglich (G1-G4 lieferten immer bool), seit der
    # None-Vereinheitlichung ein realer Fall.
    passed = score >= threshold if available_max > 0 else False

    if available_max == 0:
        label = "Keine Daten"
    else:
        label = "Bestanden" if passed else "Nicht bestanden"

    result = {
        "checks": checks,
        "score": score,
        "max_score": available_max,
        "threshold": threshold,
        "passed": passed,
        "label": label,
        "unavailable_count": unavailable_count,
    }

    cache.set(cache_key, result, ttl=900)  # 15 min cache
    return result
