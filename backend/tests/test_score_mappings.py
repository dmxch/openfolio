"""Tests fuer die Score-Mapping-Kandidaten (Iteration-2.5 Item D).

Reine Pure-Function-Tests, keine DB-Abhaengigkeit. Der Context-Builder
`build_percentile_ctx` wird in Item E (Backtest-Harness) gegen die echte
DB getestet, hier nur die Mapper.
"""
from __future__ import annotations

import pytest

from services.screening.score_mappings import (
    MAPPINGS,
    hybrid,
    linear,
    log10_stretched,
    percentile,
)


# --- linear (Baseline-Sanity) ---------------------------------------------


def test_linear_basis():
    assert linear(0) == 0
    assert linear(5) == 50
    assert linear(10) == 100


def test_linear_clamps_out_of_range():
    assert linear(-1) == 0
    assert linear(11) == 100
    assert linear(999) == 100


def test_linear_ignores_ctx():
    assert linear(5, {"cdf": [(1, 99)]}) == 50


# --- log10_stretched ------------------------------------------------------


def test_log10_endpoints():
    assert log10_stretched(0) == 0
    assert log10_stretched(10) == 100
    assert log10_stretched(-3) == 0


def test_log10_stretches_lower_band_above_linear():
    # Kern-Eigenschaft: untere Population bekommt mehr Display-Spread.
    # raw=3 wandert von 30 (linear) auf ~58.
    assert log10_stretched(3) > linear(3)
    assert log10_stretched(2) > linear(2)
    assert log10_stretched(1) > linear(1)


def test_log10_clamps_above_10():
    assert log10_stretched(11) == 100
    assert log10_stretched(100) == 100


# --- percentile -----------------------------------------------------------


def test_percentile_empty_cdf_returns_zero():
    assert percentile(5, {"cdf": []}) == 0
    assert percentile(5, {}) == 0
    assert percentile(5, None) == 0


def test_percentile_negative_or_zero_raw():
    assert percentile(0, {"cdf": [(1, 19), (2, 62)]}) == 0
    assert percentile(-3, {"cdf": [(1, 19), (2, 62)]}) == 0


def test_percentile_returns_cumulative_rank():
    # CDF analog zur Item-C-Diagnose (gerundet).
    cdf = [(1, 19), (2, 62), (3, 96), (4, 98), (5, 100), (6, 100)]
    assert percentile(1, {"cdf": cdf}) == 19
    assert percentile(2, {"cdf": cdf}) == 62
    assert percentile(3, {"cdf": cdf}) == 96
    assert percentile(5, {"cdf": cdf}) == 100


def test_percentile_above_max_returns_100():
    cdf = [(1, 50), (2, 100)]
    assert percentile(99, {"cdf": cdf}) == 100


def test_percentile_first_match_wins_on_duplicates():
    # Defensive: Builder soll dedupen, aber wenn nicht, gewinnt der
    # erste Match (= niedrigeres Perzentil) — sicherer Default als
    # einen mittleren Wert zu interpolieren.
    cdf = [(2, 50), (2, 60), (3, 100)]
    assert percentile(2, {"cdf": cdf}) == 50


# --- hybrid ---------------------------------------------------------------


def test_hybrid_lower_band_matches_linear():
    assert hybrid(0) == 0
    assert hybrid(1) == 10
    assert hybrid(2) == 20
    assert hybrid(3) == 30


def test_hybrid_crossover_continuous_at_raw_3_to_4():
    # "Stetig" hier = monoton, kein Negativ-Sprung. linear(3)=30,
    # hybrid(4) muss >= 40 sein (eigener Skala-Bereich [40,100]).
    upper_cdf = [(4, 60), (5, 90), (6, 100)]
    assert hybrid(3, {"upper_cdf": upper_cdf}) == 30
    assert hybrid(4, {"upper_cdf": upper_cdf}) >= 40
    assert hybrid(4, {"upper_cdf": upper_cdf}) > hybrid(3, {"upper_cdf": upper_cdf})


def test_hybrid_upper_band_uses_upper_cdf():
    upper_cdf = [(4, 60), (5, 90), (6, 100)]
    assert hybrid(4, {"upper_cdf": upper_cdf}) == 60
    assert hybrid(5, {"upper_cdf": upper_cdf}) == 90
    assert hybrid(6, {"upper_cdf": upper_cdf}) == 100


def test_hybrid_above_upper_cdf_returns_100():
    upper_cdf = [(4, 60), (5, 90)]
    assert hybrid(10, {"upper_cdf": upper_cdf}) == 100


def test_hybrid_empty_upper_cdf_floor_40():
    # Wenn kein Upper-Bucket vorhanden (Kaltstart), Decision-Layer
    # mindestens auf Display 40 setzen statt auf 0 zu fallen.
    assert hybrid(4) == 40
    assert hybrid(4, {"upper_cdf": []}) == 40


def test_hybrid_negative_raw():
    assert hybrid(-1) == 0
    assert hybrid(-5, {"upper_cdf": [(4, 60)]}) == 0


# --- MAPPINGS Registry ----------------------------------------------------


def test_mappings_registry_complete():
    assert set(MAPPINGS.keys()) == {"linear", "log10_stretched", "percentile", "hybrid"}
    # Alle callable mit gleicher Signatur.
    for name, fn in MAPPINGS.items():
        result = fn(5, {"cdf": [(5, 80)], "upper_cdf": [(5, 80)]})
        assert isinstance(result, int), f"{name} liefert keinen int"
        assert 0 <= result <= 100, f"{name} out of [0,100]: {result}"
