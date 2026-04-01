"""Tests for price_service — cache layers, fallback logic, and VIX levels.

Tests the multi-layer price resolution (memory cache → DB cache → live fetch → fallback)
and the VIX level classification that must NEVER change without explicit maintainer approval.
"""

from unittest.mock import MagicMock, patch

import pytest

from services.price_service import get_stock_price, get_crypto_price_chf, get_gold_price_chf, get_vix

# get_cached_price_sync is lazily imported inside functions via
# `from services.cache_service import get_cached_price_sync`, so we
# must patch it at the source module.
PATCH_DB_CACHE = "services.cache_service.get_cached_price_sync"


# ---------------------------------------------------------------------------
# get_stock_price
# ---------------------------------------------------------------------------

class TestGetStockPrice:
    """Tests the 4-layer price resolution: cache → DB today → live → DB 5d fallback."""

    @patch("services.price_service.cache")
    def test_returns_cached_price(self, mock_cache):
        """Layer 1: memory/Redis cache hit returns immediately."""
        expected = {"price": 150.0, "currency": "USD", "change_pct": 1.5}
        mock_cache.get.return_value = expected

        result = get_stock_price("AAPL")
        assert result == expected
        mock_cache.get.assert_called_once_with("price:AAPL")

    @patch("services.price_service.cache")
    def test_returns_db_cache_today(self, mock_cache):
        """Layer 2: DB cache (today, not stale) → cache.set + return."""
        mock_cache.get.return_value = None

        with patch(PATCH_DB_CACHE) as mock_db:
            mock_db.return_value = {"price": 149.0, "currency": "USD", "stale": False}
            result = get_stock_price("AAPL")
            assert result is not None
            assert result["price"] == 149.0
            mock_cache.set.assert_called_once()

    @patch("services.price_service.cache")
    def test_returns_none_when_no_price(self, mock_cache):
        """No cache, no DB, no live fetch (in event loop) → None."""
        mock_cache.get.return_value = None

        with patch(PATCH_DB_CACHE, return_value=None):
            with patch("services.price_service._in_event_loop", return_value=True):
                result = get_stock_price("UNKNOWN")
                assert result is None

    @patch("services.price_service.cache")
    def test_event_loop_skips_live_fetch(self, mock_cache):
        """When in event loop, skip blocking yfinance call, try DB fallback."""
        mock_cache.get.return_value = None

        with patch(PATCH_DB_CACHE) as mock_db:
            # First call (today): None. Second call (5d fallback): has data
            mock_db.side_effect = [None, {"price": 148.0, "currency": "USD"}]
            with patch("services.price_service._in_event_loop", return_value=True):
                result = get_stock_price("AAPL")
                assert result is not None
                assert result["price"] == 148.0

    @patch("services.price_service.cache")
    def test_live_fetch_success(self, mock_cache):
        """When NOT in event loop, yfinance live fetch works."""
        mock_cache.get.return_value = None

        with patch(PATCH_DB_CACHE, return_value=None):
            with patch("services.price_service._in_event_loop", return_value=False):
                mock_ticker = MagicMock()
                mock_ticker.fast_info.last_price = 155.0
                mock_ticker.fast_info.previous_close = 150.0
                mock_ticker.fast_info.currency = "USD"
                with patch("services.price_service.yf.Ticker", return_value=mock_ticker):
                    result = get_stock_price("AAPL")
                    assert result is not None
                    assert result["price"] == 155.0
                    assert result["currency"] == "USD"
                    # change_pct = (155-150)/150*100 = 3.33
                    assert abs(result["change_pct"] - 3.33) < 0.01

    @patch("services.price_service.cache")
    def test_live_fetch_failure_falls_to_db(self, mock_cache):
        """yfinance fails → DB 5-day fallback."""
        mock_cache.get.return_value = None

        with patch(PATCH_DB_CACHE) as mock_db:
            mock_db.side_effect = [None, {"price": 145.0, "currency": "USD"}]
            with patch("services.price_service._in_event_loop", return_value=False):
                with patch("services.price_service.yf.Ticker", side_effect=Exception("yfinance down")):
                    result = get_stock_price("AAPL")
                    assert result is not None
                    assert result["price"] == 145.0

    @patch("services.price_service.cache")
    def test_allow_live_fetch_false(self, mock_cache):
        """allow_live_fetch=False skips yfinance even outside event loop."""
        mock_cache.get.return_value = None

        with patch(PATCH_DB_CACHE, return_value=None):
            with patch("services.price_service._in_event_loop", return_value=False):
                result = get_stock_price("AAPL", allow_live_fetch=False)
                assert result is None


# ---------------------------------------------------------------------------
# get_crypto_price_chf (sync version)
# ---------------------------------------------------------------------------

