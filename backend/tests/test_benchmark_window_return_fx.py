"""Tests fuer die CHF-Umrechnung der Benchmark-Fensterrendite.

Regression (Prod, 1.8.2026): ``get_benchmark_window_return`` lieferte die
Rendite in Notierungswaehrung, ``compare_to_benchmark`` subtrahierte sie aber
von einem CHF-Bucket-Return. ``delta_pct`` mischte damit zwei Waehrungen. Im
Fenster 16.05.-30.06.2026 (USD/CHF +2.99 %) kippte das Satellite-Delta von real
-1.38 pp auf gemeldete +2.06 pp — das Vorzeichen der Aussage.

Die Tests mocken die Kursreihen, damit kein yfinance-Call rausgeht (die Reihen
kommen im Produktivcode ueber ``_get_benchmark_closes``, die Waehrung ueber
``benchmark_quote_currency``).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from services import benchmark_service


def _series(pairs: list[tuple[str, float]]):
    return [(date.fromisoformat(d), v) for d, v in pairs]


BENCH = _series([("2026-05-15", 100.0), ("2026-06-30", 115.07)])
FX_USD = _series([("2026-05-15", 0.7842), ("2026-06-30", 0.8076)])


def _fake_closes(ticker: str):
    return FX_USD if ticker == "USDCHF=X" else BENCH


def test_window_return_includes_fx_effect():
    """+15.07 % in USD bei USD/CHF +2.99 % ergibt +18.51 % in CHF."""
    with patch.object(benchmark_service, "_get_benchmark_closes", side_effect=_fake_closes), \
         patch.object(benchmark_service, "benchmark_quote_currency", return_value="USD"):
        r = benchmark_service.get_benchmark_window_return(
            "MTUM", date(2026, 5, 16), date(2026, 6, 30)
        )
    assert r == pytest.approx(18.51, abs=0.02)


def test_chf_benchmark_is_not_converted():
    """Ein CHF-notierter Benchmark (^SSMI) bleibt unveraendert — kein FX-Call."""
    def _closes(ticker: str):
        assert ticker != "CHFCHF=X", "CHF darf keinen FX-Lookup ausloesen"
        return BENCH

    with patch.object(benchmark_service, "_get_benchmark_closes", side_effect=_closes), \
         patch.object(benchmark_service, "benchmark_quote_currency", return_value="CHF"):
        r = benchmark_service.get_benchmark_window_return(
            "^SSMI", date(2026, 5, 16), date(2026, 6, 30)
        )
    assert r == pytest.approx(15.07, abs=0.02)


def test_unknown_currency_returns_none_not_mixed_number():
    """Unbekannte Notierungswaehrung → None. Eine fehlende Zahl ist sichtbar,
    eine waehrungsgemischte nicht."""
    with patch.object(benchmark_service, "_get_benchmark_closes", side_effect=_fake_closes), \
         patch.object(benchmark_service, "benchmark_quote_currency", return_value=None):
        r = benchmark_service.get_benchmark_window_return(
            "MTUM", date(2026, 5, 16), date(2026, 6, 30)
        )
    assert r is None


def test_missing_fx_series_returns_none():
    """Kein FX-Kurs beschaffbar → None statt Rendite in Fremdwaehrung."""
    def _closes(ticker: str):
        return None if ticker == "USDCHF=X" else BENCH

    with patch.object(benchmark_service, "_get_benchmark_closes", side_effect=_closes), \
         patch.object(benchmark_service, "benchmark_quote_currency", return_value="USD"):
        r = benchmark_service.get_benchmark_window_return(
            "MTUM", date(2026, 5, 16), date(2026, 6, 30)
        )
    assert r is None


def test_monthly_returns_are_chf_too():
    """Die Monatsreihe (/benchmark-returns, Portfolio-Chart) laeuft ueber
    denselben CHF-Pfad — sie stand in der UI neben CHF-Portfolio-Monatsrenditen.

    Reihe: 100 (Mai) → 115.07 (Juni) bei USD/CHF 0.7842 → 0.8076.
    In CHF: 78.42 → 92.93, also +18.51 % statt +15.07 %.
    """
    with patch.object(benchmark_service.cache, "get", return_value=None), \
         patch.object(benchmark_service.cache, "set"), \
         patch.object(benchmark_service, "_get_benchmark_closes", side_effect=_fake_closes), \
         patch.object(benchmark_service, "benchmark_quote_currency", return_value="USD"):
        r = benchmark_service.get_benchmark_monthly_returns("MTUM")
    assert r["currency"] == "CHF"
    juni = [m for m in r["months"] if (m["year"], m["month"]) == (2026, 6)]
    assert juni and juni[0]["return_pct"] == pytest.approx(18.51, abs=0.02)


def test_monthly_returns_empty_when_currency_unknown():
    """Unbekannte Waehrung → leere Reihe statt gemischter Zahlen."""
    with patch.object(benchmark_service.cache, "get", return_value=None), \
         patch.object(benchmark_service.cache, "set"), \
         patch.object(benchmark_service, "_get_benchmark_closes", side_effect=_fake_closes), \
         patch.object(benchmark_service, "benchmark_quote_currency", return_value=None):
        r = benchmark_service.get_benchmark_monthly_returns("MTUM")
    assert r["months"] == [] and r["annual_totals"] == {}
    assert r["currency"] == "CHF"


def test_unknown_currency_is_negative_cached():
    """Fehlschlag wird gecacht: der info/quote-Endpunkt haelt den globalen
    Ticker-Lock, ein 429-Bann darf nicht jeden Request in denselben Timeout
    schicken."""
    store: dict = {}
    with patch.object(benchmark_service.cache, "get", side_effect=store.get), \
         patch.object(benchmark_service.cache, "set",
                      side_effect=lambda k, v, ttl=None: store.__setitem__(k, v)), \
         patch("yf_patch.yf_quote_currency", return_value=None) as mock_cur:
        assert benchmark_service.benchmark_quote_currency("MTUM") is None
        assert benchmark_service.benchmark_quote_currency("MTUM") is None
    assert mock_cur.call_count == 1, "zweiter Aufruf haette aus dem Cache kommen muessen"


def test_gbx_alias_normalised_to_gbp():
    """yfinance liefert Pence mal als GBX, mal als GBp — beide muessen auf die
    GBP-FX-Reihe fuehren, sonst laeuft der Lookup auf GBXCHF=X ins Leere."""
    with patch.object(benchmark_service.cache, "get", return_value=None), \
         patch.object(benchmark_service.cache, "set"), \
         patch("yf_patch.yf_quote_currency", return_value="GBX"):
        assert benchmark_service.benchmark_quote_currency("TESTL") == "GBp"


def test_gbx_pence_normalised_before_fx():
    """GBp wird auf GBP normalisiert (Faktor 100), nicht aus dem Suffix geraten.

    Der Faktor kuerzt sich im Return heraus — geprueft wird, dass die
    GBP-FX-Reihe gezogen wird und keine GBpCHF=X-Anfrage entsteht.
    """
    seen: list[str] = []

    def _closes(ticker: str):
        seen.append(ticker)
        return FX_USD if ticker.endswith("CHF=X") else BENCH

    with patch.object(benchmark_service, "_get_benchmark_closes", side_effect=_closes), \
         patch.object(benchmark_service, "benchmark_quote_currency", return_value="GBp"):
        r = benchmark_service.get_benchmark_window_return(
            "TESTL", date(2026, 5, 16), date(2026, 6, 30)
        )
    assert "GBPCHF=X" in seen
    assert "GBpCHF=X" not in seen
    assert r == pytest.approx(18.51, abs=0.02)
