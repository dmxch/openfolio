"""Per-Position-Rebalancing: Bucket-Ueberhang -> Trim-Kandidaten (largest-first)
+ Konzentrations-Flags. Upstreams (Plan/Summary) gemockt -> testet die Logik isoliert."""
from __future__ import annotations

import uuid

import pytest

import services.position_rebalancing_service as pr

pytestmark = pytest.mark.asyncio


def _ret(val):
    async def _f(_db, _user_id):
        return val
    return _f


def _patch(monkeypatch, buckets, positions, has_targets=True):
    monkeypatch.setattr(pr, "get_rebalancing_plan",
                        _ret({"has_targets": has_targets, "buckets": buckets}))
    monkeypatch.setattr(pr, "get_portfolio_summary", _ret({"positions": positions}))


async def test_overweight_decomposed_largest_first(db, monkeypatch):
    _patch(monkeypatch,
        buckets=[
            {"bucket_id": "B1", "name": "Core", "delta_chf": -1000.0},   # 1000 uebergewichtet
            {"bucket_id": "B2", "name": "Sat", "delta_chf": 500.0},      # untergewichtet -> ignoriert
        ],
        positions=[
            {"ticker": "AAA", "name": "A", "type": "stock", "bucket_id": "B1", "market_value_chf": 700.0, "weight_pct": 7.0},
            {"ticker": "BBB", "name": "B", "type": "stock", "bucket_id": "B1", "market_value_chf": 400.0, "weight_pct": 4.0},
            {"ticker": "CASH", "type": "cash", "bucket_id": "B1", "market_value_chf": 9999.0, "count_as_cash": True},
        ])
    res = await pr.get_position_rebalancing(db, uuid.uuid4())
    tc = res["trim_candidates"]
    assert [(t["ticker"], t["trim_chf"]) for t in tc] == [("AAA", 700.0), ("BBB", 300.0)]  # largest-first
    assert all(t["bucket_name"] == "Core" for t in tc)
    assert "CASH" not in [t["ticker"] for t in tc]   # cash nicht trimmbar


async def test_overweight_capped_at_available_holdings(db, monkeypatch):
    _patch(monkeypatch,
        buckets=[{"bucket_id": "B1", "name": "Core", "delta_chf": -2000.0}],   # 2000 uebergewichtet
        positions=[
            {"ticker": "AAA", "type": "stock", "bucket_id": "B1", "market_value_chf": 700.0, "weight_pct": 7.0},
            {"ticker": "BBB", "type": "stock", "bucket_id": "B1", "market_value_chf": 400.0, "weight_pct": 4.0},
        ])
    res = await pr.get_position_rebalancing(db, uuid.uuid4())
    # nur 1100 handelbar -> AAA 700 + BBB 400, kein Overflow darueber hinaus
    assert [(t["ticker"], t["trim_chf"]) for t in res["trim_candidates"]] == [("AAA", 700.0), ("BBB", 400.0)]


async def test_underweight_only_no_trim(db, monkeypatch):
    _patch(monkeypatch,
        buckets=[{"bucket_id": "B1", "name": "Core", "delta_chf": 800.0}],     # untergewichtet
        positions=[{"ticker": "AAA", "type": "stock", "bucket_id": "B1", "market_value_chf": 500.0, "weight_pct": 5.0}])
    res = await pr.get_position_rebalancing(db, uuid.uuid4())
    assert res["trim_candidates"] == []


async def test_concentration_flags_threshold_and_eligibility(db, monkeypatch):
    _patch(monkeypatch,
        buckets=[],
        positions=[
            {"ticker": "BIG", "name": "Big", "type": "stock", "bucket_id": "B1", "market_value_chf": 5000.0, "weight_pct": 15.0},
            {"ticker": "SMALL", "type": "stock", "bucket_id": "B1", "market_value_chf": 500.0, "weight_pct": 5.0},
            {"ticker": "PENS", "type": "pension", "bucket_id": "B9", "market_value_chf": 9000.0, "weight_pct": 30.0},
            {"ticker": "TBILL", "type": "etf", "bucket_id": "B1", "market_value_chf": 8000.0, "weight_pct": 20.0, "count_as_cash": True},
        ],
        has_targets=False)
    res = await pr.get_position_rebalancing(db, uuid.uuid4())
    flags = [f["ticker"] for f in res["concentration_flags"]]
    assert flags == ["BIG"]                  # >=10% und handelbar
    assert "SMALL" not in flags              # unter Schwelle
    assert "PENS" not in flags               # Vorsorge nicht handelbar
    assert "TBILL" not in flags              # count_as_cash nicht handelbar
    assert res["trim_candidates"] == []      # keine Ziele -> kein Trim
    assert res["has_data"] is True           # Flag allein reicht


async def test_multiple_overweight_buckets(db, monkeypatch):
    _patch(monkeypatch,
        buckets=[
            {"bucket_id": "B1", "name": "Core", "delta_chf": -500.0},
            {"bucket_id": "B2", "name": "Sat", "delta_chf": -300.0},
        ],
        positions=[
            {"ticker": "AAA", "type": "stock", "bucket_id": "B1", "market_value_chf": 900.0, "weight_pct": 9.0},
            {"ticker": "BBB", "type": "stock", "bucket_id": "B2", "market_value_chf": 900.0, "weight_pct": 9.0},
        ])
    res = await pr.get_position_rebalancing(db, uuid.uuid4())
    got = {(t["ticker"], t["bucket_name"]): t["trim_chf"] for t in res["trim_candidates"]}
    assert got == {("AAA", "Core"): 500.0, ("BBB", "Sat"): 300.0}   # je Bucket eigener Ueberhang


async def test_position_without_bucket_flagged_not_trimmed(db, monkeypatch):
    """Handelbare Position ohne bucket_id: kann nicht getrimmt werden (kein Bucket-
    Ziel), taucht aber als Konzentrations-Flag auf, wenn ueber der Schwelle."""
    _patch(monkeypatch,
        buckets=[{"bucket_id": "B1", "name": "Core", "delta_chf": -1000.0}],
        positions=[
            {"ticker": "ORPH", "type": "stock", "bucket_id": None, "market_value_chf": 5000.0, "weight_pct": 14.0},
        ])
    res = await pr.get_position_rebalancing(db, uuid.uuid4())
    assert res["trim_candidates"] == []                               # kein Bucket -> kein Trim
    assert [f["ticker"] for f in res["concentration_flags"]] == ["ORPH"]


async def test_no_targets_no_flags_has_no_data(db, monkeypatch):
    _patch(monkeypatch, buckets=[],
        positions=[{"ticker": "AAA", "type": "stock", "bucket_id": "B1", "market_value_chf": 500.0, "weight_pct": 5.0}],
        has_targets=False)
    res = await pr.get_position_rebalancing(db, uuid.uuid4())
    assert res["has_data"] is False
