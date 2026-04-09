"""Fetch next earnings dates from yfinance + Finnhub (rich data)."""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.position import Position
from services import cache
from services.api_utils import fetch_json

logger = logging.getLogger(__name__)

_FINNHUB_EARNINGS_URL = "https://finnhub.io/api/v1/calendar/earnings"

# Label-Mapping fuer die `earnings_time` Raw-Werte, die Finnhub liefert.
# Finnhub benutzt `bmo`/`amc`/`dmh`; leerer String wird auf `unknown` gemappt.
_EARNINGS_TIME_LABELS: dict[str, str] = {
    "bmo": "Before Market Open",
    "amc": "After Market Close",
    "dmh": "During Market Hours",
    "unknown": "Unknown",
}


def get_next_earnings_date(ticker: str) -> datetime | None:
    """Fetch next earnings date for a ticker. Returns None if unavailable."""
    cache_key = f"earnings:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached != "none" else None

    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
            # yfinance returns calendar as a dict with 'Earnings Date' key
            # or as a DataFrame depending on the version
            if isinstance(cal, dict):
                dates = cal.get("Earnings Date")
                if dates and len(dates) > 0:
                    ed = dates[0]
                    if isinstance(ed, str):
                        ed = datetime.fromisoformat(ed)
                    elif hasattr(ed, 'to_pydatetime'):
                        ed = ed.to_pydatetime()
                    cache.set(cache_key, ed, ttl=86400)  # cache 24h
                    return ed
            else:
                # DataFrame format
                if "Earnings Date" in cal.columns:
                    vals = cal["Earnings Date"].tolist()
                    if vals:
                        ed = vals[0]
                        if hasattr(ed, 'to_pydatetime'):
                            ed = ed.to_pydatetime()
                        cache.set(cache_key, ed, ttl=86400)
                        return ed
    except Exception as e:
        logger.debug(f"Could not fetch earnings for {ticker}: {e}")

    cache.set(cache_key, "none", ttl=86400)
    return None


async def refresh_all_earnings(db: AsyncSession, user_id: UUID) -> dict:
    """Fetch and store next earnings dates for all active stock/etf positions.

    Args:
        db: Async database session.
        user_id: The current user's ID.

    Returns:
        Dict with count of updated positions and their details.
    """
    result = await db.execute(
        select(Position).where(
            Position.is_active == True,
            Position.user_id == user_id,
            Position.shares > 0,
            Position.type.in_(["stock", "etf"]),
        )
    )
    positions = result.scalars().all()
    updated: list[dict] = []

    # Parallel fetch with semaphore (max 5 concurrent)
    sem = asyncio.Semaphore(5)

    async def _fetch_earnings(pos: Position) -> dict | None:
        async with sem:
            yf_ticker = pos.yfinance_ticker or pos.ticker
            ed = await asyncio.to_thread(get_next_earnings_date, yf_ticker)
            if ed:
                pos.next_earnings_date = ed
                return {"ticker": pos.ticker, "next_earnings_date": ed.isoformat()}
            return None

    results = await asyncio.gather(
        *[_fetch_earnings(p) for p in positions], return_exceptions=True
    )
    for r in results:
        if isinstance(r, dict):
            updated.append(r)
        elif isinstance(r, Exception):
            logger.debug(f"Earnings fetch failed: {r}")

    await db.commit()
    return {"updated": len(updated), "positions": updated}


# ---------------------------------------------------------------------------
# Rich earnings data (Finnhub primary, yfinance fallback) — used by the
# External-API Endpoint `/portfolio/upcoming-earnings`. NICHT zu verwechseln
# mit `get_next_earnings_date()` oben, das weiterhin vom internen Worker-Job
# fuer den `Position.next_earnings_date`-Indikator genutzt wird.
# ---------------------------------------------------------------------------


