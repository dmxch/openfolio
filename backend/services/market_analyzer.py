import logging

from services.utils import compute_moving_averages
from services.price_service import get_vix

logger = logging.getLogger(__name__)


def get_market_climate() -> dict:
    mas = compute_moving_averages("^GSPC", [50, 100, 150, 200])
    vix = get_vix()
    current = mas.get("current")

    # Sanity check: S&P 500 should be > 100. A value like 1.05 indicates
    # corrupted data from a failed yfinance batch download.
    if current is not None and current < 100:
        logger.warning(f"S&P 500 price {current} is unreasonable — discarding cached data")
        from services import cache as app_cache
        app_cache.delete("ma:^GSPC:50,100,150,200")
        app_cache.delete("close:^GSPC:1y")
        # Recompute from DB fallback
        mas = compute_moving_averages("^GSPC", [50, 100, 150, 200])
        current = mas.get("current")

    # Fallback: get current S&P 500 price from DB cache if yfinance failed
    if current is None:
        from services.cache_service import get_cached_price_sync
        db_cached = get_cached_price_sync("^GSPC", fallback_days=5)
        if db_cached:
            current = db_cached["price"]
            mas["current"] = current

    if current is None:
        return {"status": "unknown", "score": 0, "details": {}, "vix": vix}

    ma50 = mas.get("ma50")
    ma150 = mas.get("ma150")
    ma200 = mas.get("ma200")

    def _fmt(v):
        return f"{v:.2f}" if v is not None else "N/A"

    logger.info(f"S&P 500: {_fmt(current)}, 50-DMA: {_fmt(ma50)}, 150-DMA: {_fmt(ma150)}, 200-DMA: {_fmt(ma200)}")

    checks = {
        "price_above_ma200": current > ma200 if ma200 else None,
        "price_above_ma150": current > ma150 if ma150 else None,
        "price_above_ma50": current > ma50 if ma50 else None,
        "ma50_above_ma200": ma50 > ma200 if ma50 and ma200 else None,
        "ma50_above_ma150": ma50 > ma150 if ma50 and ma150 else None,
        "ma150_above_ma200": ma150 > ma200 if ma150 and ma200 else None,
    }

    score = sum(1 for v in checks.values() if v is True)
    total = sum(1 for v in checks.values() if v is not None)

    # VIX penalty
    if vix and vix["value"] > 25:
        if score > 0:
            score -= 1

    # Safety rule: under 150-DMA = NEVER bullish
    below_150 = ma150 and current < ma150

    if total == 0:
        # No MAs available — derive status from VIX alone
        if vix and vix["value"] > 30:
            status = "bearish"
        elif vix and vix["value"] > 20:
            status = "neutral"
        elif vix and vix["value"] <= 20:
            status = "bullish"
        else:
            status = "unknown"
    elif vix and vix["value"] > 30:
        status = "bearish"
    elif below_150:
        # Under 150-DMA: at best neutral, never bullish
        status = "bearish" if score < 3 else "neutral"
    elif score >= 5:
        status = "bullish"
    elif score >= 3:
        status = "neutral"
    else:
        status = "bearish"

    # VIX regime
    vix_regime = None
    if vix and vix.get("value"):
        vix_val = vix["value"]
        if vix_val < 20:
            vix_regime = "risk_on"
        elif vix_val <= 30:
            vix_regime = "caution"
        else:
            vix_regime = "risk_off"

    return {
        "status": status,
        "score": score,
        "max_score": total,
        "sp500_price": round(current, 2),
        "moving_averages": {k: round(v, 2) if v else None for k, v in mas.items()},
        "checks": checks,
        "vix": vix,
        "vix_regime": vix_regime,
    }
