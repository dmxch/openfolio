"""Unit tests for services.concentration_service.

Fokus: verdrahteter Portfolio-HHI im Return-Dict von
``get_concentration_for_ticker``. Die HHI-Logik selbst lebt in
``correlation_service`` und hat dort eigene Unit-Tests
(``test_correlation_service.py``); hier wird nur die Integration geprueft —
dass die im Score-Endpoint zurueckgegebenen Werte mit der Correlation-
Single-Source-of-Truth uebereinstimmen.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

import services.concentration_service as cs

pytestmark = pytest.mark.asyncio


def _portfolio_summary(positions: list[dict], total_chf: float) -> dict:
    return {
        "positions": positions,
        "total_market_value_chf": total_chf,
    }


def _pos(
    ticker: str,
    type_: str = "stock",
    weight_pct: float = 10.0,
    market_value_chf: float = 1000.0,
    name: str | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "yfinance_ticker": ticker,
        "name": name or ticker,
        "type": type_,
        "weight_pct": weight_pct,
        "market_value_chf": market_value_chf,
    }


async def test_get_concentration_for_ticker_includes_portfolio_hhi():
    """40/30/20/10 Portfolio liefert HHI=0.30, effective_n~3.33."""
    positions = [
        _pos("A", "stock", weight_pct=40.0, market_value_chf=4000.0),
        _pos("B", "stock", weight_pct=30.0, market_value_chf=3000.0),
        _pos("C", "etf", weight_pct=20.0, market_value_chf=2000.0),
        _pos("D", "etf", weight_pct=10.0, market_value_chf=1000.0),
    ]
    summary = _portfolio_summary(positions, total_chf=10_000.0)

    user_id = uuid.uuid4()

    sector_stub = {
        "status": "no_sector", "sector": None, "current_pct": None,
        "post_buy_pct": None, "soft_warn": False, "hard_warn": False,
        "coverage_warning": False, "affected_etfs": [],
    }

    # db.execute() wird im ETF-Overlap-Pfad aufgerufen, aber nur wenn user_etfs
    # nicht leer sind. Mit zwei ETFs muessen wir einen leeren Result-Stub
    # zurueckgeben — keine EtfHolding-Eintraege im Test.
    class _EmptyResult:
        def all(self_inner):
            return []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_EmptyResult())

    with patch(
        "services.portfolio_service.get_portfolio_summary",
        AsyncMock(return_value=summary),
    ), patch(
        "services.concentration_service.get_sector_aggregation",
        AsyncMock(return_value=sector_stub),
    ):
        result = await cs.get_concentration_for_ticker(db, "A", user_id)

    assert "portfolio" in result
    portfolio = result["portfolio"]
    assert portfolio["hhi"] == pytest.approx(0.30, abs=1e-4)
    assert portfolio["effective_n"] == pytest.approx(3.33, abs=0.01)
    assert portfolio["nominal_count"] == 4
    assert portfolio["max_weight_ticker"] == "A"
    assert portfolio["max_weight_pct"] == 40.0
    assert portfolio["classification"] == "high"


async def test_get_concentration_for_ticker_empty_portfolio_unknown():
    """Leeres Portfolio → HHI=0.0, classification 'unknown'."""
    summary = _portfolio_summary([], total_chf=0.0)
    user_id = uuid.uuid4()
    sector_stub = {"status": "no_sector"}

    class _EmptyResult:
        def all(self_inner):
            return []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_EmptyResult())

    with patch(
        "services.portfolio_service.get_portfolio_summary",
        AsyncMock(return_value=summary),
    ), patch(
        "services.concentration_service.get_sector_aggregation",
        AsyncMock(return_value=sector_stub),
    ):
        result = await cs.get_concentration_for_ticker(db, "A", user_id)

    portfolio = result["portfolio"]
    assert portfolio["hhi"] == 0.0
    assert portfolio["effective_n"] == 0.0
    assert portfolio["classification"] == "unknown"
    assert portfolio["nominal_count"] == 0
