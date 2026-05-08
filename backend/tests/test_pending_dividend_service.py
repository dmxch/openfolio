"""Unit tests for pending_dividend_service.

Covers:
- _reconstruct_shares_at_date (read-only share rebuilding from txn history)
- resolve_withholding (3-level resolution: position override > ISIN map > user default)
- try_auto_match_transaction (35d window, nearest ex_date)
- unmatch_on_transaction_delete
- dismiss persistence (no Worker-recreation under UNIQUE + existence-check)

yfinance-driven detection paths (`_detect_for_position`) are NOT covered here —
they require multi-step yf_download mocking and are noted as TODO.
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from models.pending_dividend import (
    PendingDividend,
    STATUS_CONFIRMED,
    STATUS_DISMISSED,
    STATUS_PENDING,
)
from models.position import AssetType, Position, PriceSource, PricingMode
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.auth_service import hash_password
from services.pending_dividend_service import (
    DIVIDEND_MATCH_WINDOW_DAYS,
    _reconstruct_shares_at_date,
    resolve_withholding,
    try_auto_match_transaction,
    unmatch_on_transaction_delete,
)


# pytest-asyncio is in 'auto' mode (see pytest.ini): async tests get marked
# automatically. Sync tests stay sync — no global asyncio mark needed.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _txn(
    txn_type: TransactionType,
    txn_date: date,
    shares: float,
    *,
    created_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        type=txn_type,
        date=txn_date,
        shares=shares,
        created_at=created_at or datetime(2026, 1, 1, 0, 0, 0),
    )


async def _make_user(db, email: str = "u@example.com") -> User:
    user = User(email=email, password_hash=hash_password("TestPass1"))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_position(
    db,
    user_id: uuid.UUID,
    *,
    ticker: str = "AAPL",
    name: str = "Apple",
    isin: str | None = None,
    withholding_pct: Decimal | None = None,
) -> Position:
    pos = Position(
        user_id=user_id,
        ticker=ticker,
        name=name,
        type=AssetType.stock,
        currency="USD",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        gold_org=False,
        is_etf=False,
        is_active=True,
        shares=100,
        cost_basis_chf=10000,
        isin=isin,
        dividend_withholding_pct=withholding_pct,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


async def _make_transaction(
    db,
    user_id: uuid.UUID,
    position_id: uuid.UUID,
    *,
    txn_type: TransactionType = TransactionType.dividend,
    txn_date: date,
    shares: float = 0,
    total_chf: float = 0,
) -> Transaction:
    txn = Transaction(
        user_id=user_id,
        position_id=position_id,
        type=txn_type,
        date=txn_date,
        shares=shares,
        price_per_share=0,
        currency="USD",
        fx_rate_to_chf=1.0,
        total_chf=total_chf,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn


async def _make_pending(
    db,
    user_id: uuid.UUID,
    position_id: uuid.UUID,
    *,
    ex_date: date,
    status: str = STATUS_PENDING,
    matched_transaction_id: uuid.UUID | None = None,
    dps: float = 0.5,
) -> PendingDividend:
    pending = PendingDividend(
        user_id=user_id,
        position_id=position_id,
        ex_date=ex_date,
        dividend_per_share=Decimal(str(dps)),
        currency="USD",
        shares_at_ex_date=Decimal("100"),
        expected_gross_chf=Decimal("50.00"),
        status=status,
        matched_transaction_id=matched_transaction_id,
    )
    db.add(pending)
    await db.commit()
    await db.refresh(pending)
    return pending


# ---------------------------------------------------------------------------
# _reconstruct_shares_at_date
# ---------------------------------------------------------------------------


class TestReconstructSharesAtDate:
    def test_buy_only(self):
        txns = [_txn(TransactionType.buy, date(2025, 1, 1), 100)]
        assert _reconstruct_shares_at_date(txns, date(2025, 6, 1)) == 100.0

    def test_partial_sell(self):
        txns = [
            _txn(TransactionType.buy, date(2025, 1, 1), 100),
            _txn(TransactionType.sell, date(2025, 3, 1), 40),
        ]
        assert _reconstruct_shares_at_date(txns, date(2025, 6, 1)) == 60.0

    def test_zero_at_exdate_position_acquired_after(self):
        txns = [_txn(TransactionType.buy, date(2025, 7, 1), 100)]
        assert _reconstruct_shares_at_date(txns, date(2025, 6, 1)) == 0.0

    def test_fully_sold_before_exdate(self):
        txns = [
            _txn(TransactionType.buy, date(2025, 1, 1), 100),
            _txn(TransactionType.sell, date(2025, 4, 1), 100),
        ]
        assert _reconstruct_shares_at_date(txns, date(2025, 6, 1)) == 0.0

    def test_delivery_in_only(self):
        # Broker-Uebertrag ohne expliziten Buy — wird wie buy behandelt.
        txns = [_txn(TransactionType.delivery_in, date(2025, 1, 1), 50)]
        assert _reconstruct_shares_at_date(txns, date(2025, 6, 1)) == 50.0


# ---------------------------------------------------------------------------
# resolve_withholding
# ---------------------------------------------------------------------------


def _settings(default: float = 0.35) -> SimpleNamespace:
    return SimpleNamespace(dividend_withholding_default=Decimal(str(default)))


def _pos(*, isin: str | None = None, override: float | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        isin=isin,
        dividend_withholding_pct=Decimal(str(override)) if override is not None else None,
    )


class TestResolveWithholding:
    def test_position_override_wins(self):
        pos = _pos(isin="US0378331005", override=0.10)
        assert resolve_withholding(pos, _settings(0.35)) == pytest.approx(0.10)

    def test_isin_us(self):
        pos = _pos(isin="US0378331005")
        assert resolve_withholding(pos, _settings(0.35)) == pytest.approx(0.15)

    def test_isin_ch(self):
        pos = _pos(isin="CH0038863350")
        assert resolve_withholding(pos, _settings(0.20)) == pytest.approx(0.35)

    def test_isin_ie_ucits(self):
        pos = _pos(isin="IE00B4L5Y983")
        assert resolve_withholding(pos, _settings(0.35)) == pytest.approx(0.0)

    def test_no_isin_falls_back_to_user_default(self):
        pos = _pos(isin=None)
        assert resolve_withholding(pos, _settings(0.27)) == pytest.approx(0.27)

    def test_unknown_country_falls_back_to_user_default(self):
        # ZA is not in WITHHOLDING_BY_COUNTRY → fallback to user default.
        pos = _pos(isin="ZA0001000000")
        assert resolve_withholding(pos, _settings(0.30)) == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# try_auto_match_transaction
# ---------------------------------------------------------------------------


class TestAutoMatch:
    async def test_match_within_35_days(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user.id)
        ex = date(2025, 5, 1)
        await _make_pending(db, user.id, pos.id, ex_date=ex)

        txn = await _make_transaction(
            db,
            user.id,
            pos.id,
            txn_type=TransactionType.dividend,
            txn_date=ex + timedelta(days=30),
        )
        result = await try_auto_match_transaction(db, txn, user.id)

        assert result is not None
        assert result.status == STATUS_CONFIRMED
        assert result.matched_transaction_id == txn.id

    async def test_no_match_outside_35_days(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user.id)
        ex = date(2025, 5, 1)
        await _make_pending(db, user.id, pos.id, ex_date=ex)

        txn = await _make_transaction(
            db,
            user.id,
            pos.id,
            txn_type=TransactionType.dividend,
            txn_date=ex + timedelta(days=DIVIDEND_MATCH_WINDOW_DAYS + 5),
        )
        result = await try_auto_match_transaction(db, txn, user.id)
        assert result is None

    @pytest.mark.skip(
        reason=(
            "ORDER BY abs(date - date) is PG-specific; SQLite returns 0 for "
            "date subtraction so ordering is non-deterministic. Covered by "
            "the live smoke-test against Postgres."
        )
    )
    async def test_picks_nearest_ex_date(self, db):
        user = await _make_user(db, email="reit@example.com")
        pos = await _make_position(db, user.id, ticker="O", name="Realty Income")
        # Two monthly REIT pendings, txn nearer to the second one.
        ex1 = date(2025, 5, 1)
        ex2 = date(2025, 6, 1)
        p1 = await _make_pending(db, user.id, pos.id, ex_date=ex1)
        p2 = await _make_pending(db, user.id, pos.id, ex_date=ex2)

        txn = await _make_transaction(
            db,
            user.id,
            pos.id,
            txn_type=TransactionType.dividend,
            txn_date=date(2025, 6, 5),  # 35 days from ex1, 4 days from ex2
        )
        result = await try_auto_match_transaction(db, txn, user.id)

        assert result is not None
        assert result.id == p2.id
        assert result.status == STATUS_CONFIRMED
        # First pending stays untouched.
        await db.refresh(p1)
        assert p1.status == STATUS_PENDING

    async def test_non_dividend_transaction_skipped(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user.id)
        ex = date(2025, 5, 1)
        await _make_pending(db, user.id, pos.id, ex_date=ex)

        txn = await _make_transaction(
            db,
            user.id,
            pos.id,
            txn_type=TransactionType.buy,
            txn_date=ex + timedelta(days=10),
            shares=10,
            total_chf=1000,
        )
        result = await try_auto_match_transaction(db, txn, user.id)
        assert result is None


# ---------------------------------------------------------------------------
# unmatch_on_transaction_delete
# ---------------------------------------------------------------------------


class TestUnmatchOnTransactionDelete:
    async def test_unmatch_resets_to_pending(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user.id)
        ex = date(2025, 5, 1)

        txn = await _make_transaction(
            db,
            user.id,
            pos.id,
            txn_type=TransactionType.dividend,
            txn_date=ex,
        )
        await _make_pending(
            db,
            user.id,
            pos.id,
            ex_date=ex,
            status=STATUS_CONFIRMED,
            matched_transaction_id=txn.id,
        )

        count = await unmatch_on_transaction_delete(db, txn.id, user.id)
        assert count == 1

        # Re-query: status was reset, FK SET NULL is owned by the DB and
        # is not exercised in this in-memory test (the test asserts the
        # service's status-flip behavior).
        from sqlalchemy import select
        result = await db.execute(
            select(PendingDividend).where(PendingDividend.user_id == user.id)
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].status == STATUS_PENDING

    async def test_unmatch_skips_dismissed(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user.id)
        ex = date(2025, 5, 1)
        txn = await _make_transaction(
            db,
            user.id,
            pos.id,
            txn_type=TransactionType.dividend,
            txn_date=ex,
        )
        # Edge — direkt-DB-Manipulation: dismissed-Pending haengt am Txn.
        await _make_pending(
            db,
            user.id,
            pos.id,
            ex_date=ex,
            status=STATUS_DISMISSED,
            matched_transaction_id=txn.id,
        )

        count = await unmatch_on_transaction_delete(db, txn.id, user.id)
        assert count == 0


# ---------------------------------------------------------------------------
# Dismiss persistence (Worker would not recreate)
# ---------------------------------------------------------------------------


class TestDismissPersistence:
    async def test_dismissed_row_blocks_recreation(self, db):
        """Worker re-runs the existence-check before INSERT; even if it
        somehow tried to insert, the UNIQUE(user_id, position_id, ex_date)
        constraint would reject it.
        """
        user = await _make_user(db)
        pos = await _make_position(db, user.id)
        ex = date(2025, 5, 1)

        await _make_pending(
            db,
            user.id,
            pos.id,
            ex_date=ex,
            status=STATUS_DISMISSED,
            dps=0.5,
        )

        from sqlalchemy import select
        existing = await db.execute(
            select(PendingDividend).where(
                PendingDividend.user_id == user.id,
                PendingDividend.position_id == pos.id,
                PendingDividend.ex_date == ex,
            )
        )
        assert existing.scalars().first() is not None

        # Attempt a second insert with same (user, position, ex_date) — UNIQUE blocks it.
        from sqlalchemy.exc import IntegrityError
        dup = PendingDividend(
            user_id=user.id,
            position_id=pos.id,
            ex_date=ex,
            dividend_per_share=Decimal("0.5"),
            currency="USD",
            shares_at_ex_date=Decimal("100"),
            expected_gross_chf=Decimal("50.00"),
            status=STATUS_PENDING,
        )
        db.add(dup)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


# ---------------------------------------------------------------------------
# TODO: Initial-Seeding-Period-Selection (90d → period="3mo", rolling 35d → "2mo")
# Requires a yf_download mock returning a pandas DataFrame with multi-index
# columns. Skipped here for cost — covered by the live smoke-test in the plan.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="requires yf_download mock — covered by smoke-test")
async def test_initial_seeding_90d_then_rolling_35d():
    pass
