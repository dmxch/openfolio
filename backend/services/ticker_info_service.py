"""Slim yfinance-Ticker-Info (Name/Currency) mit Redis-Cache.

Genutzt von den Positions-Neuanlage-Pfaden in ``api.transactions`` und
``api.orders`` (Audit 2026-07-02, Nit #6: gehört fachlich in services/,
nicht als Router-zu-Router-Import).
"""
import logging

from api.validation import is_iso_currency

logger = logging.getLogger(__name__)


def _pence_divisor_applies(ticker: str) -> bool:
    """True, wenn ``cache_service._pence_divisor`` Pence-Kurse dieses Tickers teilt.

    Dieselbe Bedingung wie dort (Endung ``.L``). Wer sie dort ändert, zieht sie
    hier nach; ``test_vr11_w5_yf_regressions`` hält beide Stellen zusammen.
    """
    return ticker.endswith(".L")


def _normalize_currency(raw: object, ticker: str) -> str | None:
    """Bringt die Yahoo-Währung auf den Code, den Positionen und FX-Tabelle führen.

    Pence-notierte LSE-Titel meldet Yahoo als ``GBp`` (teils ``GBX``). Die Kurse
    rechnet ``cache_service._pence_divisor`` in Pfund um, die Position führt
    deshalb ``GBP`` — mit ``GBp`` fände die Bewertung keinen FX-Kurs und zeigte
    0 CHF. Das gilt nur für Ticker, deren Kurse der Divisor teilt. Bei jedem
    anderen Ticker bleiben die Kurse in Pence: ``GBP`` ergäbe dort eine Bewertung,
    die ohne Warnung 100-fach zu hoch ist. Pence ohne Divisor gilt deshalb als
    unbekannt, ebenso alles, was kein Währungscode ist (``ZAc``, ``ILA`` …): der
    Aufrufer behält dann die Währung aus der Buchung.
    """
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    # Vor upper() prüfen: nur die Schreibweise unterscheidet Pence (GBp) von Pfund (GBP).
    if raw == "GBp" or raw.upper() == "GBX":
        return "GBP" if _pence_divisor_applies(ticker) else None
    code = raw.upper()
    return code if is_iso_currency(code) or code == "CNH" else None


async def get_ticker_info_cached(ticker: str) -> dict:
    """Slim yfinance-Info (Name/Currency) fuer Positions-Neuanlagen.

    Geht ueber den thread-safe ``yf_ticker_attr``-Wrapper (statt rohem
    ``yf.Ticker().info``) und cached das Ergebnis 24h in Redis unter
    ``ticker_info:{ticker}`` — Positions-Neuanlagen treffen yfinance damit
    nicht pro Request (Review 2026-07-02, LOW-raw-yf-info). Raises on lookup
    failure — caller handles best-effort fallback.

    ``currency`` ist normalisiert (siehe ``_normalize_currency``) oder ``None``.
    """
    from services import cache

    cache_key = f"ticker_info:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        # Auch beim Lesen: Einträge von vor der Normalisierung leben bis zu 24h.
        return {**cached, "currency": _normalize_currency(cached.get("currency"), ticker)}

    from yf_patch import yf_ticker_attr, yf_to_thread

    # Eigener Pool statt asyncio.to_thread: der Abruf wartet am Ticker-Lock und
    # soll dabei keinen Thread des Default-Executors belegen.
    info = await yf_to_thread(yf_ticker_attr, ticker, "info") or {}
    slim = {
        "shortName": info.get("shortName"),
        "longName": info.get("longName"),
        "currency": _normalize_currency(info.get("currency"), ticker),
    }
    # Leere Lookups (transienter Fehler/unbekannter Ticker) nicht 24h pinnen.
    if any(slim.values()):
        cache.set(cache_key, slim, ttl=86400)
    return slim