class TestGetCryptoPriceChf:
    @patch("services.price_service.cache")
    def test_cached_crypto(self, mock_cache):
        expected = {"price": 95000.0, "currency": "CHF", "change_pct": 2.1}
        mock_cache.get.return_value = expected
        result = get_crypto_price_chf("bitcoin")
        assert result == expected

    @patch("services.price_service.cache")
    def test_event_loop_returns_none(self, mock_cache):
        """In async context, sync crypto fetch returns None."""
        mock_cache.get.return_value = None
        with patch("services.price_service._in_event_loop", return_value=True):
            result = get_crypto_price_chf("bitcoin")
            assert result is None

    @patch("services.price_service.cache")
    def test_successful_fetch(self, mock_cache):
        mock_cache.get.return_value = None
        with patch("services.price_service._in_event_loop", return_value=False):
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "bitcoin": {"chf": 95000.0, "chf_24h_change": 2.5}
            }
            mock_resp.raise_for_status = MagicMock()
            with patch("httpx.get", return_value=mock_resp):
                result = get_crypto_price_chf("bitcoin")
                assert result["price"] == 95000.0
                assert result["currency"] == "CHF"
                assert result["change_pct"] == 2.5

    @patch("services.price_service.cache")
    def test_unknown_coin_returns_none(self, mock_cache):
        mock_cache.get.return_value = None
        with patch("services.price_service._in_event_loop", return_value=False):
            mock_resp = MagicMock()
            mock_resp.json.return_value = {}
            mock_resp.raise_for_status = MagicMock()
            with patch("httpx.get", return_value=mock_resp):
                result = get_crypto_price_chf("fake-coin")
                assert result is None


# ---------------------------------------------------------------------------
# get_gold_price_chf (sync version)
# ---------------------------------------------------------------------------

class TestGetGoldPriceChf:
    @patch("services.price_service.cache")
    def test_cached_gold(self, mock_cache):
        expected = {"price": 2400.0, "currency": "CHF", "change_pct": 0.5}
        mock_cache.get.return_value = expected
        result = get_gold_price_chf()
        assert result == expected

    @patch("services.price_service.cache")
    def test_event_loop_returns_none(self, mock_cache):
        mock_cache.get.return_value = None
        with patch("services.price_service._in_event_loop", return_value=True):
            result = get_gold_price_chf()
            assert result is None


# ---------------------------------------------------------------------------
# get_vix — level classification
# ---------------------------------------------------------------------------

class TestGetVix:
    """VIX level classification is critical for macro-gate display."""

    @patch("services.price_service.cache")
    def test_cached_vix(self, mock_cache):
        expected = {"value": 18.5, "change": -0.3, "level": "normal"}
        mock_cache.get.return_value = expected
        result = get_vix()
        assert result == expected

    @patch("services.price_service.cache")
    def test_vix_level_low(self, mock_cache):
        """VIX < 15 → low."""
        mock_cache.get.return_value = None
        with patch(PATCH_DB_CACHE) as mock_db:
            mock_db.return_value = {"price": 12.5, "stale": False}
            result = get_vix()
            assert result["level"] == "low"
            assert result["value"] == 12.5

    @patch("services.price_service.cache")
    def test_vix_level_normal(self, mock_cache):
        """15 <= VIX < 20 → normal."""
        mock_cache.get.return_value = None
        with patch(PATCH_DB_CACHE) as mock_db:
            mock_db.return_value = {"price": 17.0, "stale": False}
            result = get_vix()
            assert result["level"] == "normal"

    @patch("services.price_service.cache")
    def test_vix_level_elevated(self, mock_cache):
        """20 <= VIX < 30 → elevated."""
        mock_cache.get.return_value = None
        with patch(PATCH_DB_CACHE) as mock_db:
            mock_db.return_value = {"price": 25.0, "stale": False}
            result = get_vix()
            assert result["level"] == "elevated"

    @patch("services.price_service.cache")
    def test_vix_level_high(self, mock_cache):
        """VIX >= 30 → high."""
        mock_cache.get.return_value = None
        with patch(PATCH_DB_CACHE) as mock_db:
            mock_db.return_value = {"price": 35.0, "stale": False}
            result = get_vix()
            assert result["level"] == "high"

    @patch("services.price_service.cache")
    def test_vix_boundary_15(self, mock_cache):
        """VIX = exactly 15 → normal (not low)."""
        mock_cache.get.return_value = None
        with patch(PATCH_DB_CACHE) as mock_db:
            mock_db.return_value = {"price": 15.0, "stale": False}
            result = get_vix()
            assert result["level"] == "normal"

    @patch("services.price_service.cache")
    def test_vix_boundary_20(self, mock_cache):
        """VIX = exactly 20 → elevated (not normal)."""
        mock_cache.get.return_value = None
        with patch(PATCH_DB_CACHE) as mock_db:
            mock_db.return_value = {"price": 20.0, "stale": False}
            result = get_vix()
            assert result["level"] == "elevated"

    @patch("services.price_service.cache")
    def test_vix_boundary_30(self, mock_cache):
        """VIX = exactly 30 → high (not elevated)."""
        mock_cache.get.return_value = None
        with patch(PATCH_DB_CACHE) as mock_db:
            mock_db.return_value = {"price": 30.0, "stale": False}
            result = get_vix()
            assert result["level"] == "high"
