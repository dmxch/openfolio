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

    # Frontend-Vertrag: hypothetical_position_pct kommt aus analysis_config,
    # damit ConcentrationBanner.jsx keinen Magic-Number-Wert hartkodieren muss.
    from services.analysis_config import CORE_OVERLAP_HYPOTHETICAL_POSITION_PCT
    assert result["single_name"]["hypothetical_position_pct"] == pytest.approx(
        float(CORE_OVERLAP_HYPOTHETICAL_POSITION_PCT)
    )


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


async def test_country_lookthrough_oef_geo_default():
    """OEF (S&P 100) hat keine verwertbaren Holdings-Laender -> der ETF-Wert wird
    via Geo-Default komplett 'United States' zugeordnet statt aus der Laender-Sicht
    zu fallen. Reale Holdings (EIMI) verteilen normal."""
    user_id = uuid.uuid4()
    # EtfHolding-Rows: nur EIMI hat Country-Daten, OEF gar keine.
    rows = [
        ("EIMI.L", "Taiwan", 60.0, None),
        ("EIMI.L", "China", 40.0, None),
    ]

    class _Result:
        def all(self_inner):
            return rows

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())

    user_etfs = {
        "EIMI.L": {"name": "EM IMI", "market_value_chf": 1000.0},
        "OEF": {"name": "iShares S&P 100", "market_value_chf": 3000.0},
    }
    with patch(
        "services.concentration_service._get_user_etf_positions_with_values",
        AsyncMock(return_value=user_etfs),
    ):
        result = await cs.get_country_lookthrough(db, user_id)

    assert result["has_data"] is True
    countries = {c["country"]: c["value_chf"] for c in result["countries"]}
    assert countries["United States"] == pytest.approx(3000.0)   # OEF komplett
    assert countries["Taiwan"] == pytest.approx(600.0)           # EIMI 60%
    assert countries["China"] == pytest.approx(400.0)            # EIMI 40%
    assert result["total_lookthrough_chf"] == pytest.approx(4000.0)

    oef_meta = next(e for e in result["etfs"] if e["ticker"] == "OEF")
    assert oef_meta["source"] == "default"
    assert oef_meta["coverage_pct"] == 100.0
    assert "OEF" not in result["etfs_without_data"]


async def test_country_lookthrough_no_default_stays_excluded():
    """ETF ohne Country-Daten UND ohne Geo-Default (z.B. Bond-ETF IB01) bleibt
    ehrlich in etfs_without_data — kein erfundenes Land."""
    user_id = uuid.uuid4()

    class _Result:
        def all(self_inner):
            return []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())

    user_etfs = {"IB01.L": {"name": "Treasury 0-1y", "market_value_chf": 2000.0}}
    with patch(
        "services.concentration_service._get_user_etf_positions_with_values",
        AsyncMock(return_value=user_etfs),
    ):
        result = await cs.get_country_lookthrough(db, user_id)

    assert result["has_data"] is False
    assert "IB01.L" in result["etfs_without_data"]


async def test_country_lookthrough_skips_non_finite_weight():
    """Defensiv (Belt-and-suspenders zum Source-Guard): eine historisch persistierte
    NaN-Gewicht-Row darf den Endpoint NICHT auf 500 kippen (Starlette allow_nan=False)
    — sie wird uebersprungen, valide Rows verteilen normal, kein NaN im Output."""
    import math

    user_id = uuid.uuid4()
    rows = [
        ("EIMI.L", "Taiwan", 60.0, None),
        ("EIMI.L", "China", float("nan"), None),   # korrupte Row -> muss geskippt werden
    ]

    class _Result:
        def all(self_inner):
            return rows

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())

    user_etfs = {"EIMI.L": {"name": "EM IMI", "market_value_chf": 1000.0}}
    with patch(
        "services.concentration_service._get_user_etf_positions_with_values",
        AsyncMock(return_value=user_etfs),
    ):
        result = await cs.get_country_lookthrough(db, user_id)

    countries = {c["country"]: c["value_chf"] for c in result["countries"]}
    assert "China" not in countries                          # NaN-Row uebersprungen
    assert countries["Taiwan"] == pytest.approx(600.0)       # 1000 * 60%
    # Kein NaN/Inf im serialisierten Output (sonst 500 beim JSON-Render).
    assert math.isfinite(result["total_lookthrough_chf"])
    assert all(math.isfinite(c["value_chf"]) and math.isfinite(c["pct"])
               for c in result["countries"])


async def test_overlap_max_weight_skips_non_finite():
    """get_overlap_max_weight_for_tickers: eine NaN-Gewicht-Row passiert in Postgres
    sogar den SQL-`>=`-Filter (NaN gilt als groesstes Element) UND `weight > cur` ->
    wuerde jeden echten Max verdraengen. Python-seitig muss sie ausgefiltert werden."""
    import math

    user_id = uuid.uuid4()
    rows = [
        ("AAPL", 5.0),
        ("AAPL", float("nan")),   # korrupt -> darf die 5.0 NICHT verdraengen
        ("MSFT", float("nan")),   # nur NaN -> gar kein Eintrag
    ]

    class _Result:
        def all(self_inner):
            return rows

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())

    with patch(
        "services.concentration_service._get_user_etf_positions_with_values",
        AsyncMock(return_value={"SWDA.L": {"name": "World", "market_value_chf": 1000.0}}),
    ):
        result = await cs.get_overlap_max_weight_for_tickers(db, ["AAPL", "MSFT"], user_id)

    assert result.get("AAPL") == pytest.approx(5.0)   # NaN hat die 5.0 nicht verdraengt
    assert "MSFT" not in result                        # nur NaN -> kein Eintrag
    assert all(math.isfinite(v) for v in result.values())
