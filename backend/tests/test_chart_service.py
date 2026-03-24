"""Tests for 3-point reversal detection in chart_service."""

import pandas as pd
import pytest

from services.chart_service import detect_three_point_reversal, _find_swing_lows


def _make_series(prices: list[float]) -> pd.Series:
    """Create a daily close price series from a list of floats."""
    dates = pd.date_range("2025-01-01", periods=len(prices), freq="B")
    return pd.Series(prices, index=dates)


class TestFindSwingLows:
    def test_simple_trough(self):
        # V-shaped: 10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 12
        prices = [10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 12]
        series = _make_series(prices)
        lows = _find_swing_lows(series, lookback=3)
        assert len(lows) >= 1
        assert lows[0][1] == 6.0

    def test_not_enough_data(self):
        series = _make_series([10, 9, 10])
        lows = _find_swing_lows(series, lookback=5)
        assert lows == []


class TestDetectThreePointReversal:
    def test_clear_reversal_detected(self):
        """Three descending lows followed by a higher low → detected."""
        # Build a price series with 4 clear swing lows:
        # LL1 ~50, LL2 ~40, LL3 ~30, HL ~35
        prices = (
            [60, 58, 55, 53, 50, 48, 50, 53, 55, 58, 60] +  # LL1 at 48
            [58, 55, 50, 45, 40, 38, 40, 45, 50, 55, 58] +  # LL2 at 38
            [55, 50, 45, 40, 35, 28, 35, 40, 45, 50, 55] +  # LL3 at 28
            [52, 48, 45, 42, 40, 33, 40, 45, 50, 55, 58]     # HL at 33 (> 28)
        )
        series = _make_series(prices)
        result = detect_three_point_reversal(series, window=len(prices))

        assert result["detected"] is True
        assert result["ll3"] < result["ll2"] < result["ll1"]
        assert result["hl"] > result["ll3"]

    def test_no_reversal_only_falling(self):
        """Continuously falling prices — no higher low → not detected."""
        # 4 descending lows, no higher low
        prices = (
            [60, 58, 55, 53, 50, 48, 50, 53, 55, 58, 60] +  # low 48
            [58, 55, 50, 45, 40, 38, 40, 45, 50, 55, 58] +  # low 38
            [55, 50, 45, 40, 35, 28, 35, 40, 45, 50, 55] +  # low 28
            [50, 45, 40, 35, 30, 25, 30, 35, 40, 45, 50]     # low 25 (< 28, no HL)
        )
        series = _make_series(prices)
        result = detect_three_point_reversal(series, window=len(prices))

        assert result["detected"] is False

    def test_sideways_no_pattern(self):
        """Sideways movement — no descending lows → not detected."""
        prices = (
            [50, 48, 45, 43, 40, 43, 45, 48, 50, 52, 53] +  # low ~40
            [52, 50, 48, 45, 40, 45, 48, 50, 52, 53, 54] +  # low ~40
            [53, 50, 48, 45, 40, 45, 48, 50, 52, 53, 55] +  # low ~40
            [54, 52, 50, 48, 42, 48, 50, 52, 54, 55, 56]     # low ~42
        )
        series = _make_series(prices)
        result = detect_three_point_reversal(series, window=len(prices))

        assert result["detected"] is False

    def test_too_little_data(self):
        """Less than 30 data points → not detected."""
        series = _make_series([50, 45, 40, 35, 30, 35, 40])
        result = detect_three_point_reversal(series, window=60)

        assert result["detected"] is False

    def test_none_input(self):
        result = detect_three_point_reversal(None)
        assert result["detected"] is False

    def test_empty_series(self):
        series = pd.Series([], dtype=float)
        result = detect_three_point_reversal(series)
        assert result["detected"] is False

    def test_reversal_returns_dates(self):
        """When detected, result contains date strings."""
        prices = (
            [60, 58, 55, 53, 50, 48, 50, 53, 55, 58, 60] +
            [58, 55, 50, 45, 40, 38, 40, 45, 50, 55, 58] +
            [55, 50, 45, 40, 35, 28, 35, 40, 45, 50, 55] +
            [52, 48, 45, 42, 40, 33, 40, 45, 50, 55, 58]
        )
        series = _make_series(prices)
        result = detect_three_point_reversal(series, window=len(prices))

        assert result["detected"] is True
        assert "ll1_date" in result
        assert "ll2_date" in result
        assert "ll3_date" in result
        assert "hl_date" in result
        # Dates should be YYYY-MM-DD format
        assert len(result["ll1_date"]) == 10
