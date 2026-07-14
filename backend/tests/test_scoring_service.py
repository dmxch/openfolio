"""Tests for scoring_service: assess_ticker signal logic + constants."""

from unittest.mock import patch

from services.scoring_service import assess_ticker, SIGNAL_LABELS


class TestSignalLabels:
    def test_all_signals_have_labels(self):
        for signal in ["KAUFSIGNAL", "WATCHLIST", "BEOBACHTEN", "KEIN SETUP", "ETF_KAUFSIGNAL"]:
            assert signal in SIGNAL_LABELS
            assert len(SIGNAL_LABELS[signal]) > 0


class TestAssessTicker:
    """Tests assess_ticker with mocked score_stock + cache."""

    def _mock_setup(self, signal="KAUFSIGNAL", signal_label="Test", price=180.0, criteria=None):
        return {
            "ticker": "TEST",
            "price": price,
            "signal": signal,
            "signal_label": signal_label,
            "criteria": criteria or [],
            "score": 14,
            "max_score": 18,
        }

    @patch("services.scoring_service.cache")
    @patch("services.scoring_service.score_stock")
    def test_normal_stock_passthrough(self, mock_score, mock_cache):
        """Non-ETF ticker passes through score_stock signal."""
        mock_cache.get.return_value = None
        mock_score.return_value = self._mock_setup(signal="WATCHLIST", signal_label="Warten")

        result = assess_ticker("AAPL")
        assert result["signal"] == "WATCHLIST"
        assert result["is_whitelist_etf"] is False
        assert result["etf_buy_signal"] is False

    @patch("services.scoring_service.cache")
    @patch("services.scoring_service.score_stock")
    def test_etf_below_200dma(self, mock_score, mock_cache):
        """Broad ETF below 200-DMA → ETF_KAUFSIGNAL overrides normal signal."""
        mock_cache.get.return_value = None
        mock_score.return_value = self._mock_setup(
            signal="KEIN SETUP",
            price=400.0,
            criteria=[{"id": 1, "passed": False}],  # id=1 = Preis > MA200, passed=False
        )

        result = assess_ticker("VOO")
        assert result["signal"] == "ETF_KAUFSIGNAL"
        assert result["etf_buy_signal"] is True
        assert result["is_whitelist_etf"] is True

    @patch("services.scoring_service.cache")
    @patch("services.scoring_service.score_stock")
    def test_etf_above_200dma(self, mock_score, mock_cache):
        """Broad ETF above 200-DMA → normal signal logic."""
        mock_cache.get.return_value = None
        mock_score.return_value = self._mock_setup(
            signal="WATCHLIST",
            signal_label="Warten",
            price=400.0,
            criteria=[{"id": 1, "passed": True}],  # above MA200
        )

        result = assess_ticker("VOO")
        assert result["signal"] == "WATCHLIST"
        assert result["etf_buy_signal"] is False

    @patch("services.scoring_service.cache")
    def test_cached_result(self, mock_cache):
        """Cached assessment returned directly."""
        cached_data = {"signal": "KAUFSIGNAL", "cached": True}
        mock_cache.get.return_value = cached_data

        result = assess_ticker("AAPL")
        assert result == cached_data


class TestBondNoStockSetup:
    """Anleihen sind vom Aktien-Scoring ausgenommen (Soll-Matrix).

    Die 19-Punkte-Checkliste misst Aktien-Trend und relative Staerke gegen
    ^GSPC. Auf einen Bond-ETF angewandt ist das kein schwaches Setup, sondern
    ein Kategorienfehler.
    """

    @patch("services.scoring_service.cache")
    @patch("services.scoring_service.score_stock")
    def test_bond_returns_not_applicable(self, mock_score, mock_cache):
        mock_cache.get.return_value = None
        result = assess_ticker("IB01.L", asset_type="bond")

        assert result["not_applicable"] is True
        assert result["signal"] == "NICHT_ANWENDBAR"
        assert result["mansfield_rs"] is None
        assert result["criteria"] == []
        # Der teure Aktien-Pfad darf gar nicht erst laufen.
        mock_score.assert_not_called()

    @patch("services.scoring_service.cache")
    @patch("services.scoring_service.score_stock")
    def test_bond_does_not_poison_the_shared_cache(self, mock_score, mock_cache):
        """Der Cache-Key kennt den asset_type nicht: wuerde der Bond-Zweig nach
        dem Cache greifen, verfaelschte er denselben Ticker fuer andere Aufrufer."""
        mock_cache.get.return_value = None
        assess_ticker("IB01.L", asset_type="bond")

        mock_cache.set.assert_not_called()

    @patch("services.scoring_service.cache")
    @patch("services.scoring_service.score_stock")
    def test_other_types_still_scored(self, mock_score, mock_cache):
        """Nur bond ist ausgenommen — Aktien/ETFs laufen unveraendert."""
        mock_cache.get.return_value = None
        mock_score.return_value = self._setup()

        for t in ("stock", "etf", "crypto", "commodity", None):
            mock_score.reset_mock()
            result = assess_ticker("AAPL", asset_type=t)
            assert not result.get("not_applicable"), f"{t} darf nicht ausgenommen sein"
            mock_score.assert_called_once()

    def _setup(self):
        return {
            "ticker": "AAPL",
            "price": 180.0,
            "signal": "WATCHLIST",
            "signal_label": "Warten",
            "criteria": [],
            "score": 14,
            "max_score": 18,
        }
