"""Tests fuer den Edelmetall-Preispfad (get_metal_futures / get_metal_price_chf)."""
from unittest.mock import patch

import pytest

from services.precious_metals_service import METAL_FUTURES, get_metal_futures
from services.price_service import get_metal_price_chf


class TestGetMetalFutures:
    def test_gold(self):
        assert get_metal_futures("XAUCHF=X") == ("GC=F", "USD")

    def test_silver(self):
        assert get_metal_futures("XAGCHF=X") == ("SI=F", "USD")

    def test_platinum(self):
        assert get_metal_futures("XPTCHF=X") == ("PL=F", "USD")

    def test_palladium(self):
        assert get_metal_futures("XPDCHF=X") == ("PA=F", "USD")

    def test_unknown_ticker(self):
        assert get_metal_futures("UNKNOWN") is None

    def test_all_entries_consistent_shape(self):
        assert set(METAL_FUTURES.keys()) == {
            "XAUCHF=X", "XAGCHF=X", "XPTCHF=X", "XPDCHF=X",
        }
        for v in METAL_FUTURES.values():
            assert isinstance(v, tuple) and len(v) == 2
            assert v[1] == "USD"


class TestGetMetalPriceChf:
    @patch("services.price_service.get_gold_price_chf")
    def test_gold_delegates_to_goldorg(self, mock_gold):
        mock_gold.return_value = {"price": 3716.73, "currency": "CHF", "change_pct": 0.1}
        result = get_metal_price_chf("XAUCHF=X")
        assert result == {"price": 3716.73, "currency": "CHF", "change_pct": 0.1}
        mock_gold.assert_called_once()

    @patch("services.price_service.get_stock_price")
    def test_silver_converts_usd_via_fx(self, mock_stock):
        mock_stock.return_value = {"price": 35.0, "currency": "USD", "change_pct": 0.5}
        result = get_metal_price_chf("XAGCHF=X", fx_rates={"USD": 0.9})
        assert result is not None
        assert result["currency"] == "CHF"
        assert result["price"] == pytest.approx(35.0 * 0.9, abs=0.01)
        assert result["change_pct"] == 0.5
        mock_stock.assert_called_once_with("SI=F")

    @patch("services.price_service.get_stock_price")
    def test_platinum_uses_pl_futures(self, mock_stock):
        mock_stock.return_value = {"price": 1000.0, "currency": "USD"}
        result = get_metal_price_chf("XPTCHF=X", fx_rates={"USD": 0.9})
        assert result["price"] == pytest.approx(900.0, abs=0.01)
        mock_stock.assert_called_once_with("PL=F")

    @patch("services.price_service.get_stock_price")
    def test_returns_none_on_missing_fx(self, mock_stock):
        mock_stock.return_value = {"price": 35.0, "currency": "USD"}
        # kein fx_rates, und auch kein DB-Fallback fuer USDCHF=X:
        with patch("services.cache_service.get_cached_price_sync", return_value=None):
            result = get_metal_price_chf("XAGCHF=X")
        assert result is None

    @patch("services.price_service.get_stock_price")
    def test_fx_fallback_to_db_cache(self, mock_stock):
        mock_stock.return_value = {"price": 35.0, "currency": "USD", "change_pct": 0.5}
        with patch(
            "services.cache_service.get_cached_price_sync",
            return_value={"price": 0.88, "currency": "CHF"},
        ):
            result = get_metal_price_chf("XAGCHF=X")
        assert result is not None
        assert result["price"] == pytest.approx(35.0 * 0.88, abs=0.01)

    @patch("services.price_service.get_stock_price")
    def test_returns_none_on_missing_futures(self, mock_stock):
        mock_stock.return_value = None
        result = get_metal_price_chf("XAGCHF=X", fx_rates={"USD": 0.9})
        assert result is None

    def test_unknown_ticker_returns_none(self):
        assert get_metal_price_chf("UNKNOWN") is None
