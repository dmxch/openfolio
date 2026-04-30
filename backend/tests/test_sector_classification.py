"""Tests für sector_classification_service: 3-stufige Cascade + Bulk-Performance.

Pure-function Tests gegen DB-Mocks. Service-Integration mit echter DB läuft
in der E2E-Verification.
"""
from unittest.mock import MagicMock

from services.sector_classification_service import (
    classify_ticker_sector,
    classify_tickers_bulk,
)


def _mock_db_conn(rows: list[tuple[str, str | None]]) -> MagicMock:
    """Mock einer DB-Connection die genau die übergebenen rows zurückgibt."""
    conn = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    conn.execute.return_value = result
    return conn


class TestClassifyTickersBulk:
    def test_override_takes_priority(self, monkeypatch):
        """SECTOR_OVERRIDES gewinnt vor Auto-Klassifikation."""
        # Mock both override-table AND DB-result. Override should win.
        from services import sector_classification_service as svc
        monkeypatch.setattr(svc, "SECTOR_OVERRIDES", {"AAPL": "Healthcare"})  # absurder Override
        conn = _mock_db_conn([("AAPL", "Telecommunications Equipment")])
        result = classify_tickers_bulk(["AAPL"], db_conn=conn)
        assert result["AAPL"] == "Healthcare"
        # DB darf nicht aufgerufen werden für AAPL (Override), aber kann für andere
        # Hier wurde sie aufgerufen aber das Ergebnis wird ignoriert.

    def test_tradingview_industry_mapping(self):
        """TradingView-Industry → GICS-Sektor via TRADINGVIEW_INDUSTRY_TO_SECTOR."""
        conn = _mock_db_conn([
            ("NVDA", "Semiconductors"),
            ("MSFT", "Packaged Software"),
            ("JPM", "Major Banks"),
        ])
        result = classify_tickers_bulk(["NVDA", "MSFT", "JPM"], db_conn=conn)
        assert result["NVDA"] == "Technology"
        assert result["MSFT"] == "Technology"
        assert result["JPM"] == "Financials"

    def test_unclassified_returns_none(self):
        """Industry die in keinem Mapping ist → None."""
        conn = _mock_db_conn([("XYZ", "Some Unknown Industry XYZ")])
        result = classify_tickers_bulk(["XYZ"], db_conn=conn)
        assert result["XYZ"] is None

    def test_ticker_not_in_db_returns_none(self):
        """Ticker ohne ticker_industries-Row → None."""
        conn = _mock_db_conn([])  # leeres DB-Result
        result = classify_tickers_bulk(["UNKNOWN"], db_conn=conn)
        assert result["UNKNOWN"] is None

    def test_bulk_one_query_for_n_tickers(self):
        """N+1-Schutz: 100 Tickers → 1 SQL-Statement."""
        conn = _mock_db_conn([(f"T{i:03d}", "Semiconductors") for i in range(100)])
        tickers = [f"T{i:03d}" for i in range(100)]
        classify_tickers_bulk(tickers, db_conn=conn)
        # Genau 1 SQL-Roundtrip:
        assert conn.execute.call_count == 1

    def test_empty_list_returns_empty_dict(self):
        """Leere Input-Liste → leeres Dict, kein DB-Hit."""
        conn = _mock_db_conn([])
        result = classify_tickers_bulk([], db_conn=conn)
        assert result == {}
        assert conn.execute.call_count == 0


class TestClassifyTickerSector:
    def test_single_wrapper_consistent_with_bulk(self):
        """Single-Ticker-Wrapper liefert dasselbe wie Bulk mit 1-Element-Liste."""
        conn = _mock_db_conn([("NVDA", "Semiconductors")])
        single = classify_ticker_sector("NVDA", db_conn=conn)
        # Reset mock
        conn2 = _mock_db_conn([("NVDA", "Semiconductors")])
        bulk = classify_tickers_bulk(["NVDA"], db_conn=conn2)["NVDA"]
        assert single == bulk

    def test_single_uppercases_input(self):
        """Single-Wrapper normalisiert Case."""
        conn = _mock_db_conn([("NVDA", "Semiconductors")])
        result = classify_ticker_sector("nvda", db_conn=conn)
        assert result == "Technology"
