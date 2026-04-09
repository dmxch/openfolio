"""Unit tests for services.correlation_service.

Mocks `_fetch_close_matrix` so no real yfinance calls happen.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import numpy as np  # transitive via pandas in tests only — not imported in the service
import pandas as pd
import pytest

import services.correlation_service as cs

pytestmark = pytest.mark.asyncio


# --- Helpers ---------------------------------------------------------------

def _make_close_df(series_map: dict[str, list[float]]) -> pd.DataFrame:
    """Build a Close DataFrame with a business-day DatetimeIndex."""
    n = len(next(iter(series_map.values())))
    idx = pd.bdate_range(end="2026-04-07", periods=n)
    return pd.DataFrame(series_map, index=idx)


def _make_summary(positions: list[dict]) -> dict:
    return {"positions": positions}


def _pos(
    id_: str,
    ticker: str,
    type_: str = "stock",
    weight_pct: float = 10.0,
    sector: str | None = None,
) -> dict:
    return {
        "id": id_,
        "ticker": ticker,
        "name": ticker,
        "type": type_,
        "sector": sector,
        "weight_pct": weight_pct,
    }


class _FakePos:
    """Stand-in for a SQLAlchemy Position row."""

    def __init__(
        self,
        id_: str,
        ticker: str,
        type_value: str,
        yfinance_ticker: str | None = None,
        gold_org: bool = False,
        sector: str | None = None,
        name: str | None = None,
    ):
        self.id = uuid.UUID(id_)
        self.ticker = ticker
        self.name = name or ticker
        # Mimic the AssetType enum: object with .value attribute.
        self.type = type("T", (), {"value": type_value})()
        self.yfinance_ticker = yfinance_ticker
        self.gold_org = gold_org
        self.sector = sector


class _FakeDB:
    """Minimal async DB stub — returns a fixed list of Position rows."""

    def __init__(self, pos_rows: list[_FakePos]):
        self._rows = pos_rows

    async def execute(self, _query):
        rows = self._rows

        class _Scalars:
            def all(self_inner):
                return rows

        class _Result:
            def scalars(self_inner):
                return _Scalars()

        return _Result()


# --- Tests: helpers ---------------------------------------------------------


async def test_hhi_computation():
    # 40/30/20/10 — HHI = 0.16 + 0.09 + 0.04 + 0.01 = 0.30, effective_n ~= 3.33
    result = cs._compute_concentration(
        [("A", 40.0), ("B", 30.0), ("C", 20.0), ("D", 10.0)]
    )
    assert result["hhi"] == pytest.approx(0.30, abs=1e-4)
    assert result["effective_n"] == pytest.approx(3.33, abs=0.01)
    assert result["max_weight_ticker"] == "A"
    assert result["max_weight_pct"] == 40.0
    assert result["classification"] == "high"


async def test_insufficient_history_goes_to_warnings():
    # 5 closes -> 4 returns -> below min_days=20
    close = _make_close_df({"AAA": [100, 101, 102, 103, 104]})
    returns, warnings = cs._compute_returns(close, min_days=20)
    assert returns.empty
    assert any("insufficient_history:AAA" in w for w in warnings)


async def test_single_ticker_returns_work():
    # 30 close rows -> 29 returns -> above min_days=20
    vals = [100 + i for i in range(30)]
    close = _make_close_df({"AAA": vals})
    returns, warnings = cs._compute_returns(close, min_days=20)
    assert not returns.empty
    assert warnings == []
    # Correlation of a single series with itself = 1.0
    corr = returns.corr()
    assert corr.iat[0, 0] == pytest.approx(1.0)


async def test_real_estate_and_pe_always_excluded():
    positions = [
        _pos("1", "AAA", "stock", 20),
        _pos("2", "BBB", "real_estate", 40),
        _pos("3", "CCC", "private_equity", 30),
        _pos("4", "DDD", "etf", 10),
    ]
    for flags in [
        {"include_cash": True, "include_pension": True, "include_commodity": True, "include_crypto": True},
        {"include_cash": False, "include_pension": False, "include_commodity": False, "include_crypto": False},
    ]:
        out = cs._filter_universe(positions, **flags)
        out_types = {p["type"] for p in out}
        assert "real_estate" not in out_types
        assert "private_equity" not in out_types


async def test_universe_filter_flags():
    positions = [
        _pos("1", "AAA", "stock"),
        _pos("2", "CASHCHF", "cash"),
        _pos("3", "VIAC", "pension"),
        _pos("4", "GOLD", "commodity"),
        _pos("5", "BTC", "crypto"),
    ]
    default = cs._filter_universe(
        positions,
        include_cash=False,
        include_pension=False,
        include_commodity=True,
        include_crypto=True,
    )
    assert {p["ticker"] for p in default} == {"AAA", "GOLD", "BTC"}

    no_crypto = cs._filter_universe(
        positions,
        include_cash=False,
        include_pension=False,
        include_commodity=True,
        include_crypto=False,
    )
    assert {p["ticker"] for p in no_crypto} == {"AAA", "GOLD"}

    all_on = cs._filter_universe(
        positions,
        include_cash=True,
        include_pension=True,
        include_commodity=True,
        include_crypto=True,
    )
    assert {p["ticker"] for p in all_on} == {"AAA", "CASHCHF", "VIAC", "GOLD", "BTC"}


# --- Tests: compute_correlation_matrix end-to-end (mocked) -----------------


async def test_correlation_known_matrix():
    """Two perfectly correlated series + one uncorrelated -> matrix matches."""
    n = 40
    base = [100 + i for i in range(n)]
    # Perfectly correlated (scaled + shifted)
    mirror = [200 + 2 * i for i in range(n)]
    # Uncorrelated deterministic sequence (cosine).
    other = [100 + 5 * np.cos(i / 2) for i in range(n)]

    close = _make_close_df({"AAA": base, "BBB": mirror, "CCC": other})

    pos_rows = [
        _FakePos("00000000-0000-0000-0000-000000000001", "AAA", "stock", yfinance_ticker="AAA"),
        _FakePos("00000000-0000-0000-0000-000000000002", "BBB", "stock", yfinance_ticker="BBB"),
        _FakePos("00000000-0000-0000-0000-000000000003", "CCC", "stock", yfinance_ticker="CCC"),
    ]
    summary = _make_summary([
        _pos("00000000-0000-0000-0000-000000000001", "AAA", "stock", 40),
        _pos("00000000-0000-0000-0000-000000000002", "BBB", "stock", 30),
        _pos("00000000-0000-0000-0000-000000000003", "CCC", "stock", 30),
    ])

    with patch.object(cs, "get_portfolio_summary", return_value=summary), \
         patch.object(cs, "_fetch_close_matrix", return_value=close):
        db = _FakeDB(pos_rows)
        result = await cs.compute_correlation_matrix(
            db, uuid.uuid4(), period="90d"
        )

    assert len(result["tickers"]) == 3
    matrix_tickers = [t["yf_ticker"] for t in result["tickers"]]
    # Diagonal = 1.0
    for i in range(len(matrix_tickers)):
        assert result["matrix"][i][i] == pytest.approx(1.0, abs=1e-4)
    # AAA <-> BBB are perfectly correlated
    i_aaa = matrix_tickers.index("AAA")
    i_bbb = matrix_tickers.index("BBB")
    assert result["matrix"][i_aaa][i_bbb] == pytest.approx(1.0, abs=1e-3)
    assert result["observations"] > 0


async def test_single_position_returns_identity():
    n = 30
    close = _make_close_df({"ONLY": [100 + i for i in range(n)]})
    pos_rows = [
        _FakePos("00000000-0000-0000-0000-000000000001", "ONLY", "stock", yfinance_ticker="ONLY"),
    ]
    summary = _make_summary([
        _pos("00000000-0000-0000-0000-000000000001", "ONLY", "stock", 100.0),
    ])
    with patch.object(cs, "get_portfolio_summary", return_value=summary), \
         patch.object(cs, "_fetch_close_matrix", return_value=close):
        db = _FakeDB(pos_rows)
        result = await cs.compute_correlation_matrix(
            db, uuid.uuid4(), period="90d"
        )
    assert result["matrix"] == [[1.0]]
    assert len(result["tickers"]) == 1
    assert result["concentration"]["hhi"] == pytest.approx(1.0, abs=1e-4)


async def test_high_correlations_sorted_desc():
    """Construct 3 series: A~B=0.95, A~C=0.72, B~C=0.50 (approx via controlled mixing)."""
    rng = np.random.default_rng(42)
    n = 80
    a = rng.normal(size=n)
    # b mostly follows a
    b = 0.95 * a + 0.31 * rng.normal(size=n)
    # c partly follows a
    c = 0.72 * a + 0.69 * rng.normal(size=n)

    # Convert returns-like noise into synthetic prices (cumulative).
    def to_prices(returns):
        prices = [100.0]
        for r in returns:
            prices.append(prices[-1] * (1 + r / 100))
        return prices[1:]

    close = _make_close_df({
        "A": to_prices(a),
        "B": to_prices(b),
        "C": to_prices(c),
    })

    pos_rows = [
        _FakePos("00000000-0000-0000-0000-00000000000a", "A", "stock", yfinance_ticker="A"),
        _FakePos("00000000-0000-0000-0000-00000000000b", "B", "stock", yfinance_ticker="B"),
        _FakePos("00000000-0000-0000-0000-00000000000c", "C", "stock", yfinance_ticker="C"),
    ]
    summary = _make_summary([
        _pos("00000000-0000-0000-0000-00000000000a", "A", "stock", 30),
        _pos("00000000-0000-0000-0000-00000000000b", "B", "stock", 30),
        _pos("00000000-0000-0000-0000-00000000000c", "C", "stock", 40),
    ])

    with patch.object(cs, "get_portfolio_summary", return_value=summary), \
         patch.object(cs, "_fetch_close_matrix", return_value=close):
        db = _FakeDB(pos_rows)
        result = await cs.compute_correlation_matrix(
            db, uuid.uuid4(), period="90d"
        )

    pairs = result["high_correlations"]
    # Sorted descending by |r|
    if len(pairs) >= 2:
        for i in range(len(pairs) - 1):
            assert abs(pairs[i]["correlation"]) >= abs(pairs[i + 1]["correlation"])
    # The A-B pair with ~0.95 should be present.
    found = [p for p in pairs if {p["ticker_a"], p["ticker_b"]} == {"A", "B"}]
    assert found, f"Expected A/B high-correlation pair, got: {pairs}"
    assert abs(found[0]["correlation"]) >= 0.7