async def _fetch_finnhub_earnings(ticker: str, days: int = 60) -> dict | None:
    """Hole strukturierte Earnings-Daten fuer einen Ticker von Finnhub.

    Liefert den fruehesten kommenden Eintrag im Fenster oder None, falls
    kein API-Key gesetzt ist, die Liste leer bleibt oder der HTTP-Call
    fehlschlaegt.
    """
    if not settings.finnhub_api_key:
        return None

    today = date.today()
    params = {
        "from": today.isoformat(),
        "to": (today + timedelta(days=days)).isoformat(),
        "symbol": ticker,
        "token": settings.finnhub_api_key,
    }
    try:
        data = await fetch_json(_FINNHUB_EARNINGS_URL, params=params)
    except Exception as e:
        logger.warning(f"Finnhub earnings fetch failed for {ticker}: {e}")
        return None

    entries = (data or {}).get("earningsCalendar") or []
    if not entries:
        return None

    # Fruehester kommender Eintrag (Finnhub sortiert meist bereits, aber
    # wir sortieren defensiv selbst).
    def _entry_date(e: dict) -> str:
        return e.get("date") or "9999-99-99"

    entries_sorted = sorted(entries, key=_entry_date)
    earliest = entries_sorted[0]

    raw_hour = (earliest.get("hour") or "").strip().lower()
    earnings_time = raw_hour if raw_hour in ("bmo", "amc", "dmh") else "unknown"

    # Finnhub liefert optional ein `tentative`-Flag (1 = unbestaetigt).
    tentative = earliest.get("tentative")
    is_confirmed = not bool(tentative) if tentative is not None else True

    return {
        "earnings_date": earliest.get("date"),
        "earnings_time": earnings_time,
        "eps_estimate": earliest.get("epsEstimate"),
        "revenue_estimate_usd": earliest.get("revenueEstimate"),
        "is_confirmed": is_confirmed,
        "source": "finnhub",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


async def _fetch_rich_earnings(ticker: str) -> dict | None:
    """Hole Rich-Earnings mit Cache + Fallback-Kette (Finnhub -> yfinance)."""
    cache_key = f"earnings:rich:{ticker}:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached != "none" else None

    # Primaerquelle: Finnhub.
    data = await _fetch_finnhub_earnings(ticker)
    if data is not None:
        cache.set(cache_key, data, ttl=86400)
        return data

    # Fallback: yfinance (liefert nur Datum, keine Tageszeit / Schaetzungen).
    try:
        ed = await asyncio.to_thread(get_next_earnings_date, ticker)
    except Exception as e:
        logger.warning(f"yfinance earnings fallback failed for {ticker}: {e}")
        ed = None

    if ed is not None:
        iso_date = ed.date().isoformat() if hasattr(ed, "date") else str(ed)
        data = {
            "earnings_date": iso_date,
            "earnings_time": "unknown",
            "eps_estimate": None,
            "revenue_estimate_usd": None,
            "is_confirmed": False,
            "source": "yfinance",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        cache.set(cache_key, data, ttl=86400)
        return data

    # Beide Quellen haben nichts — negativ cachen, damit der naechste Call
    # in den naechsten 24h nicht erneut Finnhub/yfinance belastet.
    cache.set(cache_key, "none", ttl=86400)
    return None


async def get_upcoming_earnings_for_portfolio(
    db: AsyncSession,
    user_id: UUID,
    days: int = 7,
    include_etfs: bool = True,
) -> dict:
    """Liefert die naechsten Earnings-Termine fuer alle aktiven Positionen.

    Args:
        db: Async DB-Session.
        user_id: User-ID (IDOR-Schutz).
        days: Lookahead-Fenster in Tagen (1..60).
        include_etfs: Wenn False, werden ETFs komplett ignoriert.

    Returns:
        Dict mit `as_of`, `lookahead_days`, `earnings`, `no_earnings_in_window`,
        `warnings`.
    """
    allowed_types = ["stock", "etf"] if include_etfs else ["stock"]

    result = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.is_active == True,  # noqa: E712
            Position.shares > 0,
            Position.type.in_(allowed_types),
        )
    )
    positions = list(result.scalars().all())

    # Dedupliziere auf den yfinance/Finnhub-Ticker — ein und derselbe Ticker
    # kann theoretisch mehrfach im Portfolio sein.
    ticker_to_pos: dict[str, Position] = {}
    for pos in positions:
        key = (pos.yfinance_ticker or pos.ticker or "").strip()
        if not key:
            continue
        if key not in ticker_to_pos:
            ticker_to_pos[key] = pos

    tickers: list[str] = list(ticker_to_pos.keys())

    results: list = []
    if tickers:
        results = await asyncio.gather(
            *[_fetch_rich_earnings(t) for t in tickers],
            return_exceptions=True,
        )

    today = date.today()
    earnings_list: list[dict] = []
    no_earnings: list[str] = []
    warnings: list[str] = []

    for ticker, res in zip(tickers, results):
        pos = ticker_to_pos[ticker]
        display_ticker = pos.ticker or ticker

        if isinstance(res, Exception):
            logger.warning(f"earnings fetch raised for {ticker}: {res}")
            warnings.append(f"earnings_fetch_failed:{display_ticker}")
            continue

        if not res:
            no_earnings.append(display_ticker)
            continue

        raw_date = res.get("earnings_date")
        if not raw_date:
            no_earnings.append(display_ticker)
            continue

        try:
            ed_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            warnings.append(f"earnings_fetch_failed:{display_ticker}")
            continue

        days_until = (ed_date - today).days
        if days_until < 0 or days_until > days:
            no_earnings.append(display_ticker)
            continue

        earnings_time = res.get("earnings_time") or "unknown"
        earnings_list.append(
            {
                "ticker": display_ticker,
                "name": pos.name,
                "type": pos.type.value if pos.type else None,
                "earnings_date": ed_date.isoformat(),
                "days_until": days_until,
                "earnings_time": earnings_time,
                "earnings_time_label": _EARNINGS_TIME_LABELS.get(
                    earnings_time, _EARNINGS_TIME_LABELS["unknown"]
                ),
                "eps_estimate": res.get("eps_estimate"),
                "revenue_estimate_usd": res.get("revenue_estimate_usd"),
                "is_confirmed": bool(res.get("is_confirmed")),
                "source": res.get("source"),
            }
        )

    earnings_list.sort(key=lambda x: (x["earnings_date"], x["ticker"]))
    no_earnings.sort()
    warnings.sort()

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "lookahead_days": days,
        "earnings": earnings_list,
        "no_earnings_in_window": no_earnings,
        "warnings": warnings,
    }
