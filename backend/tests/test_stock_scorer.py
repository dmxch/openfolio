"""Tests for stock_scorer: signal determination, breakout trigger, formatting helpers."""

import pytest

from services.stock_scorer import determine_signal, check_breakout_trigger, _fmt_large, _fmt_pct


# --- determine_signal() ---

class TestDetermineSignal:
    """Tests the signal matrix: STARK/MODERAT/SCHWACH × breakout triggered."""

    def test_stark_with_breakout(self):
        """≥70% + breakout → KAUFSIGNAL."""
        result = determine_signal(14, 18, {"triggered": True})
        assert result["signal"] == "KAUFSIGNAL"
        assert result["quality"] == "STARK"

    def test_stark_without_breakout(self):
        """≥70% + no breakout → WATCHLIST."""
        result = determine_signal(14, 18, {"triggered": False})
        assert result["signal"] == "WATCHLIST"
        assert result["quality"] == "STARK"

    def test_moderat(self):
        """45-69% → BEOBACHTEN regardless of breakout."""
        result = determine_signal(9, 18, {"triggered": True})
        assert result["signal"] == "BEOBACHTEN"
        assert result["quality"] == "MODERAT"

    def test_schwach(self):
        """<45% → KEIN SETUP."""
        result = determine_signal(5, 18, {"triggered": False})
        assert result["signal"] == "KEIN SETUP"
        assert result["quality"] == "SCHWACH"

    def test_boundary_70_percent(self):
        """Exactly 70% → STARK."""
        # 70% of 20 = 14
        result = determine_signal(14, 20, {"triggered": False})
        assert result["quality"] == "STARK"

    def test_boundary_45_percent(self):
        """Exactly 45% → MODERAT."""
        # 45% of 20 = 9
        result = determine_signal(9, 20, {"triggered": False})
        assert result["quality"] == "MODERAT"

    def test_zero_max(self):
        """Edge case: max_score=0 → SCHWACH."""
        result = determine_signal(0, 0, {"triggered": False})
        assert result["quality"] == "SCHWACH"

    def test_signal_label_present(self):
        result = determine_signal(14, 18, {"triggered": True})
        assert "signal_label" in result
        assert len(result["signal_label"]) > 0


# --- check_breakout_trigger() ---

class TestCheckBreakoutTrigger:
    """Tests breakout detection logic with mocked analysis dicts."""

    def _make_analysis(self, current=180.0, ch_high=175.0, ch_low=160.0,
                       current_vol=500_000, avg_vol_20=200_000):
        return {
            "mas": {"current": current},
            "donchian": {"channel_high": ch_high, "channel_low": ch_low,
                         "last_breakout_date": None, "last_breakout_price": None},
            "range_data": {"high_52w": 190.0, "low_52w": 140.0},
            "current_volume": current_vol,
            "avg_volume_20": avg_vol_20,
            "avg_volume_50": avg_vol_20,
        }

    def test_breakout_triggered(self):
        """Price above channel + volume ≥ 1.5x → triggered."""
        analysis = self._make_analysis(current=180.0, ch_high=175.0, current_vol=400_000, avg_vol_20=200_000)
        result = check_breakout_trigger("TEST", analysis)
        assert result["triggered"] is True
        assert result["breakout_price"] is True
        assert result["volume_confirmation"] is True

    def test_price_below_channel(self):
        """Price below channel high → not triggered."""
        analysis = self._make_analysis(current=170.0, ch_high=175.0)
        result = check_breakout_trigger("TEST", analysis)
        assert result["triggered"] is False
        assert result["breakout_price"] is False

    def test_volume_insufficient(self):
        """Price breaks out but volume too low → not triggered."""
        analysis = self._make_analysis(current=180.0, ch_high=175.0, current_vol=250_000, avg_vol_20=200_000)
        result = check_breakout_trigger("TEST", analysis)
        assert result["triggered"] is False
        assert result["volume_confirmation"] is False

    def test_manual_resistance(self):
        """Manual resistance overrides Donchian channel."""
        analysis = self._make_analysis(current=180.0, ch_high=175.0, current_vol=400_000, avg_vol_20=200_000)
        result = check_breakout_trigger("TEST", analysis, manual_resistance=185.0)
        assert result["triggered"] is False
        assert result["resistance_source"] == "manual"
        assert result["resistance"] == 185.0

    def test_no_data(self):
        analysis = {"mas": {}, "donchian": {}, "range_data": {}, "current_volume": 0, "avg_volume_20": 0}
        result = check_breakout_trigger("TEST", analysis)
        assert result["triggered"] is False


# --- Formatting helpers ---

class TestFmtLarge:
    def test_billions(self):
        assert _fmt_large(2_500_000_000) == "2.5 Mrd"

    def test_millions(self):
        assert _fmt_large(150_000_000) == "150.0 Mio"

    def test_thousands(self):
        assert _fmt_large(5_000) == "5k"

    def test_small(self):
        assert _fmt_large(42) == "42"

    def test_none(self):
        assert _fmt_large(None) == "N/A"


class TestFmtPct:
    def test_normal(self):
        assert _fmt_pct(0.123) == "12.3%"

    def test_none(self):
        assert _fmt_pct(None) == "N/A"

    def test_zero(self):
        assert _fmt_pct(0) == "0.0%"
