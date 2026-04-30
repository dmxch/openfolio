"""Tests for sector_rotation_service.classify_ticker.

The service is a pure function — no DB, no IO. The whole point of the
service-level batched-loading split was to make this rule logic
unit-testable in isolation. These tests exercise all five classification
branches plus the three edge-cases that were specified in the design
plan as critical: Bear-Market-Median, Bull-Trap-3M, and concentrated
override.
"""
from decimal import Decimal

import pytest

from services.screening import sector_rotation_config as cfg
from services.screening.sector_rotation_service import (
    MOMENTUM_CONCENTRATED,
    MOMENTUM_HEADWIND,
    MOMENTUM_NEUTRAL,
    MOMENTUM_TAILWIND,
    MOMENTUM_UNKNOWN,
    classify_ticker,
)


def _industry_metrics(
    *,
    perf_1m: float | None = 5.0,
    perf_3m: float | None = 8.0,
    rvol: float | None = 1.5,
    top1_weight: float | None = 0.2,
    effective_n: float | None = 20.0,
) -> dict:
    """Helper: build an industry metrics dict with sensible defaults that
    by themselves classify as ``tailwind`` (so each test only has to
    override the relevant fields)."""
    return {
        "perf_1m": Decimal(str(perf_1m)) if perf_1m is not None else None,
        "perf_3m": Decimal(str(perf_3m)) if perf_3m is not None else None,
        "rvol_20d": Decimal(str(rvol)) if rvol is not None else None,
        "top1_weight": Decimal(str(top1_weight)) if top1_weight is not None else None,
        "effective_n": Decimal(str(effective_n)) if effective_n is not None else None,
    }


# Default median used by most tests: 1.0% — perf_1m=5.0 sits cleanly above it.
DEFAULT_MEDIAN = Decimal("1.0")


