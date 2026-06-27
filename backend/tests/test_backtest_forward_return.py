"""Unit-Tests fuer die reine Forward-Return-Berechnung des Backtest-Harness.

Getestet wird ausschliesslich ``compute_forward_return`` — reine Compute-Logik
auf synthetischen ``pd.Series`` mit DatetimeIndex, keine DB, kein Netz, kein
yfinance-Call. Stil orientiert an tests/test_golden_master_calculations.py
(pandas.Series + pytest.approx).

Abgedeckt:
  - normaler Return (entry 100 -> exit 112 => 0.12)
  - unvollstaendiges Fenster (scan_date + days > today) -> None
  - fehlender Entry ohne / mit entry_fallback
  - entry <= 0 -> None
  - Handelstags-Versatz (scan_date faellt auf ein Wochenende)
"""
from datetime import date

import pandas as pd
import pytest

from services.screening.backtest_harness import compute_forward_return


def _series(points: dict[str, float]) -> pd.Series:
    """Baue eine Kursserie aus {ISO-Datum: Preis} mit DatetimeIndex."""
    idx = pd.to_datetime(list(points.keys()))
    return pd.Series(list(points.values()), index=idx)


class TestComputeForwardReturn:
    def test_normal_return(self):
        # Entry 100 am Scan-Tag, Exit 112 am Exit-Target (30 Tage spaeter).
        prices = _series({"2024-01-02": 100.0, "2024-02-01": 112.0})
        result = compute_forward_return(
            prices, date(2024, 1, 2), 30, today=date(2024, 6, 1)
        )
        assert result == pytest.approx(0.12, abs=1e-9)

    def test_negative_return(self):
        prices = _series({"2024-01-02": 100.0, "2024-02-01": 90.0})
        result = compute_forward_return(
            prices, date(2024, 1, 2), 30, today=date(2024, 6, 1)
        )
        assert result == pytest.approx(-0.10, abs=1e-9)

    def test_incomplete_window_returns_none(self):
        # Exit-Target (2024-04-01) liegt nach today -> Fenster nicht abgeschlossen.
        prices = _series({"2024-01-02": 100.0, "2024-04-01": 130.0})
        result = compute_forward_return(
            prices, date(2024, 1, 2), 90, today=date(2024, 2, 1)
        )
        assert result is None

    def test_window_ending_exactly_today_is_complete(self):
        # exit_target == today ist noch abgeschlossen (nicht in der Zukunft).
        prices = _series({"2024-01-02": 100.0, "2024-02-01": 105.0})
        result = compute_forward_return(
            prices, date(2024, 1, 2), 30, today=date(2024, 2, 1)
        )
        assert result == pytest.approx(0.05, abs=1e-9)

    def test_missing_entry_without_fallback_returns_none(self):
        # Serie endet komplett VOR scan_date -> kein Entry, kein Fallback.
        prices = _series({"2023-12-01": 100.0, "2023-12-15": 101.0})
        result = compute_forward_return(
            prices, date(2024, 1, 2), 30, today=date(2024, 6, 1)
        )
        assert result is None

    def test_missing_entry_with_fallback_uses_fallback(self):
        # Nur das Exit-Target liegt in der Serie; im Entry-Fenster
        # [scan_date, exit_target) gibt es keinen Handelstag -> Fallback greift.
        prices = _series({"2024-02-01": 110.0})
        result = compute_forward_return(
            prices, date(2024, 1, 2), 30, today=date(2024, 6, 1),
            entry_fallback=100.0,
        )
        # Exit 110 / Fallback-Entry 100 - 1 = 0.10
        assert result == pytest.approx(0.10, abs=1e-9)

    def test_entry_from_series_preferred_over_fallback(self):
        # Ist ein Entry im Fenster vorhanden, wird der Fallback NICHT genutzt.
        prices = _series({"2024-01-02": 100.0, "2024-02-01": 120.0})
        result = compute_forward_return(
            prices, date(2024, 1, 2), 30, today=date(2024, 6, 1),
            entry_fallback=50.0,  # wuerde 1.40 ergeben, falls faelschlich genutzt
        )
        assert result == pytest.approx(0.20, abs=1e-9)

    def test_entry_zero_returns_none(self):
        prices = _series({"2024-01-02": 0.0, "2024-02-01": 112.0})
        result = compute_forward_return(
            prices, date(2024, 1, 2), 30, today=date(2024, 6, 1)
        )
        assert result is None

    def test_negative_entry_returns_none(self):
        prices = _series({"2024-01-02": -5.0, "2024-02-01": 112.0})
        result = compute_forward_return(
            prices, date(2024, 1, 2), 30, today=date(2024, 6, 1)
        )
        assert result is None

    def test_missing_exit_returns_none(self):
        # Entry vorhanden, aber kein Handelstag >= exit_target in der Serie.
        prices = _series({"2024-01-02": 100.0, "2024-01-10": 101.0})
        result = compute_forward_return(
            prices, date(2024, 1, 2), 30, today=date(2024, 6, 1)
        )
        assert result is None

    def test_weekend_scan_date_uses_next_trading_day(self):
        # 2024-01-06 ist ein Samstag; erster Handelstag danach = Mo 2024-01-08.
        # Exit-Target 2024-02-05 (Mo) liegt in der Serie.
        prices = _series({
            "2024-01-05": 99.0,    # Fr VOR dem Scan -> darf NICHT Entry sein
            "2024-01-08": 100.0,   # erster Handelstag >= scan_date -> Entry
            "2024-02-05": 110.0,   # Exit
        })
        result = compute_forward_return(
            prices, date(2024, 1, 6), 30, today=date(2024, 6, 1)
        )
        assert result == pytest.approx(0.10, abs=1e-9)
