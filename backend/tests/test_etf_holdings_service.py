"""Tests für etf_holdings_service Pure-Functions (is_us_etf, _parse_fmp_holding).

Service-Integration (refresh_etf_holdings, refresh_all_user_etfs) wird in
E2E-Verification gegen Live-DB getestet — Mock-Aufwand für AsyncSession +
httpx-Mock ist hier nicht angemessen, weil die Pure-Function-Tests die
kritische Logik bereits abdecken.
"""
from datetime import date

from services.etf_holdings_service import _parse_fmp_holding, is_us_etf


class TestIsUsEtf:
    def test_us_etf_no_dot(self):
        assert is_us_etf("OEF") is True
        assert is_us_etf("SPY") is True
        assert is_us_etf("VOO") is True

    def test_non_us_with_dot(self):
        assert is_us_etf("CHSPI.SW") is False
        assert is_us_etf("SWDA.L") is False
        assert is_us_etf("JPNA.L") is False
        assert is_us_etf("SSV.TO") is False

    def test_edge_lowercase(self):
        # Heuristik unabhängig von Case (nur Punkt zählt)
        assert is_us_etf("oef") is True
        assert is_us_etf("chspi.sw") is False


class TestParseFmpHolding:
    def test_full_row_with_updated(self):
        row = {
            "asset": "NVDA",
            "name": "NVIDIA Corporation",
            "weightPercentage": 7.5,
            "sharesNumber": 12345678,
            "marketValue": 1234567890,
            "updated": "2026-02-28",
        }
        parsed = _parse_fmp_holding(row)
        assert parsed is not None
        assert parsed["asset"] == "NVDA"
        assert parsed["name"] == "NVIDIA Corporation"
        assert parsed["weight_pct"] == 7.5
        assert parsed["as_of"] == date(2026, 2, 28)

    def test_row_without_updated_uses_date(self):
        row = {
            "asset": "AAPL",
            "weightPercentage": 6.0,
            "date": "2026-01-15T00:00:00",
        }
        parsed = _parse_fmp_holding(row)
        assert parsed is not None
        assert parsed["asset"] == "AAPL"
        assert parsed["as_of"] == date(2026, 1, 15)

    def test_row_no_stichtag(self):
        """FMP liefert nicht garantiert ein as_of — None ist OK."""
        row = {
            "asset": "MSFT",
            "weightPercentage": 5.5,
        }
        parsed = _parse_fmp_holding(row)
        assert parsed is not None
        assert parsed["as_of"] is None

    def test_row_missing_asset_returns_none(self):
        row = {"weightPercentage": 5.0}
        assert _parse_fmp_holding(row) is None

    def test_row_zero_weight_returns_none(self):
        """Zero-Weight-Holdings werden geskipped (FMP liefert manchmal 0%-Cash-Buckets)."""
        row = {"asset": "CASH", "weightPercentage": 0}
        assert _parse_fmp_holding(row) is None

    def test_row_invalid_date_falls_back_to_none(self):
        row = {
            "asset": "GOOGL",
            "weightPercentage": 4.0,
            "updated": "not-a-date",
        }
        parsed = _parse_fmp_holding(row)
        assert parsed is not None
        assert parsed["as_of"] is None  # graceful fallback

    def test_asset_uppercased_and_stripped(self):
        row = {"asset": " nvda ", "weightPercentage": 7.0}
        parsed = _parse_fmp_holding(row)
        assert parsed["asset"] == "NVDA"

    def test_symbol_field_as_alternative_to_asset(self):
        """FMP gibt manchmal 'symbol' statt 'asset' zurück."""
        row = {"symbol": "META", "weightPercentage": 4.5}
        parsed = _parse_fmp_holding(row)
        assert parsed is not None
        assert parsed["asset"] == "META"
