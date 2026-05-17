"""Tests fuer F-11: Bucket-Risk-Rule-Overrides in alert_service.generate_alerts.

Coverage:
  - max_position_pct: Bucket-Override hat Vorrang vor type/position_type
  - alert_loss_pct: Bucket-Override hat Vorrang vor User-Prefs
  - max_sector_pct: Per-Bucket-Sector-Aggregation produziert eigenen Alert
  - Bei fehlendem buckets_map oder fehlender Rule: Fallback auf Default
"""
from __future__ import annotations

import uuid

import pytest

from services.alert_service import (
    _bucket_loss_pct,
    _get_position_limit,
    generate_alerts,
)


def _pos(
    ticker: str,
    *,
    asset_type: str = "stock",
    position_type: str | None = None,
    bucket_id: str | None = None,
    sector: str = "Tech",
    market_value: float = 10_000,
    shares: float = 10,
    current_price: float = 100,
    stop_loss_price: float | None = None,
    pnl_pct: float = 0,
) -> dict:
    return {
        "ticker": ticker,
        "name": ticker,
        "type": asset_type,
        "position_type": position_type,
        "bucket_id": bucket_id,
        "sector": sector,
        "market_value_chf": market_value,
        "shares": shares,
        "current_price": current_price,
        "stop_loss_price": stop_loss_price,
        "pnl_pct": pnl_pct,
    }


# -- _get_position_limit --------------------------------------------------

def test_position_limit_falls_back_to_type_default():
    p = _pos("AAA", asset_type="stock", position_type="core")
    limit, label = _get_position_limit(p, buckets_map=None)
    assert limit == 10.0  # CORE_STOCK_MAX_PCT
    assert "Core" in label


def test_position_limit_bucket_override_wins():
    bid = "b1"
    p = _pos("AAA", asset_type="stock", position_type="core", bucket_id=bid)
    buckets_map = {bid: {"name": "Spielgeld", "risk_rules": {"max_position_pct": 3.0}}}
    limit, label = _get_position_limit(p, buckets_map=buckets_map)
    assert limit == 3.0
    assert "Spielgeld" in label


def test_position_limit_no_bucket_rule_falls_back():
    bid = "b1"
    p = _pos("AAA", asset_type="etf", position_type="core", bucket_id=bid)
    buckets_map = {bid: {"name": "Core", "risk_rules": {"drawdown_brake_pct": 6.0}}}
    # Keine max_position_pct in Bucket → Type-Default greift
    limit, label = _get_position_limit(p, buckets_map=buckets_map)
    assert limit == 15.0  # CORE_ETF_MAX_PCT
    assert "Core-ETF" in label


# -- _bucket_loss_pct -----------------------------------------------------

def test_bucket_loss_pct_falls_back_to_default():
    p = _pos("AAA", bucket_id=None)
    assert _bucket_loss_pct(p, None, -20.0) == -20.0


def test_bucket_loss_pct_uses_bucket_override():
    bid = "b1"
    p = _pos("AAA", bucket_id=bid)
    bm = {bid: {"name": "X", "risk_rules": {"alert_loss_pct": -10.0}}}
    assert _bucket_loss_pct(p, bm, -20.0) == -10.0


# -- generate_alerts: position_limit -------------------------------------

def test_generate_alerts_position_limit_uses_bucket():
    bid = "b1"
    positions = [
        _pos("AAA", asset_type="stock", position_type="core", bucket_id=bid,
             market_value=8000),
        _pos("BBB", asset_type="stock", position_type="core", bucket_id=bid,
             market_value=92_000),
    ]
    # Bucket-Limit auf 5% → AAA bei 8% triggert
    bm = {bid: {"name": "Strict", "risk_rules": {"max_position_pct": 5.0}}}
    alerts = generate_alerts(positions, None, user_prefs={}, buckets_map=bm)
    pl = [a for a in alerts if a["category"] == "position_limit"]
    assert any(a["ticker"] == "AAA" for a in pl)
    # Message enthaelt Bucket-Name
    aaa = next(a for a in pl if a["ticker"] == "AAA")
    assert "Strict" in aaa["message"]


# -- generate_alerts: sector_limit per bucket ----------------------------

