"""Tests fuer risk_metrics_service — additive Risiko-Kennzahlen aus der Index-Reihe.

Reine Lese-Kennzahlen; beruehren keine geschuetzte Performance-Berechnung. Die
get_portfolio_history-Quelle wird gemockt, damit die Kennzahlen deterministisch
gegen eine bekannte Reihe geprueft werden (kein Preis-/yfinance-Bedarf).
"""
from __future__ import annotations

import math
from datetime import date

import pytest

import services.risk_metrics_service as rms
from services.risk_metrics_service import (
    _annualized_return,
    _daily_returns,
    _downside_deviation,
    _max_drawdown,
    compute_risk_metrics,
)

# Kein globaler asyncio-Mark: pytest.ini laeuft mit asyncio_mode=auto, die
# async-Tests werden automatisch erkannt; die reinen Helfer-Tests bleiben sync.


def test_daily_returns():
    assert _daily_returns([100, 110, 99]) == pytest.approx([0.1, -0.1])
    # Guard: prev<=0 -> 0.0
    assert _daily_returns([0, 10]) == [0.0]


def test_max_drawdown():
    # Peak 110, Trough 90 -> (110-90)/110
    assert _max_drawdown([100, 110, 90, 120]) == pytest.approx(20 / 110)
    assert _max_drawdown([100, 101, 102]) == 0.0  # monoton steigend


def test_annualized_return_geometric():
    # +21% ueber 252 Returns -> ann == 21%
    levels = [100.0] + [None] * 0
    # baue 253 Levels: linear interpolation nicht noetig — nur erstes/letztes zaehlt
    levels = [100.0, 121.0]
    # n_returns klein -> sehr hohe Annualisierung; pruefe Formel direkt
    assert _annualized_return([100.0, 121.0], 252) == pytest.approx(0.21, abs=1e-9)
    assert _annualized_return([100.0, 200.0], 0) == 0.0


def test_downside_deviation_only_negative():
    # nur negative Returns gehen ein; positive zaehlen als 0
    dd = _downside_deviation([0.0, 0.1, -0.1], mar_daily=0.0)
    expected = math.sqrt((0.1 ** 2) / 3) * math.sqrt(252)
    assert dd == pytest.approx(expected)


async def _patch_history(monkeypatch, levels, bench=None):
    points = []
    for i, lv in enumerate(levels):
        p = {"date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", "portfolio_indexed": float(lv)}
        if bench is not None:
            p["benchmark_indexed"] = float(bench[i])
        points.append(p)

    async def fake_history(*args, **kwargs):
        return {"data": points, "summary": {}}

    monkeypatch.setattr(rms, "get_portfolio_history", fake_history)


async def test_insufficient_history(monkeypatch):
    await _patch_history(monkeypatch, [100, 101, 102])  # < MIN_OBS+1
    res = await compute_risk_metrics(db=None, start_date=date(2025, 1, 1), end_date=date(2025, 2, 1))
    assert res["error"] == "insufficient_history"


async def test_full_metrics_shape_and_drawdown(monkeypatch):
    # 30 steigende Tage mit einem Einbruch -> bekannte Kennzahlen-Struktur
    levels = [100.0]
    for i in range(1, 25):
        levels.append(levels[-1] * 1.01)
    # kuenstlicher Drawdown
    peak = levels[-1]
    levels.append(peak * 0.9)
    for _ in range(5):
        levels.append(levels[-1] * 1.01)
    bench = [100.0 * (1.005 ** i) for i in range(len(levels))]

    await _patch_history(monkeypatch, levels, bench=bench)
    res = await compute_risk_metrics(
        db=None, start_date=date(2025, 1, 1), end_date=date(2025, 3, 1), benchmark="^GSPC"
    )
    assert "error" not in res
    assert res["n_obs"] == len(levels) - 1
    assert res["volatility_pct"] > 0
    assert res["max_drawdown_pct"] == pytest.approx((peak - peak * 0.9) / peak * 100, abs=0.01)
    # Sharpe/Sortino/Calmar sind Zahlen (rf=0 default)
    assert isinstance(res["sharpe_ratio"], float)
    assert isinstance(res["sortino_ratio"], float)
    assert isinstance(res["calmar_ratio"], float)
    assert res["risk_free_rate_pct"] == 0.0
    # Information Ratio vorhanden, weil Benchmark-Serie geliefert
    assert res["information_ratio"] is not None
    assert res["benchmark"] == "^GSPC"
    assert set(res["rolling_returns"].keys()) == {"1m", "3m", "6m", "1y"}