class TestClassifyTicker:
    """Unit tests for the pure classify_ticker function."""

    def test_tailwind_full_match(self):
        """All four conditions met → tailwind, +WEIGHT_SECTOR_TAILWIND."""
        result = classify_ticker(
            "AAPL",
            ticker_industry_map={"AAPL": "Software - Application"},
            industry_metrics_map={"Software - Application": _industry_metrics()},
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.industry_name == "Software - Application"
        assert result.momentum == MOMENTUM_TAILWIND
        assert result.sector_bonus == cfg.WEIGHT_SECTOR_TAILWIND
        assert result.sector_bonus == 1

    def test_headwind_full_match(self):
        """perf_1m < median, < 0, rvol < threshold → headwind (bonus default 0)."""
        result = classify_ticker(
            "XYZ",
            ticker_industry_map={"XYZ": "Solar"},
            industry_metrics_map={
                "Solar": _industry_metrics(perf_1m=-5.0, perf_3m=-10.0, rvol=0.6),
            },
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.momentum == MOMENTUM_HEADWIND
        assert result.sector_bonus == cfg.WEIGHT_SECTOR_HEADWIND
        assert result.sector_bonus == 0

    def test_neutral_above_median_but_low_rvol(self):
        """perf_1m above median + 0 + perf_3m positive but rvol < threshold → neutral."""
        result = classify_ticker(
            "AAPL",
            ticker_industry_map={"AAPL": "Software - Application"},
            industry_metrics_map={
                "Software - Application": _industry_metrics(rvol=0.9),
            },
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.momentum == MOMENTUM_NEUTRAL
        assert result.sector_bonus == 0

    def test_concentrated_top1_weight_blocks_tailwind(self):
        """Even with all tailwind conditions met, top1_weight > 0.5 → concentrated."""
        result = classify_ticker(
            "ASML",
            ticker_industry_map={"ASML": "Semiconductor Equipment"},
            industry_metrics_map={
                "Semiconductor Equipment": _industry_metrics(top1_weight=0.65),
            },
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.momentum == MOMENTUM_CONCENTRATED
        assert result.sector_bonus == 0

    def test_concentrated_effective_n_blocks_tailwind(self):
        """effective_n < 5 → concentrated even with safe top1_weight."""
        result = classify_ticker(
            "AMAT",
            ticker_industry_map={"AMAT": "Semiconductor Equipment"},
            industry_metrics_map={
                "Semiconductor Equipment": _industry_metrics(top1_weight=0.3, effective_n=3.5),
            },
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.momentum == MOMENTUM_CONCENTRATED
        assert result.sector_bonus == 0

    def test_unknown_ticker_not_in_map(self):
        """SIX-CH ticker (or any non-US) lacks a row → unknown, bonus 0."""
        result = classify_ticker(
            "NESN.SW",
            ticker_industry_map={"AAPL": "Software - Application"},
            industry_metrics_map={"Software - Application": _industry_metrics()},
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.industry_name is None
        assert result.momentum == MOMENTUM_UNKNOWN
        assert result.sector_bonus == 0

    def test_bear_market_median_floor_blocks_relative_tailwind(self):
        """In a broad bear market the median can be negative. A ticker whose
        industry is "above median" but still absolutely negative must NOT
        be classified as tailwind — that's the perf_1m > 0 safety floor."""
        result = classify_ticker(
            "AAPL",
            ticker_industry_map={"AAPL": "Software - Application"},
            industry_metrics_map={
                # perf_1m=-2 is above median=-5, but absolutely negative
                "Software - Application": _industry_metrics(perf_1m=-2.0, perf_3m=1.0),
            },
            median_perf_1m=Decimal("-5.0"),
        )
        assert result.momentum != MOMENTUM_TAILWIND
        # It also should not classify as headwind: perf_1m > median, not <
        assert result.momentum == MOMENTUM_NEUTRAL

    def test_bull_trap_blocked_by_3m_confirm(self):
        """Classic Solar-bounce scenario: perf_1m positive and above median +
        rvol high, but 3M still negative. The perf_3m > 0 confirm must
        block the tailwind classification — otherwise we score Mean-Reversion
        bounces in structurally bear branches as bullish."""
        result = classify_ticker(
            "SOLAR_X",
            ticker_industry_map={"SOLAR_X": "Solar"},
            industry_metrics_map={
                "Solar": _industry_metrics(perf_1m=8.0, perf_3m=-15.0, rvol=2.0),
            },
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.momentum != MOMENTUM_TAILWIND
        assert result.momentum == MOMENTUM_NEUTRAL

    def test_concentrated_blocks_on_top1_ticker_itself(self):
        """The dominant ticker in a concentrated branche (e.g. SPHR in
        Media Conglomerates) gets the same concentrated classification —
        it does NOT get a tailwind bonus from "its own" branche performance."""
        result = classify_ticker(
            "SPHR",
            ticker_industry_map={"SPHR": "Media Conglomerates"},
            industry_metrics_map={
                "Media Conglomerates": _industry_metrics(top1_weight=0.7),
            },
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.momentum == MOMENTUM_CONCENTRATED
        assert result.sector_bonus == 0

    def test_unknown_when_metrics_missing(self):
        """Ticker has industry mapping but the industry has no metrics row
        in the latest snapshot (e.g. brand-new industry on TradingView).
        Returns unknown with the industry_name preserved."""
        result = classify_ticker(
            "AAPL",
            ticker_industry_map={"AAPL": "Some Brand New Industry"},
            industry_metrics_map={},  # empty
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.industry_name == "Some Brand New Industry"
        assert result.momentum == MOMENTUM_UNKNOWN

    def test_unknown_when_median_unavailable(self):
        """No median (e.g. fresh install before any snapshot ran) → unknown
        even if the ticker has an industry row, because tailwind/headwind
        cannot be evaluated without a baseline."""
        result = classify_ticker(
            "AAPL",
            ticker_industry_map={"AAPL": "Software - Application"},
            industry_metrics_map={"Software - Application": _industry_metrics()},
            median_perf_1m=None,
        )
        assert result.momentum == MOMENTUM_UNKNOWN

    def test_ticker_lookup_is_case_insensitive(self):
        """Tickers come from disparate scrapers and may be lowercased.
        The map is keyed uppercase by the scraper; classify_ticker normalises."""
        result = classify_ticker(
            "aapl",
            ticker_industry_map={"AAPL": "Software - Application"},
            industry_metrics_map={"Software - Application": _industry_metrics()},
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.momentum == MOMENTUM_TAILWIND


class TestThresholdBoundaries:
    """Spot-checks on the strict-greater/less-than comparisons in the rules."""

    def test_tailwind_requires_strict_above_median(self):
        """perf_1m exactly equal to median → not tailwind (must be strictly >)."""
        result = classify_ticker(
            "AAPL",
            ticker_industry_map={"AAPL": "X"},
            industry_metrics_map={
                "X": _industry_metrics(perf_1m=1.0),  # equals median
            },
            median_perf_1m=Decimal("1.0"),
        )
        assert result.momentum != MOMENTUM_TAILWIND

    def test_concentration_threshold_strict_greater(self):
        """top1_weight exactly at threshold (0.5) is NOT concentrated;
        only > 0.5 trips it. Reproduces the cfg constant exactly."""
        result = classify_ticker(
            "X",
            ticker_industry_map={"X": "Y"},
            industry_metrics_map={
                "Y": _industry_metrics(top1_weight=float(cfg.TOP1_CONCENTRATION_THRESHOLD)),
            },
            median_perf_1m=DEFAULT_MEDIAN,
        )
        assert result.momentum != MOMENTUM_CONCENTRATED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
