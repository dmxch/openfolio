"""Review-Fixes Batch G (Code-Review 2026-07-02) — Import-Pfad.

Gepinnte Fixes:
  - M7  ibkr_parser: mehrere Dividenden pro (Symbol, Tag) bleiben erhalten
        (Listen statt Einzel-Slot); IBKR-Reversals (negative Beträge) werden
        NICHT mehr via abs() zu positiven Dividenden geflippt, sondern mit
        Warnung übersprungen (Confirm-API akzeptiert keine negativen Beträge).
  - M8  swissquote_parser: "Zinsen auf Belastungen" (Soll-/Margin-Zins) ist
        ein Aufwand und mappt auf fee statt interest.
  - M14 confirm_import: FX-Transaktionen sind idempotent — Dedup über
        (user_id, order_id) bzw. (user_id, date, Währungspaar, Betrag).
  - M31 Duplikat-Checks sind gebatcht (Sets statt EXISTS pro Zeile) und
        erkennen jetzt auch Intra-File-Duplikate in Preview UND Confirm.
  - LOW _auto_assign_industries läuft als Background-Task (eigene Session,
        starke Task-Referenz) und nutzt den yf_patch-Wrapper statt rohem
        yf.Ticker(t).info.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

import services.import_service as imp
import services.swissquote_parser as sq
from models.fx_transaction import FxTransaction
from models.position import AssetType, Position, PriceSource
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_system_buckets, get_liquid_default_bucket
from services.ibkr_parser import parse_ibkr_csv
from services.import_service import ParsedTransaction
from services.swissquote_parser import _map_type, parse_swissquote_csv

pytestmark = pytest.mark.asyncio


# --- Helpers ----------------------------------------------------------------

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


def _parsed(ticker="DUPP", **over) -> ParsedTransaction:
    base = dict(
        row_index=2,
        type="buy",
        date="2025-01-15",
        ticker=ticker,
        shares=10,
        price_per_share=150.0,
        currency="CHF",
        fx_rate_to_chf=1.0,
        total_chf=1500.0,
    )
    base.update(over)
    return ParsedTransaction(**base)


# --- M7: IBKR Cash — mehrere Dividenden pro Tag + Reversals ------------------

IBKR_CASH_HEADER = (
    "ClientAccountID,CurrencyPrimary,FXRateToBase,Symbol,ISIN,ListingExchange,"
    "Date/Time,SettleDate,Amount,Type,Description"
)

_DIV_DESC = "VT(US9220427424) CASH DIVIDEND USD 0.85 PER SHARE (Ordinary Dividend)"
_DIV_TAX_DESC = "VT(US9220427424) CASH DIVIDEND USD 0.85 PER SHARE - US TAX"
_PIL_DESC = "VT(US9220427424) PAYMENT IN LIEU OF DIVIDEND (Payment In Lieu Of Dividend)"
_PIL_TAX_DESC = "VT(US9220427424) PAYMENT IN LIEU OF DIVIDEND - US TAX"
_DIV90_DESC = "VT(US9220427424) CASH DIVIDEND USD 0.90 PER SHARE (Ordinary Dividend)"
_DIV90_TAX_DESC = "VT(US9220427424) CASH DIVIDEND USD 0.90 PER SHARE - US TAX"

IBKR_CASH_TWO_DIVIDENDS_SAME_DAY = f"""{IBKR_CASH_HEADER}
U111,USD,0.88,VT,US9220427424,ARCA,20240315;093000,20240318,85.00,Dividends,{_DIV_DESC}
U111,USD,0.88,VT,US9220427424,ARCA,20240315;093000,20240318,10.00,Payment In Lieu Of Dividends,{_PIL_DESC}
U111,USD,0.88,VT,US9220427424,ARCA,20240315;093000,20240318,-12.75,Withholding Tax,{_DIV_TAX_DESC}
U111,USD,0.88,VT,US9220427424,ARCA,20240315;093000,20240318,-1.50,Withholding Tax,{_PIL_TAX_DESC}
"""

IBKR_CASH_ONE_TO_ONE = f"""{IBKR_CASH_HEADER}
U111,USD,0.9,VT,US9220427424,ARCA,20240315;093000,20240318,100.00,Dividends,{_DIV_DESC}
U111,USD,0.9,VT,US9220427424,ARCA,20240315;093000,20240318,-15.00,Withholding Tax,{_DIV_TAX_DESC}
"""

IBKR_CASH_ONE_DIV_TWO_TAXES = f"""{IBKR_CASH_HEADER}
U111,USD,0.9,VT,US9220427424,ARCA,20240315;093000,20240318,100.00,Dividends,{_DIV_DESC}
U111,USD,0.9,VT,US9220427424,ARCA,20240315;093000,20240318,-10.00,Withholding Tax,{_DIV_TAX_DESC}
U111,USD,0.9,VT,US9220427424,ARCA,20240315;093000,20240318,-5.00,Withholding Tax,{_DIV_TAX_DESC}
"""

IBKR_CASH_REVERSAL = f"""{IBKR_CASH_HEADER}
U111,USD,0.88,VT,US9220427424,ARCA,20240315;093000,20240318,-85.00,Dividends,{_DIV_DESC}
U111,USD,0.88,VT,US9220427424,ARCA,20240315;093000,20240318,12.75,Withholding Tax,{_DIV_TAX_DESC}
"""

IBKR_CASH_REVERSAL_PLUS_REBOOK = f"""{IBKR_CASH_HEADER}
U111,USD,0.88,VT,US9220427424,ARCA,20240315;093000,20240318,-85.00,Dividends,{_DIV_DESC}
U111,USD,0.88,VT,US9220427424,ARCA,20240315;093000,20240318,90.00,Dividends,{_DIV90_DESC}
U111,USD,0.88,VT,US9220427424,ARCA,20240315;093000,20240318,12.75,Withholding Tax,{_DIV_TAX_DESC}
U111,USD,0.88,VT,US9220427424,ARCA,20240315;093000,20240318,-13.50,Withholding Tax,{_DIV90_TAX_DESC}
"""


class TestIbkrMultipleDividendsPerDay:
    async def test_two_dividends_same_day_both_kept(self, db):
        """M7: 'Dividends' + 'Payment In Lieu' am selben Tag = ZWEI Transaktionen."""
        result = await parse_ibkr_csv(IBKR_CASH_TWO_DIVIDENDS_SAME_DAY, "t.csv", db)
        assert result.total_rows == 2
        by_gross = {t.gross_amount: t for t in result.transactions}
        assert set(by_gross) == {85.0, 10.0}

        div = by_gross[85.0]
        assert div.tax_amount == 12.75
        assert div.total_chf == round((85.0 - 12.75) * 0.88, 2)
        assert div.taxes_chf == round(12.75 * 0.88, 2)

        pil = by_gross[10.0]
        assert pil.tax_amount == 1.5
        assert pil.total_chf == round((10.0 - 1.5) * 0.88, 2)

        assert result.broker_meta["dividends_count"] == 2

    async def test_one_to_one_behavior_unchanged(self, db):
        """M7: 1 Dividende + 1 Steuerzeile — exakt das bisherige Verhalten."""
        result = await parse_ibkr_csv(IBKR_CASH_ONE_TO_ONE, "t.csv", db)
        assert result.total_rows == 1
        txn = result.transactions[0]
        assert txn.type == "dividend"
        assert txn.ticker == "VT"
        assert txn.currency == "USD"
        assert txn.shares == 0
        assert txn.gross_amount == 100.0
        assert txn.tax_amount == 15.0
        assert txn.taxes_chf == round(15.0 * 0.9, 2)
        assert txn.total_chf == round(85.0 * 0.9, 2)

    async def test_two_tax_rows_are_summed(self, db):
        """M7: mehrere Steuerzeilen zur selben Dividende werden summiert
        (vorher überschrieb die zweite die erste)."""
        result = await parse_ibkr_csv(IBKR_CASH_ONE_DIV_TWO_TAXES, "t.csv", db)
        assert result.total_rows == 1
        txn = result.transactions[0]
        assert txn.gross_amount == 100.0
        assert txn.tax_amount == 15.0
        assert txn.total_chf == round(85.0 * 0.9, 2)


class TestIbkrDividendReversal:
    async def test_reversal_is_skipped_with_warning(self, db):
        """M7: negative Dividende (Reversal) wird NICHT via abs() positiv
        importiert, sondern mit Warnung übersprungen."""
        result = await parse_ibkr_csv(IBKR_CASH_REVERSAL, "t.csv", db)
        assert result.total_rows == 0
        assert result.transactions == []
        assert any("Storno" in w or "Reversal" in w for w in result.warnings)
        assert result.broker_meta["skipped"].get("reversal") == 1

    async def test_reversal_plus_rebooking_same_day(self, db):
        """M7: Storno + Neubuchung am selben Tag — die Neubuchung überlebt
        mit IHRER Steuerzeile (Description-Matching), der Storno fällt raus."""
        result = await parse_ibkr_csv(IBKR_CASH_REVERSAL_PLUS_REBOOK, "t.csv", db)
        assert result.total_rows == 1
        txn = result.transactions[0]
        assert txn.gross_amount == 90.0
        assert txn.tax_amount == 13.5
        assert txn.total_chf == round((90.0 - 13.5) * 0.88, 2)
        assert any("Storno" in w or "Reversal" in w for w in result.warnings)


# --- M8: Swissquote Soll-Zinsen ----------------------------------------------

SQ_HEADER = (
    "Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;"
    "Aufgelaufene Zinsen;Nettobetrag;Währung Nettobetrag;"
    "Nettobetrag in Kontowährung;Saldo;Währung"
)

SQ_CSV_INTEREST_MIXED = f"""{SQ_HEADER}
15-03-2024 10:00:00;00000000;Zinsen auf Belastungen;;;;;;;;-12.50;CHF;-12.50;9987.50;CHF
16-03-2024 10:00:00;00000000;Zinsen;;;;;;;;3.20;CHF;3.20;10000.00;CHF
"""


class TestSwissquoteDebitInterest:
    def test_map_type_debit_interest_is_fee(self):
        """M8: Soll-Zinsen (Aufwand) mappen auf fee, nicht interest."""
        assert _map_type("Zinsen auf Belastungen") == "fee"
        assert _map_type("Sollzinsen") == "fee"

    def test_map_type_credit_interest_stays_interest(self):
        assert _map_type("Zinsen") == "interest"
        assert _map_type("Zinsen auf Guthaben") == "interest"

    async def test_parse_debit_interest_row_as_fee(self, db, monkeypatch):
        """M8: 'Zinsen auf Belastungen' landet als fee (Aufwand, wird in
        total_return abgezogen) — nicht als positiver interest-Ertrag."""
        monkeypatch.setattr(sq, "get_fx_rates_batch", lambda: {"CHF": 1.0, "USD": 0.88})
        result = await parse_swissquote_csv(SQ_CSV_INTEREST_MIXED, "t.csv", db)
        by_type = {t.type: t for t in result.transactions}
        assert set(by_type) == {"fee", "interest"}
        assert by_type["fee"].total_chf == 12.50
        assert by_type["fee"].notes == "Zinsen auf Belastungen"
        assert by_type["interest"].total_chf == 3.20


# --- M14: FX-Transaktionen idempotent ----------------------------------------

def _fx(order_id="FX-1", **over) -> dict:
    base = {
        "date": "2026-02-27",
        "order_id": order_id,
        "currency_from": "CHF",
        "currency_to": "USD",
        "amount_from": 9982.64,
        "amount_to": 12866.32,
        "rate": 0.775874,
        "import_batch_id": "b1",
    }
    base.update(over)
    return base


class TestFxTransactionIdempotency:
    async def test_second_import_creates_no_fx_duplicates(self, db):
        """M14: zweiter Import derselben CSV → 0 neue FxTransactions."""
        user = await _make_user(db)
        fx_rows = [_fx("FX-1"), _fx(None, currency_to="EUR", amount_to=10500.0)]

        res1 = await imp.confirm_import([], [], db, user.id, fx_transactions=fx_rows)
        assert res1["created_fx_transactions"] == 2

        res2 = await imp.confirm_import([], [], db, user.id, fx_transactions=fx_rows)
        assert res2["created_fx_transactions"] == 0
        assert res2["skipped_fx_duplicates"] == 2

        count = len((await db.execute(
            select(FxTransaction).where(FxTransaction.user_id == user.id)
        )).scalars().all())
        assert count == 2

    async def test_intra_batch_fx_duplicate_skipped(self, db):
        user = await _make_user(db)
        res = await imp.confirm_import(
            [], [], db, user.id, fx_transactions=[_fx("FX-9"), _fx("FX-9")]
        )
        assert res["created_fx_transactions"] == 1
        assert res["skipped_fx_duplicates"] == 1

    async def test_same_day_different_amounts_both_created(self, db):
        """Zwei legitime FX-Wechsel am selben Tag (andere Beträge, keine
        order_id) sind KEINE Duplikate."""
        user = await _make_user(db)
        res = await imp.confirm_import(
            [], [], db, user.id,
            fx_transactions=[
                _fx(None, amount_from=1000.0, amount_to=1130.0),
                _fx(None, amount_from=2000.0, amount_to=2260.0),
            ],
        )
        assert res["created_fx_transactions"] == 2
        assert res["skipped_fx_duplicates"] == 0

    async def test_fx_user_scoped(self, db):
        """Gleiche FX-Row eines ANDEREN Users blockt den Import nicht."""
        user_a = await _make_user(db)
        user_b = await _make_user(db)
        await imp.confirm_import([], [], db, user_a.id, fx_transactions=[_fx("FX-2")])
        res = await imp.confirm_import([], [], db, user_b.id, fx_transactions=[_fx("FX-2")])
        assert res["created_fx_transactions"] == 1


# --- M31: gebatchte Duplikat-Checks ------------------------------------------

class TestBatchedDuplicateChecks:
    async def test_confirm_reimport_is_idempotent(self, db):
        """Zweiter Confirm-Lauf derselben Datei → 0 neue Transaktionen."""
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="IDEM")

        res1 = await imp.confirm_import([_txn(pos.id)], [], db, user.id)
        assert res1["created_transactions"] == 1

        res2 = await imp.confirm_import([_txn(pos.id)], [], db, user.id)
        assert res2["created_transactions"] == 0
        assert res2["skipped_duplicates"] == 1

    async def test_confirm_intra_file_duplicate_skipped(self, db):
        """Intra-File-Duplikat: zwei identische Zeilen in EINEM Confirm-Lauf
        erzeugen nur eine Transaktion (Behavior-Change ggü. vorher)."""
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="INTRA")

        res = await imp.confirm_import([_txn(pos.id), _txn(pos.id)], [], db, user.id)
        assert res["created_transactions"] == 1
        assert res["skipped_duplicates"] == 1

        rows = (await db.execute(
            select(Transaction).where(Transaction.position_id == pos.id)
        )).scalars().all()
        assert len(rows) == 1

    async def test_confirm_order_id_duplicate_skipped(self, db):
        """order_id-Dedup greift auch bei abweichendem Betrag/Datum."""
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="ORD")
        db.add(Transaction(
            position_id=pos.id, user_id=user.id, type=TransactionType.buy,
            date=date(2025, 1, 15), shares=Decimal("10"), price_per_share=Decimal("150"),
            currency="CHF", fx_rate_to_chf=Decimal("1"), total_chf=Decimal("1500"),
            order_id="SQ-99",
        ))
        await db.commit()

        res = await imp.confirm_import(
            [_txn(pos.id, order_id="SQ-99", date="2025-02-01",
                  shares=1, price_per_share=999.0, total_chf=999.0)],
            [], db, user.id,
        )
        assert res["created_transactions"] == 0
        assert res["skipped_duplicates"] == 1

    async def test_force_import_still_overrides_batched_dedup(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="FORC")
        res = await imp.confirm_import(
            [_txn(pos.id), _txn(pos.id, force_import=True)], [], db, user.id,
        )
        assert res["created_transactions"] == 2

    async def test_preview_exact_duplicate_flagged_from_db(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="DUPP")
        db.add(Transaction(
            position_id=pos.id, user_id=user.id, type=TransactionType.buy,
            date=date(2025, 1, 15), shares=Decimal("10"), price_per_share=Decimal("150"),
            currency="CHF", fx_rate_to_chf=Decimal("1"), total_chf=Decimal("1500"),
        ))
        await db.commit()

        txns, _ = await imp.enrich_transactions([_parsed("DUPP")], db, user_id=user.id)
        assert txns[0].is_duplicate is True

    async def test_preview_partial_duplicate_warns(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="PART")
        db.add(Transaction(
            position_id=pos.id, user_id=user.id, type=TransactionType.buy,
            date=date(2025, 1, 15), shares=Decimal("5"), price_per_share=Decimal("100"),
            currency="CHF", fx_rate_to_chf=Decimal("1"), total_chf=Decimal("999"),
        ))
        await db.commit()

        txns, _ = await imp.enrich_transactions([_parsed("PART")], db, user_id=user.id)
        assert txns[0].is_duplicate is False
        assert any("Ähnliche Transaktion" in w for w in txns[0].warnings)

    async def test_preview_intra_file_duplicate_flagged(self, db):
        """Intra-File: zweite identische Zeile derselben Datei wird schon in
        der Preview als Duplikat markiert."""
        user = await _make_user(db)
        await _make_position(db, user, ticker="TWIN")

        txns, _ = await imp.enrich_transactions(
            [_parsed("TWIN"), _parsed("TWIN")], db, user_id=user.id,
        )
        assert txns[0].is_duplicate is False
        assert txns[1].is_duplicate is True

    async def test_preview_order_id_duplicate_flagged(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="OIDP")
        db.add(Transaction(
            position_id=pos.id, user_id=user.id, type=TransactionType.buy,
            date=date(2025, 1, 15), shares=Decimal("10"), price_per_share=Decimal("150"),
            currency="CHF", fx_rate_to_chf=Decimal("1"), total_chf=Decimal("1500"),
            order_id="SQ-7",
        ))
        await db.commit()

        txns, _ = await imp.enrich_transactions(
            [_parsed("OIDP", order_id="SQ-7", date="2025-03-01", total_chf=777.0)],
            db, user_id=user.id,
        )
        assert txns[0].is_duplicate is True


# --- LOW: Industry-Enrichment im Hintergrund + yf-Wrapper ---------------------

class TestIndustryEnrichment:
    async def test_confirm_runs_industry_enrichment_in_background(self, db, monkeypatch):
        """Confirm kehrt zurück ohne das Enrichment zu awaiten; der
        Background-Task lädt die Positionen mit eigener Session."""
        recorded: list[list[str]] = []

        async def _recorder(bg_db, positions):
            assert bg_db is not db  # eigene Session, nicht die Request-Session
            recorded.append(sorted(p.ticker for p in positions))

        monkeypatch.setattr(imp, "_auto_assign_industries", _recorder)

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

        pending = list(imp._industry_bg_tasks)
        if pending:
            await asyncio.wait(pending, timeout=5)
        assert recorded == [["MSFT"]]

    async def test_auto_assign_industries_uses_yf_wrapper(self, db, monkeypatch):
        """Der rohe yf.Ticker(t).info-Call ist durch yf_patch.yf_ticker_attr
        ersetzt (Thread-Safety + korrekter User-Agent)."""
        import yf_patch

        calls: list[tuple[str, str]] = []

        def _fake_ticker_attr(ticker: str, attr: str):
            calls.append((ticker, attr))
            return {"industry": "Test Industry", "sector": "Technology"}

        monkeypatch.setattr(yf_patch, "yf_ticker_attr", _fake_ticker_attr)

        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="NVDA")

        await imp._auto_assign_industries(db, [pos])

        assert calls == [("NVDA", "info")]
        assert pos.industry == "Test Industry"
        # Unbekannte Industry → Fallback auf den yfinance-Sector
        assert pos.sector == "Technology"
