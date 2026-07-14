"""Vertragstests für get_pe_summary (E1): die PE-Komponente des Netto-Vermögens.

Der Vertrag (net_worth_service konsumiert total_net_value_chf):
  {"total_gross_value_chf": float, "total_net_value_chf": float, "count": int}

Semantik: pro AKTIVEM Holding num_shares × gross-/net_value_per_share aus der
NEUESTEN Valuation; Holding ohne Valuation trägt 0 bei (bewusst, wie heute),
zählt aber im count; Fremdwährung (holdings.currency) wird via
get_fx_rates_batch nach CHF konvertiert; alles user_id-scoped (Multi-User).

Invariante #2 bleibt unberührt: PE ist aus der liquiden Performance komplett
draussen — diese Summe existiert NUR für das Netto-Vermögen (Konzept A).
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

import services.private_equity_service as pe_service
import services.utils as service_utils
from models.private_equity import PrivateEquityHolding, PrivateEquityValuation
from models.user import User
from services.private_equity_service import get_pe_summary


async def _make_user(db) -> User:
    user = User(email=f"pe-{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _patch_fx(monkeypatch, rates: dict[str, float]) -> None:
    """FX-Batch deterministisch stubben (kein DB-Cache-/yfinance-Zugriff im Test).

    Doppelt gepatcht, weil die Bindungsstelle implementierungsabhängig ist:
    an der Definitionsstelle (services.utils — deckt funktionslokale Imports
    und get_fx_rate ab) UND an der Import-Stelle im PE-Service (deckt den
    üblichen Modul-Level-Import ab; raising=False, falls dort keiner ist).
    Sync-Stub, funktioniert damit auch hinter asyncio.to_thread.
    """
    def _stub():
        return dict(rates)

    monkeypatch.setattr(service_utils, "get_fx_rates_batch", _stub)
    monkeypatch.setattr(pe_service, "get_fx_rates_batch", _stub, raising=False)


async def _make_holding(
    db, user_id: uuid.UUID, *, num_shares: int = 100, currency: str = "CHF", is_active: bool = True
) -> PrivateEquityHolding:
    h = PrivateEquityHolding(
        user_id=user_id,
        company_name="Acme AG",  # Plaintext reicht: decrypt_field hat Legacy-Fallback
        num_shares=num_shares,
        nominal_value=100.0,
        currency=currency,
        is_active=is_active,
    )
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


def _valuation(
    holding_id: uuid.UUID, d: date, gross: float, net: float, discount: float = 30.0
) -> PrivateEquityValuation:
    return PrivateEquityValuation(
        holding_id=holding_id,
        valuation_date=d,
        gross_value_per_share=gross,
        discount_pct=discount,
        net_value_per_share=net,
    )


async def test_latest_valuation_gross_and_net(db, monkeypatch):
    """(a) num_shares × per-share aus der NEUESTEN Valuation; net < gross bei Discount."""
    _patch_fx(monkeypatch, {"CHF": 1.0})
    user = await _make_user(db)
    h = await _make_holding(db, user.id, num_shares=100)
    # Ältere Valuation mit anderen Werten — darf NICHT gewinnen.
    db.add(_valuation(h.id, date(2025, 1, 1), gross=40.0, net=28.0))
    # Neueste Valuation: gross 50, Discount 30% -> net 35.
    db.add(_valuation(h.id, date(2026, 1, 1), gross=50.0, net=35.0))
    await db.commit()

    res = await get_pe_summary(db, user.id)
    assert res["count"] == 1
    assert res["total_gross_value_chf"] == pytest.approx(5000.0)  # 100 × 50 (neueste, nicht 40)
    assert res["total_net_value_chf"] == pytest.approx(3500.0)    # 100 × 35 (Steuerwert)
    assert res["total_net_value_chf"] < res["total_gross_value_chf"]


async def test_holding_without_valuation_contributes_zero_but_counts(db, monkeypatch):
    """(b) Holding ohne Valuation: 0 Wertbeitrag (bewusst, wie heute), count zählt es."""
    _patch_fx(monkeypatch, {"CHF": 1.0})
    user = await _make_user(db)
    h1 = await _make_holding(db, user.id, num_shares=10)
    db.add(_valuation(h1.id, date(2026, 1, 1), gross=50.0, net=35.0))
    await _make_holding(db, user.id, num_shares=999)  # keine Valuation
    await db.commit()

    res = await get_pe_summary(db, user.id)
    assert res["count"] == 2
    assert res["total_gross_value_chf"] == pytest.approx(500.0)   # nur h1: 10 × 50
    assert res["total_net_value_chf"] == pytest.approx(350.0)     # nur h1: 10 × 35


async def test_foreign_currency_converted_to_chf(db, monkeypatch):
    """(c) holdings.currency ≠ CHF wird über den FX-Batch nach CHF konvertiert."""
    _patch_fx(monkeypatch, {"CHF": 1.0, "USD": 0.5})  # bewusst weit weg von 1.0
    user = await _make_user(db)
    h = await _make_holding(db, user.id, num_shares=10, currency="USD")
    db.add(_valuation(h.id, date(2026, 1, 1), gross=100.0, net=70.0))
    await db.commit()

    res = await get_pe_summary(db, user.id)
    assert res["count"] == 1
    assert res["total_gross_value_chf"] == pytest.approx(500.0)   # 10 × 100 × 0.5, nicht 1000
    assert res["total_net_value_chf"] == pytest.approx(350.0)     # 10 × 70 × 0.5


async def test_user_scoping_other_user_sees_nothing(db, monkeypatch):
    """(d) Multi-User: fremde Holdings tauchen nicht auf."""
    _patch_fx(monkeypatch, {"CHF": 1.0})
    owner = await _make_user(db)
    other = await _make_user(db)
    h = await _make_holding(db, owner.id, num_shares=100)
    db.add(_valuation(h.id, date(2026, 1, 1), gross=50.0, net=35.0))
    await db.commit()

    res = await get_pe_summary(db, other.id)
    assert res["count"] == 0
    assert res["total_gross_value_chf"] == 0.0
    assert res["total_net_value_chf"] == 0.0


async def test_inactive_holding_excluded(db, monkeypatch):
    """Nur AKTIVE Holdings zählen — verkaufte/abgeschriebene sind komplett raus."""
    _patch_fx(monkeypatch, {"CHF": 1.0})
    user = await _make_user(db)
    h = await _make_holding(db, user.id, num_shares=100, is_active=False)
    db.add(_valuation(h.id, date(2026, 1, 1), gross=50.0, net=35.0))
    await db.commit()

    res = await get_pe_summary(db, user.id)
    assert res["count"] == 0
    assert res["total_gross_value_chf"] == 0.0
    assert res["total_net_value_chf"] == 0.0
