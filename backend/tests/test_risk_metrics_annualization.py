"""Tests fuer die Annualisierung der Risiko-Kennzahlen.

Regression (Prod-Befund 1.8.2026): Die Reihe aus ``get_portfolio_history`` hat
KALENDERtage — jeder Tag ein Punkt, Wochenenden per Forward-Fill. Annualisiert
wurde aber mit der fixen Handelstags-Konvention 252. Bei einem Ein-Jahres-Fenster
war der Exponent ``252/365 = 0.690``: ein Jahr wurde behandelt, als waeren 1.45
Jahre vergangen. Prod 1y: Benchmark 12.83 % statt ~19.1 %, Portfolio -11.86 %
statt ~-16.7 %, Volatilitaet 22.87 % statt ~27.5 %. Betroffen waren
annualized_return, benchmark_annualized_return, Volatilitaet, Downside-Vola,
Sharpe, Sortino, Calmar, Information Ratio und Tracking Error gleichzeitig.
"""
from __future__ import annotations

import math

import pytest

from services.risk_metrics_service import (
    DAYS_PER_YEAR,
    _annualized_return,
    _periods_per_year,
)


def test_calendar_daily_series_annualises_to_itself_over_one_year():
    """Ein Jahr Kalendertage → Annualisierung ist die Jahresrendite selbst."""
    ppy = _periods_per_year(n_returns=364, span_days=365)
    levels = [100.0, 119.14]  # +19.14 % ueber das Fenster
    ann = _annualized_return(levels, 364, ppy)
    assert ann == pytest.approx(0.1914, abs=0.002), (
        f"1-Jahres-Rendite darf sich durch Annualisierung nicht veraendern, war {ann:.4f}"
    )


def test_old_trading_day_constant_would_have_understated_it():
    """Gegenprobe: mit dem alten fixen 252 kaeme deutlich zu wenig heraus.

    Das ist der Prod-Fall — +19.1 % wurden als 12.8 % gemeldet.
    """
    levels = [100.0, 119.14]
    alt = _annualized_return(levels, 364, 252)
    assert alt == pytest.approx(0.128, abs=0.005)


def test_three_year_window_annualises_geometrically():
    """Drei Jahre, Verdopplung → 26 % p.a. (2 ** (1/3) - 1)."""
    ppy = _periods_per_year(n_returns=1094, span_days=1095)
    ann = _annualized_return([100.0, 200.0], 1094, ppy)
    assert ann == pytest.approx(2 ** (1 / 3) - 1, abs=0.005)


def test_downsampled_series_self_corrects():
    """Ausgeduennte Reihe (5-Tage-Sampling ueber 5 Jahre) bekommt automatisch
    den richtigen Faktor — genau dafuer wird die Frequenz abgeleitet statt
    gesetzt. Mit einer Konstante waere ein 5-Jahres-Fenster als ~1.4 Jahre
    annualisiert worden."""
    ppy = _periods_per_year(n_returns=365, span_days=1826)
    assert ppy == pytest.approx(73.0, abs=1.0)
    ann = _annualized_return([100.0, 200.0], 365, ppy)
    assert ann == pytest.approx(2 ** (1 / 5) - 1, abs=0.005)


def test_weekend_zeros_cancel_in_volatility_scaling():
    """Kalendertag-Reihe mit Wochenend-Nullen, skaliert mit sqrt(ppy), ergibt
    dieselbe Jahresvolatilitaet wie die reine Handelstags-Reihe.

    Genau dieser Effekt kuerzt sich heraus: die Nullen daempfen die Streuung um
    sqrt(252/365), die groessere Skalierung hebt das wieder auf.
    """
    import statistics

    trading = [0.01, -0.012, 0.008, -0.006, 0.011] * 50   # 250 Handelstage
    vol_trading = statistics.stdev(trading) * math.sqrt(252)

    calendar = []
    for i, r in enumerate(trading):
        calendar.append(r)
        if i % 5 == 4:  # nach je 5 Handelstagen zwei Null-Tage
            calendar.extend([0.0, 0.0])
    ppy = _periods_per_year(len(calendar), span_days=round(len(calendar) * 365.25 / 365.25))
    vol_calendar = statistics.stdev(calendar) * math.sqrt(ppy)

    assert vol_calendar == pytest.approx(vol_trading, rel=0.05)


def test_degenerate_inputs_fall_back_to_trading_days():
    """Leere/kaputte Reihe darf nicht durch null teilen."""
    assert _periods_per_year(0, 365) == 252.0
    assert _periods_per_year(364, 0) == 252.0
    assert DAYS_PER_YEAR == pytest.approx(365.25)
