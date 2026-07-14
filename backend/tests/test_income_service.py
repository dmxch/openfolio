"""Test Dividenden Yield-on-Cost: nur effektiv erhaltene Divs (12M) / cost_basis,
nur liquide Wertschriften, alte Divs ausserhalb des Fensters ignoriert."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType
from services.income_service import get_dividend_yield_on_cost

TODAY = date(2026, 6, 27)


def _pos(uid, ticker, *, cost, shares=10, atype=AssetType.stock, cash=False):
    return Position(user_id=uid, bucket_id=uuid.uuid4(), ticker=ticker, name=ticker,
                    type=atype, currency="CHF", shares=Decimal(str(shares)),
                    cost_basis_chf=Decimal(str(cost)), count_as_cash=cash, is_active=True)


def _div(uid, pos_id, total, d):
    return Transaction(user_id=uid, position_id=pos_id, type=TransactionType.dividend,
                       date=d, currency="CHF", total_chf=Decimal(str(total)))


async def test_yield_on_cost(db):
    uid = uuid.uuid4()
    p1 = _pos(uid, "AAA", cost=1000)            # eligible, zahlt 50 -> YoC 5%
    p2 = _pos(uid, "BBB", cost=2000)            # eligible, kein Div
    p3 = _pos(uid, "CASH", cost=500, atype=AssetType.cash)   # raus (type)
    p4 = _pos(uid, "TBILL", cost=800, cash=True)             # raus (count_as_cash)
    db.add_all([p1, p2, p3, p4])
    await db.commit()
    for p in (p1, p2, p3, p4):
        await db.refresh(p)

    db.add_all([
        _div(uid, p1.id, 30, date(2026, 3, 1)),   # innerhalb 12M
        _div(uid, p1.id, 20, date(2025, 9, 1)),   # innerhalb 12M (Summe 50)
        _div(uid, p1.id, 99, date(2025, 1, 1)),   # AUSSERHALB (>365d vor TODAY) -> ignoriert
        _div(uid, p4.id, 40, date(2026, 3, 1)),   # count_as_cash -> nicht eligible
    ])
    await db.commit()

    res = await get_dividend_yield_on_cost(db, uid, today=TODAY)
    assert res["has_data"] is True
    assert res["trailing_dividends_chf"] == 50.0          # 30+20, die 99 raus
    assert res["eligible_cost_basis_chf"] == 3000.0       # 1000 + 2000 (cash/tbill raus)
    # Portfolio-YoC = 50 / 3000 = 1.67 %
    assert res["portfolio_yoc_pct"] == 1.67
    # Nur der Zahler taucht in positions auf
    assert [p["ticker"] for p in res["positions"]] == ["AAA"]
    assert res["positions"][0]["yoc_pct"] == 5.0          # 50 / 1000
    assert res["positions"][0]["dividends_12m_chf"] == 50.0


async def test_bond_counts_in_numerator_and_denominator(db):
    """Anleihen schuetten aus — die Ausschuettung ist Ertrag wie eine Dividende.

    Beide Seiten des Bruchs muessen sie sehen: faellt bond aus dem Typ-Filter,
    verschwindet sowohl der Ertrag (Zaehler) als auch die Kostenbasis (Nenner) —
    das ist doppelt still, weil der YoC-Prozentsatz dabei plausibel bleibt und
    nur die absoluten Zahlen schrumpfen.

    Herleitung:
      Aktie AAA:   cost 1000, Div 50
      Anleihe IB01: cost 4000, Ausschuettung 80
      Zaehler = 50 + 80 = 130 ; Nenner = 1000 + 4000 = 5000
      Portfolio-YoC = 130 / 5000 = 2.6 %
    """
    uid = uuid.uuid4()
    p1 = _pos(uid, "AAA", cost=1000)
    p2 = _pos(uid, "IB01.L", cost=4000, atype=AssetType.bond)
    db.add_all([p1, p2])
    await db.commit()
    for p in (p1, p2):
        await db.refresh(p)

    db.add_all([
        _div(uid, p1.id, 50, date(2026, 3, 1)),
        _div(uid, p2.id, 80, date(2026, 3, 1)),
    ])
    await db.commit()

    res = await get_dividend_yield_on_cost(db, uid, today=TODAY)
    assert res["trailing_dividends_chf"] == 130.0     # Zaehler: Anleihen-Ertrag drin
    assert res["eligible_cost_basis_chf"] == 5000.0   # Nenner: Anleihen-Kostenbasis drin
    assert res["portfolio_yoc_pct"] == 2.6
    # Die Anleihe erscheint als eigener Zahler mit eigenem YoC (80 / 4000 = 2 %).
    by_ticker = {p["ticker"]: p for p in res["positions"]}
    assert by_ticker["IB01.L"]["yoc_pct"] == 2.0
    assert by_ticker["IB01.L"]["dividends_12m_chf"] == 80.0


async def test_no_eligible_positions(db):
    uid = uuid.uuid4()
    db.add(_pos(uid, "CASH", cost=500, atype=AssetType.cash))
    await db.commit()
    res = await get_dividend_yield_on_cost(db, uid, today=TODAY)
    assert res["has_data"] is False
    assert res["positions"] == []
