"""Regressionstests Welle 5, Fixer «import» (Vollreview vom 13.11.2026).

Funde: R-importtx-2 (CHF-Betrag des eigenen Exports doppelt umgerechnet),
R-importtx-3 (neue Position nur mit Dividenden bleibt aktiv), R-importtx-4
(Pending Order lehnt Ticker einer importierten Position ab), R-importtx-5
(Analyse zählt den FX-Abschnitt von IBKR-Dateien), R-importtx-6 (Reaktivierung
im Recalc verletzt den Unique-Index).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

import api.imports as imports_api
import services.import_service as imp
from models.pending_order import PendingOrder
from models.position import AssetType, Position, PriceSource
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_system_buckets, get_liquid_default_bucket
from services.recalculate_service import recalculate_all_positions, recalculate_position
from services.settings_service import export_transactions_csv

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"
TODAY = date.today().isoformat()

IBKR_HEADER = (
    "Symbol,ISIN,CurrencyPrimary,AssetClass,TradeDate,Buy/Sell,Quantity,TradePrice,"
    "IBCommission,IBCommissionCurrency,TradeMoney,ListingExchange,FXRateToBase,Taxes,"
    "Description,Notes/Codes,TransactionType"
)
IBKR_TRADE = "NOVN,CH0012005267,CHF,STK,20240320,BUY,20,95.50,-5.00,CHF,-1910.00,SWX,1.0,0,NOVARTIS,,ExchTrade"
IBKR_FX_SECTION = ["Date/Time,FromCurrency,ToCurrency,Rate"] + ["20240320,USD,CHF,0.88"] * 10
IBKR_CASH_HEADER = (
    "ClientAccountID,CurrencyPrimary,FXRateToBase,Symbol,ISIN,ListingExchange,"
    "Date/Time,SettleDate,Amount,Type,Description"
)
IBKR_CASH_DIVIDEND = "U1,CHF,1,NESN,CH0038863350,EBS,20240315;093000,20240318,85.00,Dividends,NESN DIV"


@pytest.fixture(autouse=True)
def no_network():
    """Kein Snapshot-Regen, kein Yahoo-Abruf, keine Branchen-Zuordnung."""
    info = AsyncMock(return_value={"shortName": "Test AG", "currency": "USD"})
    with (
        patch("api.orders.trigger_snapshot_regen"),
        patch("api.imports.trigger_snapshot_regen"),
        patch("services.ticker_info_service.get_ticker_info_cached", info),
        patch("services.import_service._auto_assign_industries", AsyncMock()),
    ):
        yield


# --- Helfer ------------------------------------------------------------------

async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await create_system_buckets(db, user.id)
    await get_liquid_default_bucket(db, user.id)
    await db.commit()
    return user


async def _make_position(db, user_id, *, ticker="AAPL", shares="0", cost="0", **over) -> Position:
    liquid = await get_liquid_default_bucket(db, user_id)
    fields = dict(
        user_id=user_id,
        bucket_id=liquid.id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="CHF",
        price_source=PriceSource.yahoo,
        shares=Decimal(shares),
        cost_basis_chf=Decimal(cost),
    )
    fields.update(over)
    pos = Position(**fields)
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


def _ledger_txn(pos: Position, txn_type: TransactionType, day: int, shares: str, total: str, **over) -> Transaction:
    fields = dict(
        position_id=pos.id, user_id=pos.user_id, type=txn_type, date=date(2024, 3, day),
        shares=Decimal(shares), price_per_share=Decimal("10"), currency="CHF",
        fx_rate_to_chf=Decimal("1"), total_chf=Decimal(total),
    )
    fields.update(over)
    return Transaction(**fields)


def _import_txn(pos_id, **over) -> dict:
    base = {
        "position_id": str(pos_id) if pos_id else None,
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


async def _confirm_preview(db, preview: imp.ImportPreview, user_id) -> dict:
    """Wie der Wizard und die Route: Vorschau unverändert durch ConfirmRequest."""
    request = imports_api.ConfirmRequest(
        transactions=[t.model_dump() for t in preview.transactions],
        new_positions=preview.new_positions,
    )
    return await imp.confirm_import(
        [t.model_dump(exclude_none=True) for t in request.transactions],
        [p.model_dump(exclude_none=True) for p in request.new_positions],
        db, user_id,
    )


async def _stored_totals(db, user_id) -> dict[str, float]:
    rows = (await db.execute(
        select(Transaction.type, Transaction.total_chf).where(Transaction.user_id == user_id)
    )).all()
    return {txn_type.value: float(total) for txn_type, total in rows}


async def _login(client, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _user_id(db, email: str) -> uuid.UUID:
    return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _closed_position_with_ledger_shares(db, user_id, ticker="DUPL") -> Position:
    """Altzustand K041: Verkauf auf 50 korrigiert, die Position blieb inaktiv."""
    pos = await _make_position(db, user_id, ticker=ticker, shares="50", cost="500", is_active=False)
    db.add(_ledger_txn(pos, TransactionType.buy, 1, "100", "1000"))
    db.add(_ledger_txn(pos, TransactionType.sell, 5, "50", "600"))
    await db.commit()
    return pos


# --- R-importtx-2: eigener Export, Betrag steht schon in CHF ------------------

class TestOwnExportDividend:
    @pytest.mark.parametrize("shares, price", [("0", "0"), ("100", "0.5")])
    async def test_roundtrip_keeps_the_chf_amount_of_a_usd_dividend(self, db, shares, price):
        source = await _make_user(db)
        pos = await _make_position(db, source.id, ticker="DIVUSD", currency="USD")
        db.add(Transaction(
            position_id=pos.id, user_id=source.id, type=TransactionType.buy, date=date(2025, 3, 10),
            shares=Decimal("100"), price_per_share=Decimal("150"), currency="USD",
            fx_rate_to_chf=Decimal("0.9"), fees_chf=Decimal("5"), total_chf=Decimal("13505"),
        ))
        db.add(Transaction(
            position_id=pos.id, user_id=source.id, type=TransactionType.dividend, date=date(2025, 3, 20),
            shares=Decimal(shares), price_per_share=Decimal(price), currency="USD",
            fx_rate_to_chf=Decimal("0.9"), total_chf=Decimal("38.25"),
        ))
        await db.commit()
        exported = await export_transactions_csv(db, source.id)

        # Leeres Konto: im Quellkonto gälte jede Zeile als Duplikat.
        target = await _make_user(db)
        preview = await imp.parse_csv(exported.encode("utf-8"), "export.csv", db, user_id=target.id)
        assert {t.type: t.total_chf for t in preview.transactions} == {"buy": 13505.0, "dividend": 38.25}
        assert all(t.total_in_chf for t in preview.transactions)

        await _confirm_preview(db, preview, target.id)

        # Vorher: 38.25 × 0.9 = 34.43. Der Kauf folgt weiter Stück × Kurs × FX + Gebühren.
        assert await _stored_totals(db, target.id) == {"buy": 13505.0, "dividend": 38.25}

    async def test_amount_of_another_column_is_still_converted(self, db):
        """Die Spalte «Total» sagt nichts über die Währung: der Betrag wird umgerechnet."""
        user = await _make_user(db)
        await _make_position(db, user.id, ticker="DIVUSD", currency="USD")
        csv_bytes = (
            "Date,Type,Ticker,Shares,Price,Currency,FX,Total\n"
            "2025-03-20,dividend,DIVUSD,0,0,USD,0.9,45\n"
        ).encode("utf-8")

        preview = await imp.parse_csv(csv_bytes, "generic.csv", db, user_id=user.id)
        assert [t.total_in_chf for t in preview.transactions] == [False]
        await _confirm_preview(db, preview, user.id)

        assert await _stored_totals(db, user.id) == {"dividend": 40.5}

    async def test_confirm_request_passes_the_flag_through(self):
        txn = imports_api.ImportTransaction(type="dividend", date="2025-03-20", total_chf=38.25, total_in_chf=True)
        assert txn.model_dump(exclude_none=True)["total_in_chf"] is True
        assert imports_api.ImportTransaction(type="dividend", date="2025-03-20").total_in_chf is False


# --- R-importtx-3: neue Position nur mit Dividenden ---------------------------

class TestNewPositionWithDividendsOnly:
    async def test_dividend_import_on_a_new_title_ends_inactive(self, db):
        """IBKR-Dividendendatei für einen Titel ohne bestehende Position."""
        user = await _make_user(db)
        csv_bytes = "\n".join([IBKR_CASH_HEADER, IBKR_CASH_DIVIDEND]).encode("utf-8")
        preview = await imp.parse_csv(csv_bytes, "dividends.csv", db, user_id=user.id)
        assert [t.type for t in preview.transactions] == ["dividend"]
        assert [p["ticker"] for p in preview.new_positions] == ["NESN.SW"]

        result = await _confirm_preview(db, preview, user.id)
        await recalculate_all_positions(db, user_id=user.id)  # wie die Route nach dem Import

        assert result["created_transactions"] == 1
        pos = (await db.execute(select(Position).where(Position.user_id == user.id))).scalar_one()
        await db.refresh(pos)
        assert (pos.ticker, float(pos.shares), pos.is_active) == ("NESN.SW", 0.0, False)

    async def test_new_title_with_a_buy_stays_active(self, db):
        user = await _make_user(db)
        csv_bytes = (
            "Date,Type,Ticker,Shares,Price,Currency,Total\n"
            "2024-03-15,dividend,NESN.SW,0,0,CHF,85.00\n"
            "2024-02-01,buy,NESN.SW,10,100,CHF,1000\n"
        ).encode("utf-8")
        preview = await imp.parse_csv(csv_bytes, "mixed.csv", db, user_id=user.id)

        await _confirm_preview(db, preview, user.id)

        pos = (await db.execute(select(Position).where(Position.user_id == user.id))).scalar_one()
        await db.refresh(pos)
        assert (float(pos.shares), pos.is_active) == (10.0, True)

    async def test_new_cash_account_with_interest_stays_active(self, db):
        """Cash trägt seinen Saldo ohne Stückzahl: 0 Stück heisst dort nicht «geschlossen»."""
        user = await _make_user(db)
        await imp.confirm_import(
            [_import_txn(None, type="interest", shares=0, price_per_share=0, total_chf=3.2,
                         ticker="CASH_ZKB", is_new_position=True)],
            [{"ticker": "CASH_ZKB", "name": "ZKB Konto", "suggested_type": "cash"}],
            db, user.id,
        )
        pos = (await db.execute(select(Position).where(Position.user_id == user.id))).scalar_one()
        assert pos.is_active is True


# --- R-importtx-5: Analyse einer IBKR-Datei mit langem FX-Abschnitt -----------

class TestAnalyzeIbkrSections:
    async def test_fx_section_does_not_count_against_the_row_limit(self, db, monkeypatch, tmp_path):
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 2)
        monkeypatch.setattr(imp, "UPLOAD_DIR", str(tmp_path))
        content = "\n".join([IBKR_HEADER, IBKR_TRADE, IBKR_TRADE] + IBKR_FX_SECTION).encode("utf-8")

        analysis = await imp.analyze_csv_structure(content, "flex.csv", db, uuid.uuid4())

        assert analysis["detected_broker"] == "interactive_brokers"
        assert analysis["row_count"] == 2
        assert all(row[0] == "NOVN" for row in analysis["sample_rows"])
        assert analysis["unique_types"] == [{"value": "BUY", "count": 2}]

    async def test_trade_section_itself_stays_limited(self, db, monkeypatch, tmp_path):
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 2)
        monkeypatch.setattr(imp, "UPLOAD_DIR", str(tmp_path))
        content = "\n".join([IBKR_HEADER] + [IBKR_TRADE] * 3 + IBKR_FX_SECTION).encode("utf-8")

        with pytest.raises(ValueError, match="mehr als"):
            await imp.analyze_csv_structure(content, "flex.csv", db, uuid.uuid4())
        assert list(tmp_path.iterdir()) == []

    async def test_ibkr_cash_file_counts_every_row_like_its_parser(self, db, monkeypatch, tmp_path):
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 2)
        monkeypatch.setattr(imp, "UPLOAD_DIR", str(tmp_path))
        content = "\n".join([IBKR_CASH_HEADER] + [IBKR_CASH_DIVIDEND] * 3).encode("utf-8")

        with pytest.raises(ValueError, match="mehr als"):
            await imp.analyze_csv_structure(content, "cash.csv", db, uuid.uuid4())

    async def test_generic_file_still_counts_every_row(self, db, monkeypatch, tmp_path):
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 2)
        monkeypatch.setattr(imp, "UPLOAD_DIR", str(tmp_path))
        rows = ["Date,Type,Ticker,Shares,Price,Currency,Total"] + ["2025-01-15,buy,AAA,1,10,CHF,10"] * 3

        with pytest.raises(ValueError, match="mehr als"):
            await imp.analyze_csv_structure("\n".join(rows).encode("utf-8"), "big.csv", db, uuid.uuid4())

    async def test_header_only_and_empty_files_behave_as_before(self, db, monkeypatch, tmp_path):
        monkeypatch.setattr(imp, "UPLOAD_DIR", str(tmp_path))
        analysis = await imp.analyze_csv_structure(
            b"Date,Type,Ticker,Shares,Price,Currency,Total\n", "head.csv", db, uuid.uuid4(),
        )
        assert analysis["row_count"] == 0
        assert analysis["headers"][0] == "Date"


# --- R-importtx-6: Reaktivierung neben einer aktiven Position -----------------

class TestReactivationNextToAnActiveTwin:
    async def test_recalculate_all_keeps_the_closed_position_inactive(self, db, caplog):
        user = await _make_user(db)
        closed = await _closed_position_with_ledger_shares(db, user.id)
        twin = await _make_position(db, user.id, ticker="DUPL", shares="5", cost="500")
        assert closed.bucket_id == twin.bucket_id

        with caplog.at_level(logging.WARNING, logger="services.recalculate_service"):
            results = await recalculate_all_positions(db, user_id=user.id)  # vorher: IntegrityError

        assert all("error" not in r for r in results)
        await db.refresh(closed)
        await db.refresh(twin)
        assert (float(closed.shares), closed.is_active) == (50.0, False)
        assert twin.is_active is True
        assert "inactive despite" in caplog.text

    async def test_recalculate_position_keeps_the_closed_position_inactive(self, db):
        user = await _make_user(db)
        closed = await _closed_position_with_ledger_shares(db, user.id)
        await _make_position(db, user.id, ticker="DUPL", shares="5", cost="500")

        await recalculate_position(db, closed.id)
        await db.commit()  # vorher: IntegrityError

        await db.refresh(closed)
        assert (float(closed.shares), closed.is_active) == (50.0, False)

    async def test_two_closed_twins_reactivate_only_one(self, db):
        user = await _make_user(db)
        first = await _closed_position_with_ledger_shares(db, user.id)
        second = await _closed_position_with_ledger_shares(db, user.id)

        await recalculate_all_positions(db, user_id=user.id)

        await db.refresh(first)
        await db.refresh(second)
        assert sorted([first.is_active, second.is_active]) == [False, True]

    async def test_without_twin_the_position_is_reactivated(self, db):
        """K041 bleibt behoben: Bestand aus dem Ledger macht die Position wieder aktiv."""
        user = await _make_user(db)
        closed = await _closed_position_with_ledger_shares(db, user.id)
        await _make_position(db, user.id, ticker="OTHER", shares="5", cost="500")

        await recalculate_all_positions(db, user_id=user.id)
        await db.refresh(closed)
        assert closed.is_active is True

        closed.is_active = False
        await db.commit()
        await recalculate_position(db, closed.id)
        await db.commit()
        await db.refresh(closed)
        assert closed.is_active is True

    async def test_twin_in_another_bucket_does_not_block(self, db):
        from services.bucket_service import create_bucket

        user = await _make_user(db)
        closed = await _closed_position_with_ledger_shares(db, user.id)
        other_bucket = await create_bucket(db, user.id, name="Zweiter Bucket")
        await db.commit()
        await _make_position(db, user.id, ticker="DUPL", shares="5", cost="500", bucket_id=other_bucket.id)

        await recalculate_all_positions(db, user_id=user.id)

        await db.refresh(closed)
        assert closed.is_active is True

    async def test_import_onto_the_closed_position_does_not_violate_the_index(self, db):
        user = await _make_user(db)
        closed = await _closed_position_with_ledger_shares(db, user.id)
        twin = await _make_position(db, user.id, ticker="DUPL", shares="5", cost="500")

        result = await imp.confirm_import(  # vorher: IntegrityError beim Commit
            [_import_txn(closed.id, date="2024-04-01", shares=10, price_per_share=10.0, total_chf=100.0)],
            [], db, user.id,
        )

        assert result["created_transactions"] == 1
        await db.refresh(closed)
        await db.refresh(twin)
        assert (float(closed.shares), closed.is_active) == (60.0, False)
        assert twin.is_active is True

    async def test_import_route_answers_201_in_the_legacy_state(self, client, db):
        headers = await _login(client, "w5-recalc@example.com")
        user_id = await _user_id(db, "w5-recalc@example.com")
        await _closed_position_with_ledger_shares(db, user_id)
        await _make_position(db, user_id, ticker="DUPL", shares="5", cost="500")

        res = await client.post(
            "/api/import/confirm", json={"transactions": [], "new_positions": []}, headers=headers,
        )

        assert res.status_code == 201, res.text  # vorher 500 «Import fehlgeschlagen»


# --- R-importtx-4: Pending Order auf eine importierte Position ----------------

def _order(**overrides) -> dict:
    base = {"ticker": "BRK B", "side": "sell", "shares": 2, "limit_price": 400.0,
            "currency": "USD", "expiry_type": "gtc"}
    base.update(overrides)
    return base


class TestOrderTickerOfAnExistingPosition:
    async def test_display_ticker_of_an_own_position_is_accepted_and_fills_it(self, client, db):
        headers = await _login(client, "w5-order@example.com")
        user_id = await _user_id(db, "w5-order@example.com")
        pos = await _make_position(
            db, user_id, ticker="BRK B", shares="10", cost="4000", currency="USD", yfinance_ticker="BRK-B",
        )
        db.add(_ledger_txn(pos, TransactionType.buy, 1, "10", "4000", currency="USD"))
        await db.commit()

        created = await client.post("/api/orders/pending", json=_order(ticker="brk b"), headers=headers)
        assert created.status_code == 201, created.text  # vorher 422
        assert created.json()["ticker"] == "BRK B"

        fill = await client.post(
            f"/api/orders/pending/{created.json()['id']}/fill",
            json={"price_per_share": 410.0, "fill_date": TODAY, "fx_rate_to_chf": 1.0},
            headers=headers,
        )
        assert fill.status_code == 200, fill.text
        positions = (await db.execute(select(Position).where(Position.user_id == user_id))).scalars().all()
        assert [p.ticker for p in positions] == ["BRK B"]  # keine neue Position «BRK-B»
        await db.refresh(pos)
        assert float(pos.shares) == 8

    async def test_ticker_of_a_foreign_position_is_rejected(self, client, db):
        other = await _make_user(db)
        await _make_position(db, other.id, ticker="BRK B", shares="10", cost="4000")
        headers = await _login(client, "w5-order-foreign@example.com")

        res = await client.post("/api/orders/pending", json=_order(), headers=headers)

        assert res.status_code == 422
        assert "Ticker" in res.json()["detail"]
        assert (await db.execute(select(PendingOrder))).scalars().all() == []

    @pytest.mark.parametrize("ticker", ["AAPL,MSFT", "AAPL MSFT", " AAPL", "   "])
    async def test_non_market_ticker_without_position_is_rejected(self, client, ticker):
        headers = await _login(client, "w5-order-bad@example.com")
        res = await client.post("/api/orders/pending", json=_order(ticker=ticker, side="buy"), headers=headers)
        assert res.status_code == 422

    async def test_market_ticker_without_position_is_still_accepted(self, client):
        headers = await _login(client, "w5-order-ok@example.com")
        res = await client.post("/api/orders/pending", json=_order(ticker="nesn.sw", side="buy"), headers=headers)
        assert res.status_code == 201, res.text
        assert res.json()["ticker"] == "NESN.SW"