async def test_information_ratio_none_without_benchmark(monkeypatch):
    levels = [100.0 * (1.005 ** i) for i in range(40)]
    await _patch_history(monkeypatch, levels, bench=None)
    res = await compute_risk_metrics(db=None, start_date=date(2025, 1, 1), end_date=date(2025, 3, 1))
    assert res["information_ratio"] is None
    assert res["benchmark_annualized_return_pct"] is None


async def test_risk_free_rate_lowers_sharpe(monkeypatch):
    levels = [100.0 * (1.004 ** i) for i in range(40)]
    await _patch_history(monkeypatch, levels)
    res0 = await compute_risk_metrics(db=None, start_date=date(2025, 1, 1), end_date=date(2025, 3, 1))
    monkeypatch.setattr(rms.settings, "risk_free_rate_pct", 5.0)
    res5 = await compute_risk_metrics(db=None, start_date=date(2025, 1, 1), end_date=date(2025, 3, 1))
    assert res5["sharpe_ratio"] < res0["sharpe_ratio"]
    assert res5["risk_free_rate_pct"] == 5.0


async def test_degenerate_constant_series_flagged(monkeypatch):
    # Konstante Reihe (z.B. ein nicht-markiertes Asset wie eingefrorenes Gold):
    # ausreichend Beobachtungen, aber Vola 0 -> degenerate=True, Ratios None,
    # KEIN insufficient_history (die Reihe ist nicht zu kurz, nur konstant).
    await _patch_history(monkeypatch, [100.0] * 40)
    res = await compute_risk_metrics(db=None, start_date=date(2025, 1, 1), end_date=date(2025, 3, 1))
    assert "error" not in res
    assert res["degenerate"] is True
    assert res["volatility_pct"] == 0.0
    assert res["sharpe_ratio"] is None
    assert res["sortino_ratio"] is None
    assert res["calmar_ratio"] is None


async def test_varying_series_not_degenerate(monkeypatch):
    levels = [100.0 * (1.004 ** i) for i in range(40)]
    await _patch_history(monkeypatch, levels)
    res = await compute_risk_metrics(db=None, start_date=date(2025, 1, 1), end_date=date(2025, 3, 1))
    assert res["degenerate"] is False


async def test_benchmark_resolved_from_bucket(db, monkeypatch):
    """risk-metrics nutzt ohne explizites benchmark den pro-Bucket konfigurierten
    bucket.benchmark (Satellite->MTUM), nicht stur ^GSPC. Explizit gesetztes
    benchmark hat Vorrang; ohne bucket_id Fallback ^GSPC."""
    import uuid as _uuid

    from models.user import User
    from services.bucket_service import create_bucket

    user = User(email=f"rm{_uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    bucket = await create_bucket(db, user.id, name="Satellite", benchmark="MTUM")
    await db.commit()

    captured: dict = {}

    async def fake_history(db_, start, end, benchmark=None, **kwargs):
        captured["benchmark"] = benchmark
        points = [
            {"date": f"2025-01-{(i % 28) + 1:02d}", "portfolio_indexed": 100.0 * (1.004 ** i)}
            for i in range(40)
        ]
        return {"data": points, "summary": {}}

    monkeypatch.setattr(rms, "get_portfolio_history", fake_history)

    # Ohne explizites benchmark -> bucket.benchmark (MTUM)
    res = await compute_risk_metrics(
        db, date(2025, 1, 1), date(2025, 3, 1), user_id=user.id, bucket_id=bucket.id
    )
    assert captured["benchmark"] == "MTUM"
    assert res["benchmark"] == "MTUM"
    assert res["benchmark_name"] == "MSCI USA Momentum"

    # Explizit gesetztes benchmark hat Vorrang
    res2 = await compute_risk_metrics(
        db, date(2025, 1, 1), date(2025, 3, 1),
        benchmark="^GSPC", user_id=user.id, bucket_id=bucket.id,
    )
    assert res2["benchmark"] == "^GSPC"

    # Ohne bucket_id -> Fallback ^GSPC
    res3 = await compute_risk_metrics(db, date(2025, 1, 1), date(2025, 3, 1), user_id=user.id)
    assert res3["benchmark"] == "^GSPC"
