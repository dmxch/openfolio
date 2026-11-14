"""Dividend tracking via yfinance."""
import logging
from datetime import date

from yf_patch import yf_fast_info, yf_ticker_attr

from services import cache
from services.utils import get_fx_rate

logger = logging.getLogger(__name__)

_CACHE_TTL = 3600
# Negativ-Cache: ohne ihn lädt jeder Aufruf für einen Titel ohne Dividende die
# volle Kurshistorie erneut von Yahoo, seriell unter dem globalen yfinance-Lock.
# Fehler nur kurz, damit ein transienter Ausfall sich selbst heilt.
_EMPTY_CACHE_TTL = 6 * 3600
_ERROR_CACHE_TTL = 300


def resolve_dividend_currency(ticker: str, fallback_currency: str) -> tuple[str, float]:
    """Resolve the quote currency for dividend amounts of a ticker.

    GBp/GBX (Pence-quotierte LSE-Titel): get_fx_rate kennt "GBp" nicht und
    fiele still auf 1.0 zurück → Beträge ~100× zu hoch (Review 2026-06-10, H3).
    Auf GBP normalisieren und Beträge durch 100 teilen.

    Returns (currency, pence_divisor).
    """
    # yf_fast_info liest das Feld, solange das Ticker-Lock gehalten ist.
    div_currency = yf_fast_info(ticker, ("currency",))["currency"] or fallback_currency
    if str(div_currency).upper() in ("GBP1/100", "GBX") or div_currency == "GBp":
        return "GBP", 100.0
    return div_currency, 1.0


def _fetch_dividends_per_share(ticker: str, since_date: date, currency: str) -> list[dict]:
    """Per-share dividend rows: date, dividend_per_share, currency, fx_rate.

    Enthält bewusst KEINE stückzahlabhängigen Felder: das Resultat liegt im
    geteilten Redis (Multi-User, gleicher Ticker) — die shares des Aufrufers
    dürfen nie in den Cache (Review 2026-07-02, C1: Cross-User-Kontamination).
    """
    cache_key = f"divs_ps:{ticker}:{since_date.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        divs = yf_ticker_attr(ticker, "dividends")
        if divs is None:
            # yfinance schluckt Netzfehler beim Kursabruf und liefert dann None,
            # ohne zu werfen. Ein Titel ohne Dividende liefert eine leere Series.
            # None ist also ein gescheiterter Abruf: nur kurz cachen, sonst gilt
            # ein Yahoo-Ausfall sechs Stunden lang als «keine Dividende».
            logger.warning(f"Failed to fetch dividends for {ticker}: yfinance returned no data")
            cache.set(cache_key, [], ttl=_ERROR_CACHE_TTL)
            return []
        if divs.empty:
            cache.set(cache_key, [], ttl=_EMPTY_CACHE_TTL)
            return []

        # Filter to since_date
        divs = divs[divs.index >= str(since_date)]
        if divs.empty:
            cache.set(cache_key, [], ttl=_EMPTY_CACHE_TTL)
            return []

        div_currency, pence_divisor = resolve_dividend_currency(ticker, currency)
        fx = get_fx_rate(div_currency, "CHF")

        result = []
        for dt, amount in divs.items():
            result.append({
                "date": dt.date().isoformat(),
                "dividend_per_share": float(amount) / pence_divisor,
                "currency": div_currency,
                "fx_rate": fx,
            })

        cache.set(cache_key, result, ttl=_CACHE_TTL)
        return result
    except Exception as e:
        logger.warning(f"Failed to fetch dividends for {ticker}: {e}")
        cache.set(cache_key, [], ttl=_ERROR_CACHE_TTL)
        return []


def fetch_dividends(ticker: str, since_date: date, shares: float, currency: str = "USD") -> list[dict]:
    """Fetch dividend history for a ticker and compute expected payouts.

    Returns list of dicts with: date, dividend_per_share, currency, shares_held, total_chf
    """
    return [
        {
            "date": row["date"],
            "dividend_per_share": round(row["dividend_per_share"], 4),
            "currency": row["currency"],
            "shares_held": shares,
            "total_chf": round(shares * row["dividend_per_share"] * row["fx_rate"], 2),
            "fx_rate": row["fx_rate"],
        }
        for row in _fetch_dividends_per_share(ticker, since_date, currency)
    ]
