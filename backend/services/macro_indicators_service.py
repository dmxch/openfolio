"""Macro crash indicators: Shiller PE, Buffett Indicator, Unemployment, Yield Curve, VIX."""

import asyncio
import logging
from datetime import timedelta

from dateutils import utcnow

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from services import cache
from services.api_utils import fetch_json, fetch_text

logger = logging.getLogger(__name__)

# --- Thresholds ---
SHILLER_PE_GREEN = 20
SHILLER_PE_RED = 30
SHILLER_PE_HISTORICAL_AVG = 17.3

BUFFETT_GREEN = 100
BUFFETT_RED = 150
BUFFETT_HISTORICAL_AVG = 120

YIELD_CURVE_GREEN = 0.5
YIELD_CURVE_RED = 0

VIX_GREEN = 20
VIX_RED = 30

UNEMPLOYMENT_LOOKBACK_MONTHS = 3

_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


def _get_fred_api_key() -> str | None:
    """Liefert einen nutzbaren FRED API-Key aus der DB.

    FRED-Indikatoren sind globale Marktdaten (Shiller PE, Buffett, Yield
    Curve, Unemployment, etc.), die fuer alle User identisch sind. Der
    Worker-Job zum Pre-Caching laeuft ohne User-Kontext, deshalb nimmt
    diese Funktion bewusst den ersten verfuegbaren `fred_api_key` aus
    `user_settings` und cached ihn fuer 5 Minuten. Solange mindestens
    ein User einen Key eingetragen hat, profitieren alle vom geteilten
    Cache. Der Env-Var-Fallback wurde im Rahmen der per-user-Key-
    Migration entfernt.
    """
    cached_key = cache.get("fred_api_key")
    if cached_key is not None:
        return cached_key if cached_key != "" else None

    try:
        from db import SyncSessionLocal
        from models.user import UserSettings
        from services.auth_service import decrypt_value

        with SyncSessionLocal() as session:
            result = session.query(UserSettings.fred_api_key).filter(
                UserSettings.fred_api_key.isnot(None)
            ).first()
            if result and result[0]:
                key = decrypt_value(result[0])
                cache.set("fred_api_key", key, ttl=300)
                return key
    except Exception as e:
        logger.warning(f"FRED API Key Abfrage/Entschlüsselung fehlgeschlagen: {e}")

    # Kein User hat einen Key eingetragen — kurzes negativ cachen.
    cache.set("fred_api_key", "", ttl=300)
    return None


async def _fred_get(series_id: str, api_key: str | None = None) -> float | None:
    """Fetch latest value from FRED API."""
    if api_key is None:
        api_key = _get_fred_api_key()
    if not api_key:
        return None
    try:
        data = await fetch_json(
            _FRED_URL,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 5,
            },
            timeout=10,
        )
        observations = data.get("observations", [])
        for obs in observations:
            val = obs.get("value", ".")
            if val != ".":
                return float(val)
        return None
    except Exception as e:
        logger.warning(f"FRED API failed for {series_id}: {e}")
        return None


async def _fred_get_with_date(series_id: str, api_key: str | None = None) -> tuple[float | None, str | None]:
    """Fetch latest value and its date from FRED API."""
    if api_key is None:
        api_key = _get_fred_api_key()
    if not api_key:
        return None, None
    try:
        data = await fetch_json(
            _FRED_URL,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 5,
            },
            timeout=10,
        )
        observations = data.get("observations", [])
        for obs in observations:
            val = obs.get("value", ".")
            if val != ".":
                return float(val), obs.get("date")
        return None, None
    except Exception as e:
        logger.warning(f"FRED API failed for {series_id}: {e}")
        return None, None


async def _fred_find_last_change_date(series_id: str, api_key: str | None = None) -> str | None:
    """Find the date when the FRED series value last changed."""
    if api_key is None:
        api_key = _get_fred_api_key()
    if not api_key:
        return None
    try:
        data = await fetch_json(
            _FRED_URL,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 90,
            },
            timeout=10,
        )
        observations = data.get("observations", [])
        values = [(obs.get("date"), obs.get("value", ".")) for obs in observations if obs.get("value", ".") != "."]
        if len(values) < 2:
            return values[0][0] if values else None
        current_val = values[0][1]
        prev_date = values[0][0]
        for date_str, val in values[1:]:
            if val != current_val:
                return prev_date  # Date of earliest observation with current value
            prev_date = date_str
        return values[-1][0]
    except Exception as e:
        logger.warning(f"FRED last change lookup failed for {series_id}: {e}")
        return None


