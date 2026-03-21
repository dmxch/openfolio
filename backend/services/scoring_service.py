"""Scoring service: combines macro gate + setup score into a unified ticker assessment.

Wraps stock_scorer.score_stock() and macro_gate_service.calculate_macro_gate()
to produce a single TickerAssessment that can be used by watchlist, stock detail,
and sector drill-down consistently.

Macro-Gate Ampel-System:
- 6-9/9 (Bestanden): Alle Signale aktiv (Core + Satellite)
- 3-5/9 (Schwach):   Core mit strengeren Kriterien, Satellite blockiert
- 0-2/9 (Kritisch):  Core nur mit Bestätigung, Satellite blockiert
"""

import logging

from services import cache
from services.stock_scorer import score_stock
from services.macro_gate_service import calculate_macro_gate

logger = logging.getLogger(__name__)

# Signal labels mapping
SIGNAL_LABELS = {
    "KAUFSIGNAL": "Kaufkriterien erfüllt (Breakout bestätigt)",
    "KAUFSIGNAL_WARNUNG": "Kaufkriterien erfüllt (schwaches Makro)",
    "KAUFSIGNAL_BESTÄTIGUNG": "Kaufkriterien erfüllt (kritisches Makro — Bestätigung nötig)",
    "WATCHLIST": "Warten auf Breakout",
    "BEOBACHTEN": "Setup nicht stark genug",
    "KEIN SETUP": "Kriterien nicht erfüllt",
    "MAKRO_BLOCKIERT": "Makro-Gate nicht bestanden",
    "ETF_KAUFSIGNAL": "ETF unter 200-DMA — Kaufkriterien erfüllt",
}

# Broad market ETFs where below-200-DMA = BUY signal (inverted Schwur 1)
# Base tickers only — matching strips exchange suffix (VWRL.SW → VWRL)
ETF_200DMA_WHITELIST = {
    # US Broad Market
    "VOO", "VTI", "SPY", "QQQ", "OEF", "IVV", "VT", "DIA",
    # International / World (US-listed)
    "ACWI", "URTH", "VEA", "VWO", "EEM", "IEMG",
    # European / London-listed
    "VWRL", "VWRD", "SWDA", "IWDA", "CSPX", "VUSA", "WOSC", "EIMI",
    # CHF-hedged / Switzerland
    "SP5HCH", "WRDHDCH", "SPMCHA", "CHSPI", "CSSMI",
}


def _is_broad_etf(ticker: str) -> bool:
    """Check if ticker is on the broad ETF whitelist (matches base ticker)."""
    base = ticker.split(".")[0].upper()
    return base in ETF_200DMA_WHITELIST


def _get_macro_status(score: int) -> str:
    """Classify macro gate score into traffic light status."""
    if score >= 6:
        return "bestanden"
    elif score >= 3:
        return "schwach"
    return "kritisch"


def _count_fundamental_criteria(setup: dict) -> tuple[int, int]:
    """Count passed fundamental criteria from setup score."""
    criteria = setup.get("criteria", [])
    fund_criteria = [c for c in criteria if c.get("group") == "Fundamentals"]
    passed = sum(1 for c in fund_criteria if c.get("passed") is True)
    total = len(fund_criteria)
    return passed, total


