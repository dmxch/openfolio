"""Test für die Ticker-Normalisierung des CapitolTrades-Scrapers (Fix BRK.B→BRK-B)."""
from services.screening.capitoltrades_scraper import _clean_ticker


def test_class_share_uses_hyphen_not_dot():
    # System-Konvention = Bindestrich (yfinance/analysis_config), nicht Punkt.
    assert _clean_ticker("BRK/B:US") == "BRK-B"
    assert _clean_ticker("BF/B:US") == "BF-B"


def test_plain_ticker_unchanged():
    assert _clean_ticker("AAPL:US") == "AAPL"


def test_strips_suffix_and_uppercases():
    assert _clean_ticker("msft:us") == "MSFT"
