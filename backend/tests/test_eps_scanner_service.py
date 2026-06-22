"""Tests fuer die reine Berechnungslogik des EPS-Scanners.

Pure-Function-Design: kein DB-/Netzwerk-Zugriff noetig. Synthetische
EPS-Reihen werden ueber den `_quarters`-Helfer gebaut.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.eps_scanner_service import (
    DEFAULT_ACCELERATION_MARGIN,
    DEFAULT_OUTLIER_MULTIPLIER,
    DEFAULT_YOY_THRESHOLD,
    QuarterPoint,
    Thresholds,
    compute_metrics,
    parse_finnhub_eps,
    parse_yfinance_earnings,
    _serialize_status,
)

DEFAULT_THRESHOLDS = Thresholds(
    yoy_threshold=DEFAULT_YOY_THRESHOLD,
    acceleration_margin=DEFAULT_ACCELERATION_MARGIN,
    outlier_multiplier=DEFAULT_OUTLIER_MULTIPLIER,
)


def _quarters(eps_values: list[float], source: str = "finnhub") -> list[QuarterPoint]:
    """Baue eine chronologisch aufsteigende QuarterPoint-Liste (oldest→newest)."""
    base = date(2023, 3, 31)
    points: list[QuarterPoint] = []
    for i, v in enumerate(eps_values):
        points.append(
            QuarterPoint(
                period_end=base + timedelta(days=91 * i),
                eps=float(v),
                source=source,
                fetched_at=None,
            )
        )
    return points


def _metrics(eps_values: list[float], thresholds: Thresholds = DEFAULT_THRESHOLDS) -> dict:
    return compute_metrics(_quarters(eps_values), thresholds)


# --- YoY-Berechnung --------------------------------------------------------

def test_yoy_pos_to_pos():
    m = _metrics([1.0, 1.0, 1.0, 1.0, 1.1, 1.1, 1.1, 1.1, 2.0])
    assert m["yoy_flag"] == "pos_to_pos"
    # (2.0 - 1.1) / 1.1 * 100 = 81.82
    assert m["yoy_growth_pct"] == pytest.approx(81.82, abs=0.01)
    assert m["latest_eps"] == 2.0


def test_yoy_turnaround_growth_is_null():
    m = _metrics([-0.4, 0.1, 0.1, 0.1, 0.3])
    assert m["yoy_flag"] == "turnaround"
    assert m["yoy_growth_pct"] is None


def test_yoy_zero_basis():
    m = _metrics([0.0, 0.1, 0.1, 0.1, 0.5])
    assert m["yoy_flag"] == "zero_basis"
    assert m["yoy_growth_pct"] is None


def test_yoy_pos_to_neg():
    m = _metrics([1.0, 1.0, 1.0, 1.0, -0.2])
    assert m["yoy_flag"] == "pos_to_neg"
    assert m["yoy_growth_pct"] is None


def test_yoy_neg_to_neg():
    m = _metrics([-0.5, -0.1, -0.1, -0.1, -0.3])
    assert m["yoy_flag"] == "neg_to_neg"
    assert m["yoy_growth_pct"] is None


# --- Outlier-Guard ---------------------------------------------------------

def test_outlier_guard_triggers():
    m = _metrics([0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 17.0])
    assert m["outlier_flag"] is True
    # Super-Quartal wird durch D ausgeschlossen
    assert m["super_quarter"] is False


def test_outlier_guard_does_not_trigger_on_steady_growth():
    m = _metrics([1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3])
    assert m["outlier_flag"] is False


def test_outlier_guard_skips_on_nonpositive_median():
    # Median der Vorquartale <= 0 → Guard greift nicht (Turnaround, kein Outlier)
    m = _metrics([-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, 5.0])
    assert m["outlier_flag"] is False


# --- Record-Quartal --------------------------------------------------------

def test_record_quarter_strict_greater():
    m = _metrics([1.0, 1.0, 1.0, 1.0, 1.1, 1.1, 1.1, 1.1, 2.0])
    assert m["record_quarter"] is True


def test_record_quarter_equal_is_not_record():
    m = _metrics([1.0, 1.0, 1.0, 1.0, 1.0])
    assert m["record_quarter"] is False


def test_record_quarter_window_is_eight_prior():
    # Index 0 (5.0) liegt ausserhalb der 8 Vorquartale → Record trotzdem true,
    # weil das juengste (1.5) das Max der letzten 8 Vorquartale (1.0) schlaegt.
    m = _metrics([5.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.5])
    assert m["record_quarter"] is True


def test_record_quarter_turnaround():
    m = _metrics([-0.4, 0.1, 0.1, 0.1, 0.3])
    assert m["record_quarter"] is True
    assert m["record_quarter_turnaround"] is True


def test_record_quarter_outlier_flag():
    m = _metrics([0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 17.0])
    assert m["record_quarter"] is True
    assert m["record_quarter_outlier"] is True


def test_no_record_quarter_without_prior_window():
    m = _metrics([1.4])
    assert m["record_quarter"] is False


# --- Streak-Count ----------------------------------------------------------

def test_streak_count_all_growing():
    m = _metrics([1.0, 1.0, 1.0, 1.0, 1.1, 1.1, 1.1, 1.1, 2.0])
    # YoY berechnet fuer Indizes 4..8, alle pos_to_pos und > 0
    assert m["streak_count"] == 5


def test_streak_count_mixed():
    m = _metrics([5.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.5])
    # Nur das juengste Quartal hat positives pos_to_pos-YoY
    assert m["streak_count"] == 1


# --- Super-Quartal ---------------------------------------------------------

def test_super_quarter_all_criteria_met():
    m = _metrics([1.0, 1.0, 1.0, 1.0, 1.1, 1.1, 1.1, 1.1, 2.0])
    assert m["super_quarter"] is True


def test_super_quarter_criterion_c_dropped_with_few_priors():
    # Nur 5 Quartale → keine 2 vorherigen pos_to_pos-YoY-Raten → C entfaellt.
    # A+B+D erfuellt → super_quarter True.
    m = _metrics([1.0, 1.0, 1.0, 1.0, 1.5])
    assert m["super_quarter"] is True


def test_super_quarter_fails_below_yoy_threshold():
    # Wachstum 10% < 25% Default → B faellt → kein Super-Quartal.
    m = _metrics([1.0, 1.0, 1.0, 1.0, 1.1])
    assert m["yoy_flag"] == "pos_to_pos"
    assert m["super_quarter"] is False


def test_super_quarter_fails_acceleration_criterion_c():
    # Prior-YoY-Raten = 40%, juengstes YoY = 30%: B erfuellt (30 >= 25),
    # aber C scheitert (30 < median(40,40,40) + 5pp = 45) → kein Super-Quartal.
    eps = [1.0, 1.0, 1.0, 1.0, 1.0, 1.4, 1.4, 1.4, 1.3]
    m = _metrics(eps)
    assert m["yoy_flag"] == "pos_to_pos"
    assert m["yoy_growth_pct"] == pytest.approx(30.0, abs=0.01)
    assert m["super_quarter"] is False


def test_super_quarter_excluded_for_turnaround():
    m = _metrics([-0.4, 0.1, 0.1, 0.1, 0.3])
    assert m["super_quarter"] is False


# --- quarter_count / Display ----------------------------------------------

def test_quarter_count_and_display_cap():
    eps = [float(i) for i in range(1, 11)]  # 10 Quartale
    m = _metrics(eps)
    assert m["quarter_count"] == 10
    # Display ist auf die letzten 8 Quartale begrenzt
    assert len(m["quarters"]) == 8


# --- Parsing ---------------------------------------------------------------

def test_parse_finnhub_eps_sorts_ascending():
    payload = {
        "series": {
            "quarterly": {
                "eps": [
                    {"period": "2025-10-26", "v": 0.93},
                    {"period": "2025-07-27", "v": 1.21},
                    {"period": "2026-01-25", "v": 1.40},
                ]
            }
        }
    }
    parsed = parse_finnhub_eps(payload)
    assert [p[0].isoformat() for p in parsed] == [
        "2025-07-27", "2025-10-26", "2026-01-25",
    ]
    assert float(parsed[-1][1]) == 1.40


def test_parse_finnhub_eps_handles_missing_series():
    assert parse_finnhub_eps({}) == []
    assert parse_finnhub_eps(None) == []
    assert parse_finnhub_eps({"series": {}}) == []


def test_parse_yfinance_earnings_handles_none():
    assert parse_yfinance_earnings(None) == []


def test_serialize_status_fits_appsetting_column_when_all_missing():
    """Regression (Audit #1): Degraded-Fall (kein Key → alle Ticker missing)
    darf AppSetting.value (String(500)) NICHT ueberschreiten."""
    payload = {
        "last_run": "2026-06-22T04:17:33.123456+00:00",
        "tickers_total": 503,
        "tickers_fetched": 0,
        "tickers_finnhub": 0,
        "tickers_yfinance_fallback": 0,
        "tickers_missing": 503,
        "missing_tickers": [f"TICK{i:03d}" for i in range(503)],
        "finnhub_key_configured": False,
        "job_status": "completed",
    }
    value = _serialize_status(payload)
    assert len(value) <= 500
    # Kernfelder bleiben erhalten, nur das diagnostische Sample wird gekuerzt.
    import json
    parsed = json.loads(value)
    assert parsed["tickers_missing"] == 503
    assert parsed["job_status"] == "completed"
    assert len(parsed["missing_tickers"]) < 503
