"""FIRE-/Kapital-Projektion: FIRE-Zahl, Compounding/Jahre-bis-FIRE, Kapitalbasis,
Coverage. Startkapital (get_net_worth) gemockt -> testet die Rechen-Logik isoliert."""
from __future__ import annotations

import uuid

import pytest

import services.fire_projection_service as fp

pytestmark = pytest.mark.asyncio


def _ret(securities=0.0, cash=0.0, pension=0.0, net_worth=None):
    nw = net_worth if net_worth is not None else (securities + cash + pension)
    payload = {
        "net_worth_chf": nw,
        "components": [
            {"key": "securities", "value_chf": securities},
            {"key": "cash", "value_chf": cash},
            {"key": "pension", "value_chf": pension},
        ],
    }

    async def _f(_db, _uid):
        return payload
    return _f


async def test_fire_number_from_spending_and_swr(db, monkeypatch):
    monkeypatch.setattr(fp, "get_net_worth", _ret(net_worth=500000))
    res = await fp.compute_fire_projection(
        db, uuid.uuid4(), target_annual_spending_chf=80000, withdrawal_rate_pct=4.0)
    assert res["fire_number_chf"] == 2_000_000.0   # 80000 / 0.04 = 25x


async def test_capital_base_selection(db, monkeypatch):
    monkeypatch.setattr(fp, "get_net_worth", _ret(securities=10, cash=5, pension=20, net_worth=200))
    liquid = await fp.compute_fire_projection(db, uuid.uuid4(), capital_base="liquid")
    withp = await fp.compute_fire_projection(db, uuid.uuid4(), capital_base="with_pension")
    netw = await fp.compute_fire_projection(db, uuid.uuid4(), capital_base="net_worth")
    assert liquid["starting_capital_chf"] == 15.0
    assert withp["starting_capital_chf"] == 35.0
    assert netw["starting_capital_chf"] == 200.0


async def test_private_equity_only_in_net_worth_base(db, monkeypatch):
    """PE steckt (via net_worth_chf) NUR in der net_worth-Basis, nicht in
    liquid/with_pension (illiquide). Hierarchie liquid ⊂ with_pension ⊂ net_worth."""
    # securities 600 + cash 150 + pension 250 + PE 500 (PE nur in net_worth_chf)
    monkeypatch.setattr(fp, "get_net_worth", _ret(securities=600, cash=150, pension=250, net_worth=1500))
    liquid = await fp.compute_fire_projection(db, uuid.uuid4(), capital_base="liquid")
    withp = await fp.compute_fire_projection(db, uuid.uuid4(), capital_base="with_pension")
    netw = await fp.compute_fire_projection(db, uuid.uuid4(), capital_base="net_worth")
    assert liquid["starting_capital_chf"] == 750.0     # PE NICHT drin
    assert withp["starting_capital_chf"] == 1000.0     # PE NICHT drin
    assert netw["starting_capital_chf"] == 1500.0      # PE drin (volles Netto-Vermögen)


async def test_years_to_fire_compounding(db, monkeypatch):
    monkeypatch.setattr(fp, "get_net_worth", _ret(securities=100000))
    res = await fp.compute_fire_projection(
        db, uuid.uuid4(), capital_base="liquid",
        annual_return_pct=10.0, annual_savings_chf=0.0,
        withdrawal_rate_pct=10.0, target_annual_spending_chf=12100,  # fire = 121000
        horizon_years=10)
    # 100000 -> 110000 (J1) -> 121000 (J2) >= 121000
    assert res["fire_number_chf"] == 121000.0
    assert res["years_to_fire"] == 2
    assert res["coverage_pct"] == 82.6
    assert res["projection"][2]["capital_chf"] == 121000.0


async def test_already_covered_is_zero_years(db, monkeypatch):
    monkeypatch.setattr(fp, "get_net_worth", _ret(securities=3_000_000))
    res = await fp.compute_fire_projection(
        db, uuid.uuid4(), capital_base="liquid",
        target_annual_spending_chf=80000, withdrawal_rate_pct=4.0)   # fire = 2.0M
    assert res["years_to_fire"] == 0
    assert res["coverage_pct"] >= 100.0


async def test_no_target_no_fire_number(db, monkeypatch):
    monkeypatch.setattr(fp, "get_net_worth", _ret(net_worth=250000))
    res = await fp.compute_fire_projection(db, uuid.uuid4(), target_annual_spending_chf=None)
    assert res["fire_number_chf"] is None
    assert res["years_to_fire"] is None
    assert res["coverage_pct"] is None
    assert res["projection"][0]["capital_chf"] == 250000.0   # Kurve trotzdem da


async def test_not_reached_in_horizon(db, monkeypatch):
    monkeypatch.setattr(fp, "get_net_worth", _ret(securities=10000))
    res = await fp.compute_fire_projection(
        db, uuid.uuid4(), capital_base="liquid",
        annual_return_pct=1.0, annual_savings_chf=0.0,
        withdrawal_rate_pct=4.0, target_annual_spending_chf=1_000_000,  # fire = 25M, unerreichbar
        horizon_years=5)
    assert res["years_to_fire"] is None
    assert len(res["projection"]) == 6   # Jahr 0..5