def test_generate_alerts_per_bucket_sector_limit():
    bid = "b1"
    positions = [
        # Im Bucket b1: Tech 60%, Healthcare 40% → Tech > 50% Bucket-Limit
        _pos("AAA", asset_type="stock", bucket_id=bid, sector="Tech",
             market_value=60_000),
        _pos("BBB", asset_type="stock", bucket_id=bid, sector="Healthcare",
             market_value=40_000),
    ]
    bm = {bid: {"name": "Tech-Cap", "risk_rules": {"max_sector_pct": 50.0}}}
    alerts = generate_alerts(positions, None, user_prefs={}, buckets_map=bm)
    bucket_sector_alerts = [
        a for a in alerts
        if a["category"] == "sector_limit" and "Tech-Cap" in a["title"]
    ]
    assert len(bucket_sector_alerts) == 1
    assert "60.0%" in bucket_sector_alerts[0]["message"]


def test_generate_alerts_no_bucket_sector_rule_no_extra_alert():
    bid = "b1"
    positions = [
        _pos("AAA", asset_type="stock", bucket_id=bid, sector="Tech",
             market_value=60_000),
        _pos("BBB", asset_type="stock", bucket_id=bid, sector="Healthcare",
             market_value=40_000),
    ]
    bm = {bid: {"name": "X", "risk_rules": {}}}  # keine max_sector_pct
    alerts = generate_alerts(positions, None, user_prefs={}, buckets_map=bm)
    bucket_sector_alerts = [
        a for a in alerts if a["category"] == "sector_limit" and "Bucket" in a["title"]
    ]
    assert bucket_sector_alerts == []


# -- generate_alerts: loss threshold per bucket --------------------------

def test_generate_alerts_loss_threshold_from_bucket():
    bid = "b1"
    positions = [
        # 50% Verlust, kein Stop-Loss gesetzt
        _pos("AAA", asset_type="stock", position_type="core", bucket_id=bid,
             stop_loss_price=None, pnl_pct=-30.0, market_value=10_000),
    ]
    # Bucket-Override fordert -25% → -30% triggert
    bm = {bid: {"name": "Tight", "risk_rules": {"alert_loss_pct": -25.0}}}
    alerts = generate_alerts(positions, None, user_prefs={}, buckets_map=bm)
    loss = [a for a in alerts if a["category"] == "loss"]
    assert any(a["ticker"] == "AAA" for a in loss)


def test_generate_alerts_loss_threshold_default_when_no_bucket():
    positions = [
        _pos("AAA", asset_type="stock", position_type="core",
             stop_loss_price=None, pnl_pct=-30.0, market_value=10_000),
    ]
    # Core-default: -25% → -30% triggert
    alerts = generate_alerts(positions, None, user_prefs={}, buckets_map=None)
    loss = [a for a in alerts if a["category"] == "loss"]
    assert any(a["ticker"] == "AAA" for a in loss)


# -- F-14: Position-Override > Bucket-Override > Default -----------------

def test_position_limit_override_wins_over_bucket():
    bid = "b1"
    p = _pos("AAA", asset_type="stock", position_type="core", bucket_id=bid)
    p["risk_rules"] = {"max_position_pct": 2.0}
    buckets_map = {bid: {"name": "Bucket-Rule", "risk_rules": {"max_position_pct": 5.0}}}
    limit, label = _get_position_limit(p, buckets_map=buckets_map)
    assert limit == 2.0
    assert "Position-Override" in label


def test_loss_threshold_position_override_wins_over_bucket():
    bid = "b1"
    p = _pos("AAA", bucket_id=bid)
    p["risk_rules"] = {"alert_loss_pct": -8.0}
    bm = {bid: {"name": "X", "risk_rules": {"alert_loss_pct": -15.0}}}
    assert _bucket_loss_pct(p, bm, -25.0) == -8.0


def test_position_override_fallback_to_bucket_when_unset():
    bid = "b1"
    p = _pos("AAA", bucket_id=bid)
    p["risk_rules"] = {"drawdown_brake_pct": 8.0}  # nicht alert_loss_pct
    bm = {bid: {"name": "X", "risk_rules": {"alert_loss_pct": -15.0}}}
    assert _bucket_loss_pct(p, bm, -25.0) == -15.0
