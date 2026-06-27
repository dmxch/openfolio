"""Test der Rebalancing-Mathematik (Soll/Ist/Delta + Cash-First).

get_allocations_by_bucket + get_portfolio_summary werden gemockt (deren Logik ist
anderswo getestet); Bucket-Ziele werden real in die DB geseedet, da der Service
sie von dort liest (target_pct XOR target_chf).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from models.bucket import Bucket, BucketKind
import services.rebalancing_service as rs


async def _seed_bucket(db, uid, name, *, target_pct=None, target_chf=None, kind=BucketKind.user):
    b = Bucket(user_id=uid, name=name, kind=kind, target_pct=target_pct, target_chf=target_chf)
    db.add(b)
    await db.commit()
    await db.refresh(b)
    return b


async def test_soll_ist_delta_and_cash_first(db, monkeypatch):
    uid = uuid.uuid4()
    core = await _seed_bucket(db, uid, "Core", target_pct=Decimal("50"))      # Ziel 50 %
    sat = await _seed_bucket(db, uid, "Satellite", target_pct=Decimal("30"))  # Ziel 30 %
    cash_b = await _seed_bucket(db, uid, "Cash", kind=BucketKind.system)      # ohne Ziel

    # Ist: Core 60 % (6000), Satellite 20 % (2000), Cash 20 % (2000) -> total 10'000
    allocations = [
        {"bucket_id": str(core.id), "name": "Core", "kind": "user", "color": "#111", "value_chf": 6000.0, "pct": 60.0},
        {"bucket_id": str(sat.id), "name": "Satellite", "kind": "user", "color": "#222", "value_chf": 2000.0, "pct": 20.0},
        {"bucket_id": str(cash_b.id), "name": "Cash", "kind": "system", "color": None, "value_chf": 2000.0, "pct": 20.0},
    ]

    async def _fake_alloc(_db, _uid):
        return allocations

    async def _fake_summary(_db, user_id=None):
        return {"positions": [{"type": "cash", "market_value_chf": 2000.0, "count_as_cash": False}]}

    monkeypatch.setattr(rs, "get_allocations_by_bucket", _fake_alloc)
    monkeypatch.setattr(rs, "get_portfolio_summary", _fake_summary)

    res = await rs.get_rebalancing_plan(db, uid)
    assert res["has_targets"] is True
    by = {b["name"]: b for b in res["buckets"]}

    # Core: Soll 50 % / Ist 60 % -> uebergewichtet, ΔCHF -1000
    assert by["Core"]["target_pct"] == 50.0
    assert by["Core"]["delta_pp"] == -10.0
    assert by["Core"]["target_chf"] == 5000.0
    assert by["Core"]["delta_chf"] == -1000.0
    assert by["Core"]["status"] == "uebergewichtet"

    # Satellite: Soll 30 % / Ist 20 % -> untergewichtet, ΔCHF +1000
    assert by["Satellite"]["delta_chf"] == 1000.0
    assert by["Satellite"]["status"] == "untergewichtet"

    # Cash-Bucket ohne Ziel taucht NICHT auf
    assert "Cash" not in by

    assert res["total_underweight_chf"] == 1000.0
    assert res["total_overweight_chf"] == 1000.0
    assert res["available_cash_chf"] == 2000.0
    # 2000 Cash deckt 1000 Untergewicht voll -> 100 %
    assert res["cash_covers_underweight_pct"] == 100.0


async def test_target_chf_variant(db, monkeypatch):
    # Bucket mit absolutem CHF-Ziel statt Prozent.
    uid = uuid.uuid4()
    b = await _seed_bucket(db, uid, "Wachstum", target_chf=Decimal("4000"))
    allocations = [
        {"bucket_id": str(b.id), "name": "Wachstum", "kind": "user", "color": None, "value_chf": 3000.0, "pct": 30.0},
        {"bucket_id": str(uuid.uuid4()), "name": "Rest", "kind": "system", "color": None, "value_chf": 7000.0, "pct": 70.0},
    ]
    monkeypatch.setattr(rs, "get_allocations_by_bucket", lambda _d, _u: _coro(allocations))
    monkeypatch.setattr(rs, "get_portfolio_summary", lambda _d, user_id=None: _coro({"positions": []}))

    res = await rs.get_rebalancing_plan(db, uid)
    w = res["buckets"][0]
    assert w["target_chf"] == 4000.0            # absolutes Ziel direkt
    assert w["target_pct"] == 40.0              # 4000 / 10000
    assert w["delta_chf"] == 1000.0             # 4000 - 3000 -> aufstocken
    assert res["cash_covers_underweight_pct"] == 0.0   # Untergewicht, aber kein Cash -> 0 % gedeckt


async def _coro(value):
    return value


async def test_no_targets_returns_empty(db, monkeypatch):
    uid = uuid.uuid4()
    monkeypatch.setattr(rs, "get_allocations_by_bucket",
                        lambda _d, _u: _coro([{"bucket_id": str(uuid.uuid4()), "name": "X", "kind": "user",
                                               "color": None, "value_chf": 100.0, "pct": 100.0}]))
    monkeypatch.setattr(rs, "get_portfolio_summary", lambda _d, user_id=None: _coro({"positions": []}))
    res = await rs.get_rebalancing_plan(db, uid)
    assert res["has_targets"] is False
    assert res["buckets"] == []
