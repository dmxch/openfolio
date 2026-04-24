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


async def test_min_mcap_filter_drops_small_caps(db):
    now = datetime(2026, 4, 22, 0, 0, 0)
    db.add(MarketIndustry(slug="big", name="Big", scraped_at=now, market_cap=Decimal("50000000000")))
    db.add(MarketIndustry(slug="small", name="Small", scraped_at=now, market_cap=Decimal("5000000")))
    db.add(MarketIndustry(slug="nullcap", name="Null", scraped_at=now, market_cap=None))
    await db.commit()

    result = await svc.get_latest_industries(db, period="ytd", min_mcap=1_000_000_000)
    slugs = [r["slug"] for r in result["rows"]]
    assert slugs == ["big"]


# --- _compute_rvol_20d ----------------------------------------------------

async def _seed_history(db, slug: str, values: list[Decimal | None], start_days_ago: int = 1):
    """Insert historical snapshots for *slug* on past weekdays.

    values[0] goes to the most-recent historical day (yesterday),
    values[-1] to the oldest. None entries are skipped (not persisted).
    """
    from dateutils import utcnow as _now
    today = _now().replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=None).date()
    from datetime import date as _date, timedelta as _td
    for i, v in enumerate(values):
        if v is None:
            # Insert a NULL value_traded row — should be ignored by helper
            ts = datetime.combine(today - _td(days=start_days_ago + i), datetime.min.time())
            db.add(MarketIndustry(slug=slug, name=slug, scraped_at=ts, value_traded=None))
            continue
        ts = datetime.combine(today - _td(days=start_days_ago + i), datetime.min.time())
        db.add(MarketIndustry(slug=slug, name=slug, scraped_at=ts, value_traded=v))
    await db.commit()


async def test_rvol_returns_none_with_insufficient_history(db):
    await _seed_history(db, "semis", [Decimal("100")] * 10)
    rvol = await svc._compute_rvol_20d(db, "semis", Decimal("150"))
    assert rvol is None


async def test_rvol_ignores_null_value_traded(db):
    # 10 real values + 15 NULL entries = 10 valid < 20 → None
    mixed = [Decimal("100")] * 10 + [None] * 15
    await _seed_history(db, "pharma", mixed)
    rvol = await svc._compute_rvol_20d(db, "pharma", Decimal("150"))
    assert rvol is None


async def test_rvol_computes_ratio_with_enough_history(db):
    await _seed_history(db, "oil", [Decimal("100")] * 20)
    rvol = await svc._compute_rvol_20d(db, "oil", Decimal("180"))
    # 180 / avg(100) = 1.80
    assert rvol == Decimal("1.80")


async def test_rvol_handles_zero_current(db):
    await _seed_history(db, "dead", [Decimal("100")] * 20)
    rvol = await svc._compute_rvol_20d(db, "dead", Decimal("0"))
    assert rvol is None


async def test_rvol_handles_none_current(db):
    await _seed_history(db, "null-today", [Decimal("100")] * 20)
    rvol = await svc._compute_rvol_20d(db, "null-today", None)
    assert rvol is None


async def test_rvol_handles_zero_historical_average(db):
    await _seed_history(db, "all-zero", [Decimal("0")] * 20)
    rvol = await svc._compute_rvol_20d(db, "all-zero", Decimal("100"))
    assert rvol is None


# --- _compute_concentration (HHI + Top-1) --------------------------------

def test_concentration_empty_members():
    assert svc._compute_concentration([]) == (None, None, None)


def test_concentration_single_dominant_member():
    top, weight, eff_n = svc._compute_concentration([("SPHR", Decimal("4.7"))])
    assert top == "SPHR"
    assert weight == Decimal("1.0000")
    assert eff_n == Decimal("1.00")


def test_concentration_two_members_65_35():
    # Media Conglomerates-Shape: SPHR 65%, VVVNF 35% → Eff-N ≈ 1.81
    top, weight, eff_n = svc._compute_concentration([
        ("SPHR", Decimal("4.7")),
        ("VVVNF", Decimal("2.5")),
    ])
    assert top == "SPHR"
    assert weight == Decimal("0.6528")
    # HHI = 0.6528^2 + 0.3472^2 ≈ 0.5468 → Eff-N ≈ 1.83
    assert Decimal("1.7") < eff_n < Decimal("1.9")


def test_concentration_perfectly_balanced():
    # 5 equal members → Eff-N = 5, Top-1 = 20%
    members = [(f"T{i}", Decimal("100")) for i in range(5)]
    top, weight, eff_n = svc._compute_concentration(members)
    assert weight == Decimal("0.2000")
    assert eff_n == Decimal("5.00")


def test_concentration_zero_total_returns_none():
    top, weight, eff_n = svc._compute_concentration([("X", Decimal(0)), ("Y", Decimal(0))])
    assert (top, weight, eff_n) == (None, None, None)


def test_concentration_computer_peripherals_shape():
    # Real shape: ANET 225, SNDK 147, WDC 137, STX 129, KXHCF 124, rest ~65
    # Expected Top-1 ≈ 26%, Eff-N ~6-7.
    members = [
        ("ANET", Decimal("225")),
        ("SNDK", Decimal("147")),
        ("WDC", Decimal("137")),
        ("STX", Decimal("129")),
        ("KXHCF", Decimal("124")),
        ("CAJFF", Decimal("24")),
        ("P", Decimal("24")),
        ("NTAP", Decimal("22")),
        ("LOGI", Decimal("14")),
    ]
    top, weight, eff_n = svc._compute_concentration(members)
    assert top == "ANET"
    assert Decimal("0.25") < weight < Decimal("0.30")
    assert Decimal("5") < eff_n < Decimal("7")


# --- _row_to_dict ---------------------------------------------------------

def test_row_to_dict_computes_turnover_ratio():
    row = MarketIndustry(
        slug="s", name="S", scraped_at=datetime(2026, 4, 22),
        market_cap=Decimal("1000000000000"),  # 1T
        value_traded=Decimal("5000000000"),   # 5B
        rvol_20d=Decimal("1.50"),
    )
    d = svc._row_to_dict(row)
    assert d["value_traded"] == 5_000_000_000.0
    assert d["turnover_ratio"] == 0.005  # 5B / 1T
    assert d["rvol"] == 1.5


def test_row_to_dict_turnover_ratio_null_when_inputs_missing():
    row = MarketIndustry(
        slug="s", name="S", scraped_at=datetime(2026, 4, 22),
        market_cap=None, value_traded=None,
    )
    d = svc._row_to_dict(row)
    assert d["turnover_ratio"] is None
    assert d["value_traded"] is None
    assert d["rvol"] is None
    assert d["top1_ticker"] is None
    assert d["top1_weight"] is None
    assert d["effective_n"] is None


def test_row_to_dict_serializes_concentration_fields():
    row = MarketIndustry(
        slug="s", name="S", scraped_at=datetime(2026, 4, 22),
        top1_ticker="SPHR",
        top1_weight=Decimal("0.6528"),
        effective_n=Decimal("1.83"),
    )
    d = svc._row_to_dict(row)
    assert d["top1_ticker"] == "SPHR"
    assert d["top1_weight"] == 0.6528
    assert d["effective_n"] == 1.83
