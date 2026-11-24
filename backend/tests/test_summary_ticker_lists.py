"""Die Portfolio-Summary fragt Yahoo nicht nach Cash- und Vorsorge-Positionen.

Ein Vorsorge-Konto trägt ein Konto-Label als Ticker (``PENSION_3A``). Die Summary
lud dafür die Kursreihe vor und rechnete MA und MRS; Yahoo antwortete mit 404 und
das Log füllte sich mit Fehlerzeilen.
"""
from types import SimpleNamespace

from models.position import AssetType
from services.portfolio_service import _summary_ticker_lists


def _pos(ticker, type_, shares=1, yfinance_ticker=None):
    return SimpleNamespace(ticker=ticker, type=type_, shares=shares, yfinance_ticker=yfinance_ticker)


def test_pension_and_cash_are_in_no_ticker_list():
    positions = [
        _pos("PENSION_3A", AssetType.pension),
        _pos("VORSORGE", AssetType.pension),
        _pos("CASH_ZKB", AssetType.cash),
        _pos("USD", AssetType.cash),
        _pos("AAPL", AssetType.stock, shares=5),
    ]

    tradable, signal, price = _summary_ticker_lists(positions)

    assert tradable == ["AAPL"]
    assert signal == ["AAPL"]
    assert price == ["AAPL"]


def test_other_types_keep_their_lists():
    positions = [
        _pos("NESN", AssetType.stock, yfinance_ticker="NESN.SW"),
        _pos("IB01.L", AssetType.bond),
        _pos("GOLD", AssetType.commodity, yfinance_ticker="GC=F"),
        _pos("SOLD", AssetType.stock, shares=0),
        _pos("HAUS", AssetType.real_estate),
        _pos("PE1", AssetType.private_equity),
    ]

    tradable, signal, price = _summary_ticker_lists(positions)

    assert tradable == ["NESN.SW", "IB01.L"]  # Anleihe: Kurs ja
    assert signal == ["NESN.SW"]  # Anleihe: keine Aktien-Signale
    assert price == ["NESN.SW", "IB01.L", "GC=F"]  # SKIP_TICKERS: Kurs, kein MA/MRS
