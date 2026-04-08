"""Scoring service: combines setup score + ETF 200-DMA logic into a unified ticker assessment.

Wraps stock_scorer.score_stock() to produce a single TickerAssessment that can be used
by watchlist, stock detail, and sector drill-down consistently.

Signal-Logik (vereinfacht — ohne Makro-Gate):
- Setup STARK (≥70%) + Breakout → KAUFSIGNAL
- Setup STARK + kein Breakout → WATCHLIST
- Setup MODERAT (45-69%) → BEOBACHTEN
- Setup SCHWACH (<45%) → KEIN SETUP
- ETF unter 200-DMA (Whitelist) → ETF_KAUFSIGNAL (überstimmt alles)
"""

import logging

from services import cache
from services.stock_scorer import score_stock
from services.sector_mapping import is_broad_etf

logger = logging.getLogger(__name__)

# Signal labels mapping
SIGNAL_LABELS = {
    "KAUFSIGNAL": "Kaufkriterien erfüllt (Breakout bestätigt)",
    "WATCHLIST": "Warten auf Breakout",
    "BEOBACHTEN": "Setup nicht stark genug",
    "KEIN SETUP": "Kriterien nicht erfüllt",
    "ETF_KAUFSIGNAL": "ETF unter 200-DMA — Kaufkriterien erfüllt",
}


def assess_ticker(ticker: str, sector: str | None = None, manual_resistance: float | None = None) -> dict:
    """Full assessment: setup score + final signal.

    The macro gate is no longer used for individual stock signals.
    Signal logic is based purely on setup quality + breakout.
    ETF 200-DMA buy signal still overrides normal logic.
    """
    cache_key = f"assessment:{ticker}:{sector or 'none'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    setup = score_stock(ticker, manual_resistance)

    # Check for broad market ETF 200-DMA buy signal (inverted Schwur 1)
    is_whitelist_etf = is_broad_etf(ticker)
    etf_buy_signal = False
    if is_whitelist_etf:
        current = setup.get("price")
        ma200_criterion = next((c for c in setup.get("criteria", []) if c.get("id") == 1), None)
        if ma200_criterion and current and ma200_criterion.get("passed") is False:
            etf_buy_signal = True

    # Determine final signal
    if etf_buy_signal:
        signal = "ETF_KAUFSIGNAL"
        signal_label = SIGNAL_LABELS["ETF_KAUFSIGNAL"]
    else:
        # Use setup score signal directly
        signal = setup.get("signal", "KEIN SETUP")
        signal_label = setup.get("signal_label", SIGNAL_LABELS.get(signal, ""))

    result = {
        # Full setup data (backward compatible with score_stock response)
        **setup,
        # Signal
        "signal": signal,
        "signal_label": signal_label,
        # Flags for easy frontend checks
        "etf_buy_signal": etf_buy_signal,
        "is_whitelist_etf": is_whitelist_etf,
    }

    # Defensive caching: wenn der Underlying-Downloader keine brauchbaren
    # Preisdaten lieferte (transienter yfinance-Fehler, 429, Netzwerk-Timeout),
    # ist das Setup komplett mit N/A-MA-Kriterien gefuellt und der Score
    # irrefuehrend niedrig (z.B. 2/18 statt realistischer 8-10/18). In dem Fall
    # das broken Ergebnis NUR kurz cachen (60s), damit der naechste Request
    # die Chance auf frische Daten hat statt 15 Minuten stale zu bleiben.
    if setup.get("price") is None:
        logger.warning(
            f"assess_ticker({ticker}): setup has no price (downloader failure). "
            f"Caching with short TTL (60s) to allow quick retry."
        )
        cache.set(cache_key, result, ttl=60)
    else:
        cache.set(cache_key, result, ttl=900)  # 15 min
    return result