async def _fred_get_series(series_id: str, limit: int = 6, api_key: str | None = None) -> list[float]:
    """Fetch recent values from FRED API for trend analysis."""
    if api_key is None:
        api_key = _get_fred_api_key()
    if not api_key:
        return []
    try:
        data = await fetch_json(
            _FRED_URL,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
            timeout=10,
        )
        observations = data.get("observations", [])
        values = []
        for obs in observations:
            val = obs.get("value", ".")
            if val != ".":
                values.append(float(val))
        return values
    except Exception as e:
        logger.warning(f"FRED API series failed for {series_id}: {e}")
        return []


async def _scrape_shiller_pe() -> float | None:
    """Scrape current Shiller PE from multpl.com."""
    try:
        from bs4 import BeautifulSoup
        html = await fetch_text(
            "https://www.multpl.com/shiller-pe",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        soup = BeautifulSoup(html, "html.parser")
        big_num = soup.find("div", {"id": "current"})
        if big_num:
            text = big_num.get_text(strip=True)
            # Extract the number (e.g. "38.47" from "Current Shiller PE Ratio is 38.47")
            import re
            match = re.search(r"(\d+\.?\d*)", text)
            if match:
                return float(match.group(1))
        return None
    except Exception as e:
        logger.warning(f"Shiller PE scrape failed: {e}")
        return None


def _compute_status(value: float | None, green_threshold, red_threshold, invert: bool = False) -> str:
    """Determine traffic light status. invert=True means lower is worse (e.g. yield curve)."""
    if value is None:
        return "unavailable"
    if not invert:
        if value < green_threshold:
            return "green"
        elif value <= red_threshold:
            return "yellow"
        else:
            return "red"
    else:
        if value > green_threshold:
            return "green"
        elif value >= red_threshold:
            return "yellow"
        else:
            return "red"


def _unemployment_status(values: list[float]) -> tuple[str, str]:
    """Determine unemployment trend from recent values (newest first)."""
    if len(values) < UNEMPLOYMENT_LOOKBACK_MONTHS:
        return "unavailable", "Keine Daten"
    newest = values[0]
    oldest = values[UNEMPLOYMENT_LOOKBACK_MONTHS - 1]
    diff = newest - oldest
    if diff > 0.3:
        return "red", "Steigend"
    elif diff < -0.3:
        return "green", "Fallend"
    else:
        return "yellow", "Stabil"


STATUS_LABELS = {
    "green": "Normal",
    "yellow": "Warnung",
    "red": "Gefahr",
    "unavailable": "Keine Daten",
}


async def fetch_all_indicators() -> dict:
    """Fetch all 5 macro indicators and return structured response."""
    cache_key = "macro_indicators"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Load FRED API key once and fire all HTTP calls in parallel
    api_key = _get_fred_api_key()

    from services.price_service import get_vix

    results = await asyncio.gather(
        _scrape_shiller_pe(),
        _fred_get("NCBEILQ027S", api_key),
        _fred_get("GDP", api_key),
        _fred_get_series("UNRATE", 6, api_key),
        _fred_get("T10Y2Y", api_key),
        asyncio.to_thread(get_vix),
        _fred_get("BAMLH0A0HYM2", api_key),
        return_exceptions=True,
    )

    def _safe_result(r, default=None):
        return default if isinstance(r, Exception) else r

    shiller_pe = _safe_result(results[0])
    mktcap_millions = _safe_result(results[1])
    gdp_billions = _safe_result(results[2])
    unemployment_values = _safe_result(results[3], [])
    yield_spread = _safe_result(results[4])
    vix_data = _safe_result(results[5])
    credit_spread = _safe_result(results[6])

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning(f"Macro indicator fetch #{i} failed: {r}")

    indicators = []

    # 1. Shiller PE (CAPE)
    shiller_status = _compute_status(shiller_pe, SHILLER_PE_GREEN, SHILLER_PE_RED)
    shiller_label = "Stark überbewertet" if shiller_status == "red" else "Überbewertet" if shiller_status == "yellow" else "Keine Daten" if shiller_status == "unavailable" else "Normal"
    indicators.append({
        "name": "shiller_pe",
        "label": "Shiller PE (CAPE)",
        "value": round(shiller_pe, 2) if shiller_pe else None,
        "unit": "",
        "status": shiller_status,
        "status_label": shiller_label,
        "description": "Zyklisch bereinigtes KGV des S&P 500",
        "thresholds": {"green": f"<{SHILLER_PE_GREEN}", "yellow": f"{SHILLER_PE_GREEN}-{SHILLER_PE_RED}", "red": f">{SHILLER_PE_RED}"},
        "historical_avg": SHILLER_PE_HISTORICAL_AVG,
        "source": "multpl.com",
        "updated_at": utcnow().isoformat(),
    })

    # 2. Buffett Indicator (Total Market Cap / GDP)
    buffett_value = None
    if mktcap_millions is not None and gdp_billions is not None and gdp_billions > 0:
        mktcap_billions = mktcap_millions / 1000
        buffett_value = round((mktcap_billions / gdp_billions) * 100, 1)
        logger.info(f"Buffett Indicator: mktcap={mktcap_millions}M, gdp={gdp_billions}B → {buffett_value}%")
    else:
        logger.warning(f"Buffett Indicator unavailable: mktcap={mktcap_millions}, gdp={gdp_billions}")
    buffett_status = _compute_status(buffett_value, BUFFETT_GREEN, BUFFETT_RED)
    buffett_label = "Stark überbewertet" if buffett_status == "red" else "Überbewertet" if buffett_status == "yellow" else "Keine Daten" if buffett_status == "unavailable" else "Normal"
    indicators.append({
        "name": "buffett_indicator",
        "label": "Buffett Indicator",
        "value": buffett_value,
        "unit": "%",
        "status": buffett_status,
        "status_label": buffett_label,
        "description": "Marktkapitalisierung / BIP der USA",
        "thresholds": {"green": f"<{BUFFETT_GREEN}%", "yellow": f"{BUFFETT_GREEN}-{BUFFETT_RED}%", "red": f">{BUFFETT_RED}%"},
        "historical_avg": BUFFETT_HISTORICAL_AVG,
        "source": "FRED (NCBEILQ027S / GDP)",
        "updated_at": utcnow().isoformat(),
    })

    # 3. Unemployment Rate (Trend)
    current_unemployment = unemployment_values[0] if unemployment_values else None
    unemp_status, unemp_trend = _unemployment_status(unemployment_values)
    indicators.append({
        "name": "unemployment",
        "label": "Arbeitslosenquote",
        "value": current_unemployment,
        "unit": "%",
        "status": unemp_status,
        "status_label": unemp_trend,
        "description": "US-Arbeitslosenquote (3-Monats-Trend)",
        "thresholds": {"green": "Fallend", "yellow": "Stabil", "red": "Steigend (3M-Trend)"},
        "historical_avg": 5.7,
        "source": "FRED (UNRATE)",
        "updated_at": utcnow().isoformat(),
    })

    # 4. Yield Curve (10Y-2Y Treasury Spread)
    yield_status = _compute_status(yield_spread, YIELD_CURVE_GREEN, YIELD_CURVE_RED, invert=True)
    if yield_status == "red":
        yield_label = "Invertiert"
    elif yield_status == "yellow":
        yield_label = "Flach"
    elif yield_status == "unavailable":
        yield_label = "Keine Daten"
    else:
        yield_label = "Normal"
    indicators.append({
        "name": "yield_curve",
        "label": "Zinsstruktur (10Y-2Y)",
        "value": round(yield_spread, 2) if yield_spread is not None else None,
        "unit": "%",
        "status": yield_status,
        "status_label": yield_label,
        "description": "Spread zwischen 10-jähriger und 2-jähriger US-Staatsanleihe",
        "thresholds": {"green": ">0.5% (normal)", "yellow": "0-0.5% (flach)", "red": "<0% (invertiert)"},
        "historical_avg": 1.0,
        "source": "FRED (T10Y2Y)",
        "updated_at": utcnow().isoformat(),
    })

    # 5. VIX
    vix_value = vix_data.get("value") if vix_data else None
    vix_status = _compute_status(vix_value, VIX_GREEN, VIX_RED)
    if vix_status == "red":
        vix_label = "Panik"
    elif vix_status == "yellow":
        vix_label = "Erhöht"
    elif vix_status == "unavailable":
        vix_label = "Keine Daten"
    else:
        vix_label = "Niedrig"
    indicators.append({
        "name": "vix",
        "label": "VIX",
        "value": round(vix_value, 1) if vix_value is not None else None,
        "unit": "",
        "status": vix_status,
        "status_label": vix_label,
        "description": "CBOE Volatility Index — Angstbarometer des Marktes",
        "thresholds": {"green": f"<{VIX_GREEN}", "yellow": f"{VIX_GREEN}-{VIX_RED}", "red": f">{VIX_RED}"},
        "historical_avg": 19.5,
        "source": "Yahoo Finance (^VIX)",
        "updated_at": utcnow().isoformat(),
    })

    # 6. Credit Spread (High Yield)
    if credit_spread is not None:
        if credit_spread < 3.0:
            cs_status = "green"
            cs_label = "Niedrig"
        elif credit_spread <= 5.0:
            cs_status = "yellow"
            cs_label = "Normal"
        elif credit_spread <= 7.0:
            cs_status = "orange"
            cs_label = "Erhöht"
        else:
            cs_status = "red"
            cs_label = "Stress"
    else:
        cs_status = "unavailable"
        cs_label = "Keine Daten"
    indicators.append({
        "name": "credit_spread",
        "label": "Credit Spread (High Yield)",
        "value": round(credit_spread, 2) if credit_spread is not None else None,
        "unit": "%",
        "status": cs_status,
        "status_label": cs_label,
        "description": "ICE BofA US High Yield Spread",
        "thresholds": {"green": "<3%", "yellow": "3-5%", "orange": "5-7%", "red": ">7%"},
        "historical_avg": 4.5,
        "source": "FRED (BAMLH0A0HYM2)",
        "updated_at": utcnow().isoformat(),
    })

    # Overall status — only count available indicators
    red_count = sum(1 for i in indicators if i["status"] == "red")
    yellow_count = sum(1 for i in indicators if i["status"] == "yellow")
    green_count = sum(1 for i in indicators if i["status"] == "green")
    unavailable_count = sum(1 for i in indicators if i["status"] == "unavailable")

    if red_count >= 2:
        overall_status = "red"
        overall_label = "Risk Off"
    elif red_count == 1 or yellow_count >= 3:
        overall_status = "yellow"
        overall_label = "Vorsicht"
    else:
        overall_status = "green"
        overall_label = "Risk On"

    result = {
        "indicators": indicators,
        "overall_status": overall_status,
        "overall_label": overall_label,
        "green_count": green_count,
        "yellow_count": yellow_count,
        "red_count": red_count,
        "unavailable_count": unavailable_count,
        "gate_passed": None,  # Will be set by macro_gate_service
        "updated_at": utcnow().isoformat(),
    }

    # Cache for 15 minutes (VIX refreshes most frequently)
    cache.set(cache_key, result, ttl=900)
    return result


async def fetch_extra_indicators() -> list[dict]:
    """Fetch additional market indicators (oil, fed rate, USD/CHF) — not part of macro gate."""
    cache_key = "extra_indicators"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from services.price_service import get_stock_price

    # Fire all independent calls in parallel
    api_key = _get_fred_api_key()

    results = await asyncio.gather(
        asyncio.to_thread(get_stock_price, "CL=F"),
        asyncio.to_thread(get_stock_price, "BZ=F"),
        _fred_get_with_date("DFF", api_key),
        _fred_find_last_change_date("DFF", api_key),
        asyncio.to_thread(get_stock_price, "USDCHF=X"),
        return_exceptions=True,
    )

    def _safe(r, default=None):
        return default if isinstance(r, Exception) else r

    oil = _safe(results[0])
    brent = _safe(results[1])
    fed_result = _safe(results[2], (None, None))
    fed_rate, fed_date = fed_result if isinstance(fed_result, tuple) else (None, None)
    last_change = _safe(results[3])
    usdchf = _safe(results[4])

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning(f"Extra indicator fetch #{i} failed: {r}")

    indicators = []

    # 1. Oil Price (WTI Crude)
    wti_price = None
    if oil:
        wti_price = round(oil["price"], 2)
        indicators.append({
            "name": "oil_wti",
            "label": "Öl (WTI)",
            "value": wti_price,
            "unit": " USD",
            "change_pct": oil.get("change_pct", 0),
            "source": "Yahoo Finance (CL=F)",
            "updated_at": utcnow().isoformat(),
        })
    else:
        indicators.append({
            "name": "oil_wti",
            "label": "Öl (WTI)",
            "value": None,
            "unit": " USD",
            "change_pct": None,
            "source": "Yahoo Finance (CL=F)",
            "updated_at": utcnow().isoformat(),
        })

    # 1b. Oil Price (Brent Crude)
    brent_price = None
    if brent:
        brent_price = round(brent["price"], 2)
        indicators.append({
            "name": "oil_brent",
            "label": "Öl (Brent)",
            "value": brent_price,
            "unit": " USD",
            "change_pct": brent.get("change_pct", 0),
            "source": "Yahoo Finance (BZ=F)",
            "updated_at": utcnow().isoformat(),
        })
    else:
        indicators.append({
            "name": "oil_brent",
            "label": "Öl (Brent)",
            "value": None,
            "unit": " USD",
            "change_pct": None,
            "source": "Yahoo Finance (BZ=F)",
            "updated_at": utcnow().isoformat(),
        })

    # 1c. WTI-Brent Spread
    if wti_price and brent_price:
        spread_value = round(brent_price - wti_price, 2)
        spread_pct = round((spread_value / wti_price) * 100, 2)
        if spread_value < 0 or spread_value > 10:
            spread_status = "red"
        elif spread_value > 5:
            spread_status = "yellow"
        else:
            spread_status = "green"
        indicators.append({
            "name": "oil_spread",
            "label": "WTI-Brent Spread",
            "value": spread_value,
            "unit": " USD",
            "spread_pct": spread_pct,
            "status": spread_status,
            "source": "Berechnet (BZ=F − CL=F)",
            "updated_at": utcnow().isoformat(),
        })

    # 2. Fed Funds Rate (FRED DFF)
    indicators.append({
        "name": "fed_funds_rate",
        "label": "Fed Funds Rate",
        "value": round(fed_rate, 2) if fed_rate is not None else None,
        "unit": "%",
        "change_pct": None,
        "last_change_date": last_change,
        "source": "FRED (DFF)",
        "updated_at": utcnow().isoformat(),
    })

    # 3. USD/CHF
    if usdchf:
        indicators.append({
            "name": "usd_chf",
            "label": "USD/CHF",
            "value": round(usdchf["price"], 4),
            "unit": "",
            "change_pct": usdchf.get("change_pct", 0),
            "source": "Yahoo Finance (USDCHF=X)",
            "updated_at": utcnow().isoformat(),
        })
    else:
        indicators.append({
            "name": "usd_chf",
            "label": "USD/CHF",
            "value": None,
            "unit": "",
            "change_pct": None,
            "source": "Yahoo Finance (USDCHF=X)",
            "updated_at": utcnow().isoformat(),
        })

    cache.set(cache_key, indicators, ttl=900)
    return indicators


def get_indicator(name: str) -> dict | None:
    """Get a single indicator by name from cached data.

    Returns cached data only — does not trigger a fetch.
    The async fetch_all_indicators() populates this cache.
    """
    cached = cache.get("macro_indicators")
    if cached is None:
        return None
    for ind in cached.get("indicators", []):
        if ind["name"] == name:
            return ind
    return None


def get_cached_indicators() -> dict | None:
    """Return cached macro indicators without fetching (for sync callers)."""
    return cache.get("macro_indicators")


async def persist_indicators_async(db: AsyncSession) -> None:
    """Fetch and persist all indicators to DB cache."""
    from models.macro_indicator_cache import MacroIndicatorCache

    data = await fetch_all_indicators()
    now = utcnow()

    for ind in data.get("indicators", []):
        ttl_hours = 1 if ind["name"] == "vix" else 24
        expires = now + timedelta(hours=ttl_hours)

        existing = await db.get(MacroIndicatorCache, ind["name"])
        if existing:
            existing.value = ind["value"]
            existing.status = ind["status"]
            existing.raw_data = ind
            existing.fetched_at = now
            existing.expires_at = expires
        else:
            entry = MacroIndicatorCache(
                indicator=ind["name"],
                value=ind["value"],
                status=ind["status"],
                raw_data=ind,
                fetched_at=now,
                expires_at=expires,
            )
            db.add(entry)

    await db.commit()
    logger.info(f"Persisted {len(data.get('indicators', []))} macro indicators to DB")
