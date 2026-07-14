"""Scoring service: combines setup score + ETF 200-DMA logic into a unified ticker assessment.

Wraps stock_scorer.score_stock() to produce a single TickerAssessment that can be used
by watchlist, stock detail, and sector drill-down consistently.

Signal-Logik (vereinfacht — ohne Makro-Gate):
- Setup STARK (≥70%) + Breakout → KAUFSIGNAL
- Setup STARK + kein Breakout → WATCHLIST
- Setup MODERAT (45-69%) → BEOBACHTEN
- Setup SCHWACH (<45%) → KEIN SETUP
- ETF unter 200-DMA (Whitelist) → ETF_KAUFSIGNAL (überstimmt alles)
- Anleihen (asset_type='bond') → NICHT_ANWENDBAR (kein Aktien-Setup, siehe assess_ticker)
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
    "NICHT_ANWENDBAR": "Aktien-Setup für Anleihen nicht anwendbar",
}

# Asset-Typen ohne Aktien-Setup. Die 19-Punkte-Checkliste misst Aktien-Trend und
# relative Stärke gegen ^GSPC — auf einen Bond-ETF angewandt liefert sie keine
# schwache Bewertung, sondern eine bedeutungslose: Mansfield RS einer Anleihe
# gegen den S&P 500 beschreibt die Zinskurve, kein Setup.
_NO_STOCK_SETUP_TYPES = frozenset({"bond"})


def _not_applicable_assessment(ticker: str, asset_type: str) -> dict:
    """Neutrales Ergebnis für Assetklassen ohne Aktien-Setup.

    Bewusst score/max_score = 0 und criteria = [] statt "0 von 19 Punkten":
    ein Nullscore liesse sich als schlechtes Setup missverstehen, hier gibt es
    schlicht keines. ``not_applicable`` ist der Schalter für die Aufrufer.
    """
    return {
        "ticker": ticker,
        "type": asset_type,
        "price": None,
        "score": 0,
        "max_score": 0,
        "pct": 0,
        "rating": "",
        "criteria": [],
        "alerts": [],
        "mansfield_rs": None,
        "breakout": None,
        "signal": "NICHT_ANWENDBAR",
        "signal_label": SIGNAL_LABELS["NICHT_ANWENDBAR"],
        "etf_buy_signal": False,
        "is_whitelist_etf": False,
        "not_applicable": True,
    }


def assess_ticker(
    ticker: str,
    sector: str | None = None,
    manual_resistance: float | None = None,
    asset_type: str | None = None,
) -> dict:
    """Full assessment: setup score + final signal.

    The macro gate is no longer used for individual stock signals.
    Signal logic is based purely on setup quality + breakout.
    ETF 200-DMA buy signal still overrides normal logic.

    ``asset_type`` ist der Positions-/Watchlist-Typ des Tickers, falls bekannt.
    Anleihen werden damit vom Aktien-Scoring ausgenommen; ohne Angabe (None)
    läuft die Bewertung unverändert wie bisher.
    """
    if asset_type in _NO_STOCK_SETUP_TYPES:
        # Vor dem Cache: der Cache-Key kennt den asset_type nicht, ein hier
        # geschriebener Eintrag würde denselben Ticker für andere Aufrufer
        # verfälschen (und umgekehrt).
        return _not_applicable_assessment(ticker, asset_type)

    # manual_resistance MUSS in den Key: sie ist per-User und beeinflusst
    # Breakout-Trigger + Signal — ohne sie leakt User As Resistance-Ergebnis
    # 15 Min an alle anderen User (Review 2026-06-10, H7).
    cache_key = f"assessment:{ticker}:{sector or 'none'}:{manual_resistance if manual_resistance is not None else 'auto'}"
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