def assess_ticker(ticker: str, sector: str | None = None, manual_resistance: float | None = None) -> dict:
    """Full assessment: macro gate + setup score + final signal.

    The setup score is ALWAYS computed, even when the gate is blocked,
    so users can see which stocks are ready when the gate opens.

    Macro-Gate Ampel:
    - Bestanden (6-9): Normal signals for both Core and Satellite
    - Schwach (3-5): Core allowed with stricter criteria, Satellite blocked
    - Kritisch (0-2): Core only with confirmation, Satellite blocked
    """
    cache_key = f"assessment:{ticker}:{sector or 'none'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Always compute both
    macro_gate = calculate_macro_gate(sector)
    setup = score_stock(ticker, manual_resistance)

    macro_score = macro_gate.get("score", 0)
    macro_status = _get_macro_status(macro_score)
    setup_quality = setup.get("setup_quality", "SCHWACH")
    fund_passed, fund_total = _count_fundamental_criteria(setup)

    # Check for broad market ETF 200-DMA buy signal (inverted Schwur 1)
    is_whitelist_etf = _is_broad_etf(ticker)
    etf_buy_signal = False
    if is_whitelist_etf:
        # Extract MA200 from criteria (id=1: "Preis > MA200")
        current = setup.get("price")
        ma200_criterion = next((c for c in setup.get("criteria", []) if c.get("id") == 1), None)
        # MA200 criterion passed=False means price < MA200
        if ma200_criterion and current and ma200_criterion.get("passed") is False:
            etf_buy_signal = True

    # Determine final signal
    requires_confirmation = False
    warning_message = None

    if etf_buy_signal:
        signal = "ETF_KAUFSIGNAL"
        signal_label = SIGNAL_LABELS["ETF_KAUFSIGNAL"]
        macro_status = "überstimmt"
        warning_message = f"{ticker} handelt unter der 200-DMA — Kaufsignal für breite Index-ETFs (Erweiterter Schwur 1)."

    elif macro_status == "bestanden":
        # Green: normal signal logic for both Core and Satellite
        signal = setup.get("signal", "KEIN SETUP")
        signal_label = setup.get("signal_label", SIGNAL_LABELS.get(signal, ""))

    elif macro_status == "schwach":
        # Yellow: Core with stricter criteria, Satellite blocked
        if setup_quality == "STARK" and fund_passed >= 3:
            signal = "KAUFSIGNAL_WARNUNG"
            signal_label = SIGNAL_LABELS["KAUFSIGNAL_WARNUNG"]
            warning_message = f"Makro-Gate schwach ({macro_score}/9). Nur für Core-Positionen — engeren Stop-Loss setzen."
        elif setup_quality == "STARK":
            signal = "WATCHLIST"
            signal_label = f"Setup stark, aber Fundamentals unzureichend ({fund_passed}/{fund_total})"
            warning_message = f"Makro-Gate schwach ({macro_score}/9). Fundamentals verbessern für Kaufsignal."
        else:
            signal = "BEOBACHTEN"
            signal_label = SIGNAL_LABELS["BEOBACHTEN"]

    else:
        # Red: Core only with confirmation, Satellite blocked
        if setup_quality == "STARK" and fund_passed >= 3:
            signal = "KAUFSIGNAL_BESTÄTIGUNG"
            signal_label = SIGNAL_LABELS["KAUFSIGNAL_BESTÄTIGUNG"]
            requires_confirmation = True
            warning_message = f"Makro-Gate kritisch ({macro_score}/9)! Kauf nur als Core-Position mit Überzeugung."
        else:
            signal = "MAKRO_BLOCKIERT"
            signal_label = SIGNAL_LABELS["MAKRO_BLOCKIERT"]

    gate_blocked = signal == "MAKRO_BLOCKIERT"

    result = {
        # Full setup data (backward compatible with score_stock response)
        **setup,
        # Override signal with gate-aware signal
        "signal": signal,
        "signal_label": signal_label,
        # Add macro gate data
        "macro_gate": macro_gate,
        "macro_status": macro_status,
        # Confirmation and warning
        "requires_confirmation": requires_confirmation,
        "warning_message": warning_message,
        # Flags for easy frontend checks
        "gate_blocked": gate_blocked,
        "etf_buy_signal": etf_buy_signal,
        "is_whitelist_etf": is_whitelist_etf,
        # Original signal (without gate) for display when blocked
        "setup_signal": setup.get("signal", "KEIN SETUP"),
        "setup_signal_label": setup.get("signal_label", ""),
    }

    cache.set(cache_key, result, ttl=900)  # 15 min
    return result
