"""Trust-Haertung fuer import_service.confirm_import — der Schreibpfad, der einen
Import festschreibt (Positionen + Transaktionen, dann recalc/Snapshot-Regen).

Gepinnte high-severity Invarianten:
  - Ownership: eine position_id, die einem ANDEREN User gehoert (oder unbekannt
    ist), wird uebersprungen — niemals an fremde Positionen gehaengt (Multi-User).
  - Malformed position_id wird sauber uebersprungen (kein Crash).
  - Server-seitige Dedup (Idempotenz): exakte Duplikate werden auch ohne
    Client-Flag erkannt; force_import ist der explizite Override.
  - total_chf wird aus fx_rate abgeleitet (shares*price*fx + fees), nicht der
    Client-Wert blind uebernommen (Korrektheits-Invariante #1).
  - Buy aktualisiert shares + cost_basis_chf der Position.
  - Manuelle Salden (cash/pension) bekommen KEINEN yfinance_ticker; handelbare
    Typen bekommen einen.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

import services.import_service as imp
from models.position import AssetType, Position, PriceSource
from models.report import Report
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_system_buckets, get_liquid_default_bucket

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    # System-Buckets + Liquid-Default anlegen (positions.bucket_id ist NOT NULL)
    await create_system_buckets(db, user.id)
    await get_liquid_default_bucket(db, user.id)
    await db.commit()
    return user


async def _make_position(db, user, *, ticker="AAPL", shares="0", cost="0") -> Position:
    liquid = await get_liquid_default_bucket(db, user.id)
    pos = Position(
        user_id=user.id,
        bucket_id=liquid.id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="USD",
        price_source=PriceSource.yahoo,
        shares=Decimal(shares),
        cost_basis_chf=Decimal(cost),
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


def _txn(pos_id, **over) -> dict:
    base = {
        "position_id": str(pos_id),
        "type": "buy",
        "date": "2025-01-15",
        "shares": 10,
        "price_per_share": 150.0,
        "currency": "CHF",
        "fx_rate_to_chf": 1.0,
        "fees_chf": 0,
        "taxes_chf": 0,
        "total_chf": 1500.0,
    }
    base.update(over)
    return base


# --- Ownership / Multi-User ------------------------------------------------

async def test_foreign_position_id_is_skipped(db):
    """Eine Transaktion auf die Position eines ANDEREN Users wird verworfen."""
    owner = await _make_user(db)
    pos = await _make_position(db, owner, ticker="OWNED")
    attacker = await _make_user(db)

    res = await imp.confirm_import(
        transactions=[_txn(pos.id)],
        new_positions=[],
        db=db,
        user_id=attacker.id,
    )
    assert res["created_transactions"] == 0
    # Keine Transaktion an der fremden Position
    rows = (await db.execute(select(Transaction).where(Transaction.position_id == pos.id))).scalars().all()
    assert rows == []


async def test_malformed_position_id_is_skipped(db):
    user = await _make_user(db)
    res = await imp.confirm_import(
        transactions=[_txn("not-a-uuid")],
        new_positions=[],
        db=db,
        user_id=user.id,
    )
    assert res["created_transactions"] == 0


# --- Server-seitige Dedup / Idempotenz -------------------------------------

async def test_server_side_exact_dup_skipped_without_client_flag(db):
    """Re-Import desselben Trades wird server-seitig erkannt, auch ohne is_duplicate."""
    user = await _make_user(db)
    pos = await _make_position(db, user, ticker="DUP")
    # Vorbestehende Transaktion (gleiche Position/Datum/Typ/total_chf)
    db.add(Transaction(
        position_id=pos.id, user_id=user.id, type=TransactionType.buy,
        date=date(2025, 1, 15), shares=Decimal("10"), price_per_share=Decimal("150"),
        currency="CHF", fx_rate_to_chf=Decimal("1"), total_chf=Decimal("1500"),
    ))
    await db.commit()

    res = await imp.confirm_import(
        transactions=[_txn(pos.id)],   # KEIN is_duplicate-Flag
        new_positions=[], db=db, user_id=user.id,
    )
    assert res["created_transactions"] == 0
    assert res["skipped_duplicates"] == 1


async def test_force_import_overrides_dedup(db):
    user = await _make_user(db)
    pos = await _make_position(db, user, ticker="FORCE")
    db.add(Transaction(
        position_id=pos.id, user_id=user.id, type=TransactionType.buy,
        date=date(2025, 1, 15), shares=Decimal("10"), price_per_share=Decimal("150"),
        currency="CHF", fx_rate_to_chf=Decimal("1"), total_chf=Decimal("1500"),
    ))
    await db.commit()

    res = await imp.confirm_import(
        transactions=[_txn(pos.id, force_import=True)],
        new_positions=[], db=db, user_id=user.id,
    )
    assert res["created_transactions"] == 1
    assert res["skipped_duplicates"] == 0


# --- Korrektheit: total_chf aus fx_rate -----------------------------------

async def test_total_chf_derived_from_fx_not_client_value(db):
    """Bei Fremdwaehrung wird total_chf serverseitig gerechnet, Client-Wert ignoriert."""
    user = await _make_user(db)
    pos = await _make_position(db, user, ticker="FX")

    res = await imp.confirm_import(
        transactions=[_txn(
            pos.id, currency="USD", fx_rate_to_chf=0.9,
            shares=10, price_per_share=150.0, fees_chf=5,
            total_chf=0.0,   # falscher/leerer Client-Wert
        )],
        new_positions=[], db=db, user_id=user.id,
    )
    assert res["created_transactions"] == 1
    txn = (await db.execute(select(Transaction).where(Transaction.position_id == pos.id))).scalar_one()
    # 10 * 150 * 0.9 + 5 = 1355.0
    assert float(txn.total_chf) == 1355.0


async def test_buy_updates_position_shares_and_cost_basis(db):
    user = await _make_user(db)
    pos = await _make_position(db, user, ticker="GROW", shares="5", cost="500")

    await imp.confirm_import(
        transactions=[_txn(pos.id, shares=10, total_chf=1500.0)],
        new_positions=[], db=db, user_id=user.id,
    )
    await db.refresh(pos)
    assert float(pos.shares) == 15.0          # 5 + 10
    assert float(pos.cost_basis_chf) == 2000.0  # 500 + 1500


# --- Neue Positionen: Manual-Balance-Invariante ---------------------------

async def test_new_cash_position_has_no_yfinance_ticker(db):
    """Cash/Pension = manuelle Salden -> kein yfinance_ticker (Saldo-Fehlbepreis-Schutz)."""
    user = await _make_user(db)
    res = await imp.confirm_import(
        transactions=[],
        new_positions=[{
            "ticker": "CASH-USD", "name": "USD Cash", "suggested_type": "cash",
            "currency": "USD", "key": "CASH-USD", "yfinance_ticker": "CASH-USD",
        }],
        db=db, user_id=user.id,
    )
    assert res["created_positions"] == 1
    pos = (await db.execute(
        select(Position).where(Position.user_id == user.id, Position.ticker == "CASH-USD")
    )).scalar_one()
    assert pos.type == AssetType.cash
    assert pos.yfinance_ticker is None
    assert pos.bucket_id is not None


async def test_new_stock_position_keeps_yfinance_ticker(db, monkeypatch):
    """Handelbare Typen bekommen einen yfinance_ticker (Default = ticker)."""
    # _auto_assign_industries macht sonst einen yfinance-Netz-Call fuer Stocks.
    async def _noop(_db, _positions):
        return None
    monkeypatch.setattr(imp, "_auto_assign_industries", _noop)

    user = await _make_user(db)
    res = await imp.confirm_import(
        transactions=[],
        new_positions=[{
            "ticker": "MSFT", "name": "Microsoft", "suggested_type": "stock",
            "currency": "USD", "key": "MSFT",
        }],
        db=db, user_id=user.id,
    )
    assert res["created_positions"] == 1
    pos = (await db.execute(
        select(Position).where(Position.user_id == user.id, Position.ticker == "MSFT")
    )).scalar_one()
    assert pos.yfinance_ticker == "MSFT"


async def test_confirm_import_auto_links_open_trade_report(db):
    """Bulk-Hook: eine importierte Buy-Txn verlinkt den offenen Vault-Trade-Plan."""
    user = await _make_user(db)
    pos = await _make_position(db, user, ticker="AAPL")
    db.add(Report(
        user_id=user.id, category="trade", title="Trade-Plan AAPL",
        report_date=date(2025, 1, 15), body="...", content_hash="tj-imp-1",
        ticker="AAPL", side="buy",
    ))
    await db.commit()

    res = await imp.confirm_import(
        transactions=[_txn(pos.id, shares=10, total_chf=1500.0, force_import=True)],
        new_positions=[], db=db, user_id=user.id,
    )
    assert res["created_transactions"] == 1

    txn = (await db.execute(
        select(Transaction).where(Transaction.position_id == pos.id)
    )).scalar_one()
    rep = (await db.execute(
        select(Report).where(Report.user_id == user.id, Report.category == "trade")
    )).scalar_one()
    assert rep.linked_transaction_id == txn.id   # Bulk-Hook hat den Plan verlinkt
