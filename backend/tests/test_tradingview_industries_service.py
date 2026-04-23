"""Unit tests for services.tradingview_industries_service.

Covers the parser (NULL/shape handling) and `get_latest_industries`
(sort / top / bottom / latest-snapshot-only).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

import services.tradingview_industries_service as svc
from models.market_industry import MarketIndustry

pytestmark = pytest.mark.asyncio


# --- Parser ---------------------------------------------------------------

def _raw_row(slug: str, overrides: dict[int, object] | None = None) -> dict:
    """Build a raw scanner row with 13 columns matching _COLUMNS order."""
    d = [
        slug,                        # 0 name slug
        slug.replace("-", " ").title(),  # 1 description
        1.23,                        # 2 change
        2.34, 3.45, 4.56, 5.67, 6.78, 7.89, 8.9, 9.01,  # 3..10 Perf.W/1M/3M/6M/YTD/Y/5Y/10Y
        1_000_000_000.0,             # 11 market_cap
        500_000.0,                   # 12 volume
    ]
    if overrides:
        for idx, val in overrides.items():
            d[idx] = val
    return {"s": f"INDUSTRY_US:{slug.upper()}", "d": d}


def test_parse_row_basic():
    parsed = svc._parse_row(_raw_row("integrated-oil"))
    assert parsed["slug"] == "integrated-oil"
    assert parsed["name"] == "Integrated Oil"
    assert parsed["change_pct"] == Decimal("1.23")
    assert parsed["perf_ytd"] == Decimal("6.78")
    assert parsed["market_cap"] == Decimal("1000000000")


def test_parse_row_null_metric_returns_none():
    # TradingView returns None for missing long-running perfs on new industries.
    raw = _raw_row("new-industry", {10: None})  # Perf.10Y -> None
    parsed = svc._parse_row(raw)
    assert parsed is not None
    assert parsed["perf_10y"] is None
    # Other fields untouched.
    assert parsed["perf_ytd"] == Decimal("6.78")


def test_parse_row_non_numeric_goes_to_null():
    raw = _raw_row("weird", {7: "not-a-number"})
    parsed = svc._parse_row(raw)
    assert parsed["perf_ytd"] is None


def test_parse_row_missing_slug_returns_none():
    raw = _raw_row("x")
    raw["d"][0] = ""
    assert svc._parse_row(raw) is None


def test_parse_row_short_data_returns_none():
    raw = {"s": "short", "d": [1, 2, 3]}
    assert svc._parse_row(raw) is None


# --- get_latest_industries (DB-backed) -----------------------------------

def _make_row(slug: str, scraped_at: datetime, **perf) -> MarketIndustry:
    return MarketIndustry(
        slug=slug,
        name=slug.title(),
        scraped_at=scraped_at,
        change_pct=perf.get("change_pct"),
        perf_1w=perf.get("perf_1w"),
        perf_1m=perf.get("perf_1m"),
        perf_3m=perf.get("perf_3m"),
        perf_6m=perf.get("perf_6m"),
        perf_ytd=perf.get("perf_ytd"),
        perf_1y=perf.get("perf_1y"),
        perf_5y=perf.get("perf_5y"),
        perf_10y=perf.get("perf_10y"),
    )


async def test_get_latest_uses_only_most_recent_snapshot(db):
    old = datetime(2026, 4, 20, 0, 0, 0)
    new = datetime(2026, 4, 22, 0, 0, 0)
    # Old snapshot with one row we do NOT want back.
    db.add(_make_row("stale", old, perf_ytd=Decimal("99")))
    # New snapshot with two rows.
    db.add(_make_row("semis", new, perf_ytd=Decimal("50")))
    db.add(_make_row("utilities", new, perf_ytd=Decimal("10")))
    await db.commit()

    result = await svc.get_latest_industries(db, period="ytd")
    slugs = [r["slug"] for r in result["rows"]]
    assert slugs == ["semis", "utilities"]
    assert result["count"] == 2


async def test_top_sorts_desc_by_period_column(db):
    now = datetime(2026, 4, 22, 0, 0, 0)
    db.add(_make_row("low", now, perf_1m=Decimal("1.0")))
    db.add(_make_row("mid", now, perf_1m=Decimal("5.0")))
    db.add(_make_row("high", now, perf_1m=Decimal("10.0")))
    await db.commit()

    result = await svc.get_latest_industries(db, period="1m", top=2)
    assert [r["slug"] for r in result["rows"]] == ["high", "mid"]


async def test_bottom_returns_worst_by_period_column(db):
    now = datetime(2026, 4, 22, 0, 0, 0)
    db.add(_make_row("worst", now, perf_ytd=Decimal("-20.0")))
    db.add(_make_row("mid", now, perf_ytd=Decimal("5.0")))
    db.add(_make_row("best", now, perf_ytd=Decimal("25.0")))
    await db.commit()

    result = await svc.get_latest_industries(db, period="ytd", bottom=2)
    assert [r["slug"] for r in result["rows"]] == ["worst", "mid"]


async def test_order_asc_returns_worst_first_in_full_list(db):
    now = datetime(2026, 4, 22, 0, 0, 0)
    db.add(_make_row("a", now, perf_ytd=Decimal("10")))
    db.add(_make_row("b", now, perf_ytd=Decimal("-5")))
    await db.commit()

    result = await svc.get_latest_industries(db, period="ytd", order="asc")
    assert [r["slug"] for r in result["rows"]] == ["b", "a"]


async def test_null_period_values_sorted_last(db):
    now = datetime(2026, 4, 22, 0, 0, 0)
    db.add(_make_row("has_10y", now, perf_10y=Decimal("200")))
    db.add(_make_row("missing_10y", now, perf_10y=None))
    await db.commit()

    result = await svc.get_latest_industries(db, period="10y")
    # NULL always last regardless of order.
    assert [r["slug"] for r in result["rows"]] == ["has_10y", "missing_10y"]


async def test_empty_db_returns_empty_result(db):
    result = await svc.get_latest_industries(db, period="ytd")
    assert result["count"] == 0
    assert result["rows"] == []
    assert result["scraped_at"] is None


async def test_invalid_period_raises(db):
    with pytest.raises(ValueError):
        await svc.get_latest_industries(db, period="bogus")
