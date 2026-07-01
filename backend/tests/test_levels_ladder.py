"""Tests for the swing-low ladder in ``get_support_resistance_levels``.

Spec 2026-07-01 (``/analysis/levels`` → trailing-stop anchor). The function
now returns a spot-relative swing ladder + ATR(22) + HighestHigh(22), while
``support``/``resistance`` stay the 52-week close extremes (backward-compat).

All fixtures are synthetic OHLC frames — no network, no DB. ``yf_download`` and
the ``cache`` are patched so the pure geometry is exercised deterministically.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd

from services.chart_service import get_support_resistance_levels


# --- Fixtures -------------------------------------------------------------

def _ramp(a: float, b: float, n: int) -> list[float]:
    """``n`` strictly-monotone steps from a→b, excluding a, including b."""
    return [float(x) for x in np.linspace(a, b, n + 1)[1:]]


def _ohlc(closes: list[float], spread: float = 0.0, start: str = "2024-06-03") -> pd.DataFrame:
    """Daily OHLC frame from a close path. High/Low = close ± spread, so with
    spread=0 the swing pivots equal the close values exactly (clean asserts)."""
    idx = pd.date_range(start, periods=len(closes), freq="B")
    c = pd.Series([float(x) for x in closes], index=idx)
    return pd.DataFrame(
        {
            "Open": c,
            "High": c + spread,
            "Low": c - spread,
            "Close": c,
            "Volume": [1_000_000] * len(c),
        },
        index=idx,
    )


def _range_closes() -> list[float]:
    """Ranging path: troughs 60/70/80, peaks 85/95/100, spot 90."""
    controls = [80, 60, 85, 70, 95, 80, 100, 90]
    closes = [80.0]
    for v in controls[1:]:
        closes += _ramp(closes[-1], v, 6)
    return closes


def _parabola_closes() -> list[float]:
    """Base k-pivot at 40, then a vertical run to ~100 with a single k1
    reaction dip at 49 (a fresh vertical leg with no new k-pivot)."""
    p = [70.0, 58.0, 46.0, 40.0]      # descent to base pivot 40 (k2 low)
    p += _ramp(40, 52, 3)             # 44, 48, 52
    p += [49.0]                       # k1 reaction dip (>40, <spot; not a k2 low)
    p += _ramp(49, 100, 13)           # vertical run to spot 100
    return p


def _call(df, get_close=None, **kwargs):
    """Invoke the service with yf_download / cache / DB fallback patched."""
    with patch("services.chart_service.yf_download", return_value=df), \
         patch("services.chart_service._get_close_series", return_value=get_close), \
         patch("services.chart_service.cache.get", return_value=None), \
         patch("services.chart_service.cache.set") as mock_set:
        result = get_support_resistance_levels("TEST", **kwargs)
    return result, mock_set


# --- Ranging scenario: exact ladder, ordering, backward-compat -------------

class TestRangingLadder:
    def setup_method(self):
        self.res, self.mock_set = _call(_ohlc(_range_closes(), spread=0.0))

    def test_swing_lows_nearest_first(self):
        prices = [s["price"] for s in self.res["swing_lows"]]
        assert prices == [80.0, 70.0, 60.0]  # nearest (highest) below spot first

    def test_swing_lows_strictly_ordered_by_dist_atr(self):
        dists = [s["dist_atr"] for s in self.res["swing_lows"]]
        assert dists == sorted(dists)  # ascending distance = nearest first

    def test_swing_highs_nearest_first(self):
        prices = [s["price"] for s in self.res["swing_highs"]]
        assert prices == [95.0, 100.0]  # only pivots >= spot (90), nearest first

    def test_backward_compat_scalars_are_52w_extremes(self):
        assert self.res["support"] == 60.0     # 52W close low (unchanged meaning)
        assert self.res["resistance"] == 100.0  # 52W close high
        assert self.res["low_52w"] == 60.0
        assert self.res["high_52w"] == 100.0

    def test_historical_arrays_mirror_ladders(self):
        assert self.res["support_historical"] == [s["price"] for s in self.res["swing_lows"]]
        assert self.res["resistance_historical"] == [s["price"] for s in self.res["swing_highs"]]

    def test_every_level_has_metadata(self):
        for s in self.res["swing_lows"] + self.res["swing_highs"]:
            assert set(s) >= {"price", "date", "type", "touches", "dist_pct", "dist_atr"}
            assert len(s["date"]) == 10          # YYYY-MM-DD
            assert s["touches"] >= 1
            assert s["dist_atr"] is not None

    def test_atr_and_extremes_present(self):
        assert self.res["atr_22"] is not None and self.res["atr_22"] > 0
        assert self.res["atr_pct"] is not None
        assert self.res["highest_high_22"] == 100.0  # spread=0 → high == close
        assert self.res["as_of"] is not None
        assert self.res["current_price"] == 90.0

    def test_cache_ttl_short(self):
        assert self.mock_set.call_args.kwargs["ttl"] == 900

    def test_below_only_drops_resistances(self):
        res, _ = _call(_ohlc(_range_closes(), spread=0.0), below_only=True)
        assert res["swing_highs"] == []
        assert res["resistance_historical"] == []
        assert res["swing_lows"]                     # still present
        assert res["resistance"] == 100.0            # cheap 52W scalar kept


# --- Parabola scenario: reaction-low anchor + gap_bases --------------------

class TestParabolaFallback:
    def setup_method(self):
        # spread=5 so gap-up detection behaves like real OHLC (no spurious gaps
        # on the ~4-point daily steps). Pivots are read off the LOW = close-5.
        self.res, _ = _call(_ohlc(_parabola_closes(), spread=5.0))

    def test_gap_bases_populated(self):
        assert self.res["gap_bases"], "steep vertical leg must expose a reaction base"

    def test_nearest_low_is_reaction_type(self):
        first = self.res["swing_lows"][0]
        assert first["type"] == "reaction_low_k1"
        assert 40.0 < first["price"] < 50.0        # ≈ 44 (close 49 − spread 5)

    def test_base_pivot_below_reaction(self):
        prices = [s["price"] for s in self.res["swing_lows"]]
        assert prices == sorted(prices, reverse=True)   # nearest-first
        assert prices[-1] < prices[0]                    # base pivot deepest
        assert prices[-1] < 40.0                         # ≈ 35 (close 40 − spread 5)

    def test_reaction_above_base(self):
        # A trail only ratchets up: every gap base sits above the last k-pivot.
        base = min(s["price"] for s in self.res["swing_lows"])
        assert all(g["price"] > base for g in self.res["gap_bases"])

    def test_current_price_uses_close_not_low(self):
        assert self.res["current_price"] == 100.0


# --- Degenerate / fallback paths ------------------------------------------

class TestDataFallbacks:
    def test_empty_data_returns_full_skeleton(self):
        res, _ = _call(pd.DataFrame(), get_close=None)
        expected_keys = {
            "ticker", "as_of", "current_price", "atr_22", "atr_pct",
            "highest_high_22", "lowest_low_22", "high_52w", "low_52w",
            "swing_lows", "swing_highs", "gap_bases",
            "resistance", "support", "resistance_historical", "support_historical",
        }
        assert set(res) == expected_keys
        assert res["support"] is None and res["resistance"] is None
        assert res["swing_lows"] == [] and res["gap_bases"] == []

    def test_close_only_fallback_still_gives_52w_and_ladder(self):
        # yf gives nothing usable, but the DB close series does: 52W scalars and
        # the close-based ladder still work; ATR is null (no OHLC).
        closes = _range_closes()
        idx = pd.date_range("2024-06-03", periods=len(closes), freq="B")
        series = pd.Series(closes, index=idx)
        res, _ = _call(pd.DataFrame(), get_close=series)
        assert res["low_52w"] == 60.0 and res["high_52w"] == 100.0
        assert res["atr_22"] is None                 # no OHLC → no ATR
        assert [s["price"] for s in res["swing_lows"]] == [80.0, 70.0, 60.0]
        assert res["swing_lows"][0]["dist_atr"] is None   # no ATR → null distance

    def test_close_only_steep_parabola_has_no_phantom_gap_staircase(self):
        # Regression (review 2026-07-01): in the close-only fallback high==low==close,
        # so the gap-up test "low > prev_high" degenerates to "close > prev_close" and
        # would fire on every up-day — flooding gap_bases and pinning the trailing-stop
        # anchor ~1-2% below spot for exactly the parabolic names this feature targets.
        down = _ramp(55, 40, 50)          # monotone descent to base k2 pivot 40
        up = _ramp(40, 100, 15)           # strictly monotone steep run to spot 100
        closes = [55.0] + down + up
        idx = pd.date_range("2024-06-03", periods=len(closes), freq="B")
        res, _ = _call(pd.DataFrame(), get_close=pd.Series(closes, index=idx))
        assert res["gap_bases"] == []                      # no gaps derivable from closes
        # Anchor is the real base pivot, not a phantom up-day close a hair below spot.
        assert res["swing_lows"][0]["price"] == 40.0
        assert res["swing_lows"][0]["type"] == "swing_low_k2"
        assert not any(
            s["type"] == "reaction_low_k1" and s["dist_pct"] > -10.0
            for s in res["swing_lows"]
        )

    def test_params_are_clamped_not_crashing(self):
        # Out-of-range params must clamp (lookback→[30,260], pivot_k→[1,5]).
        res, _ = _call(_ohlc(_range_closes(), spread=0.0), lookback=99999, pivot_k=99)
        assert res["current_price"] == 90.0
        assert isinstance(res["swing_lows"], list)
