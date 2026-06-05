"""Test für die Ticker-Normalisierung des Dataroma-Grand-Portfolio-Scrapers.

Fix: Dataroma zeigt Klassen-Aktien als 'BRK.B', das System-Konvention ist aber
'BRK-B' (gleich wie sec_13f_service + capitoltrades). Ohne Normalisierung splittet
derselbe Titel in zwei Consensus-Eintraege und der Smart-Money-Score zerfaellt.
"""
import pytest

import services.screening.dataroma_scraper as ds


_GRAND_HTML = """
<table>
<tr><td>Symbol</td><td>Stock</td><td>%</td><td>Owners</td></tr>
<tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>5.2</td><td>12</td></tr>
<tr><td>BF.B</td><td>Brown-Forman</td><td>1.1</td><td>4</td></tr>
<tr><td>AAPL</td><td>Apple Inc</td><td>8.0</td><td>20</td></tr>
</table>
"""


@pytest.mark.asyncio
async def test_grand_portfolio_normalizes_class_ticker(monkeypatch):
    async def fake_fetch_text(*args, **kwargs):
        return _GRAND_HTML

    monkeypatch.setattr(ds, "fetch_text", fake_fetch_text)
    ds._homepage_warmed = True  # Warmup ueberspringen

    holdings = await ds.fetch_grand_portfolio()
    tickers = {h["ticker"] for h in holdings}

    assert "BRK-B" in tickers
    assert "BF-B" in tickers
    assert "AAPL" in tickers
    # Punkt-Form darf nicht durchrutschen
    assert "BRK.B" not in tickers
    assert "BF.B" not in tickers


@pytest.mark.asyncio
async def test_grand_portfolio_skips_header(monkeypatch):
    async def fake_fetch_text(*args, **kwargs):
        return _GRAND_HTML

    monkeypatch.setattr(ds, "fetch_text", fake_fetch_text)
    ds._homepage_warmed = True

    holdings = await ds.fetch_grand_portfolio()
    tickers = {h["ticker"] for h in holdings}
    assert "SYMBOL" not in tickers
    assert len(holdings) == 3
