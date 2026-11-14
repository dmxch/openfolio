"""Vollreview 11/2026 — GS04: ``scripts/reattribute_bucket_at_sale.py`` arbeitet
nur noch auf den Daten EINES Nutzers.

Das Skript liegt ausserhalb von ``backend/``. Im Test-Container ist es nur
sichtbar, wenn ``./scripts`` nach ``/scripts`` gemountet ist; sonst werden die
Tests uebersprungen.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from models.position import AssetType, Position, PriceSource, PricingMode
from models.transaction import Transaction, TransactionType
from models.user import User
from services.bucket_service import create_bucket, create_system_buckets

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "reattribute_bucket_at_sale.py"

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not _SCRIPT.is_file(),
        reason=f"{_SCRIPT} nicht sichtbar (./scripts ist nicht in den Container gemountet)",
    ),
]


def _load_script():
    spec = importlib.util.spec_from_file_location("vr11_reattribute_bucket_at_sale", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _user_with_moved_sale(db, ticker: str) -> tuple[User, Transaction, uuid.UUID, uuid.UUID]:
    """Nutzer mit einem Verkauf im Bucket «Alt», dessen Position heute in «Neu» liegt."""
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await create_system_buckets(db, user.id)
    old_bucket = await create_bucket(db, user.id, name="Alt")
    new_bucket = await create_bucket(db, user.id, name="Neu")
    await db.commit()

    pos = Position(
        user_id=user.id,
        bucket_id=new_bucket.id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="USD",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=0,
        cost_basis_chf=0,
    )
    db.add(pos)
    await db.commit()

    sale = Transaction(
        user_id=user.id,
        position_id=pos.id,
        type=TransactionType.sell,
        date=date(2025, 3, 10),
        shares=Decimal("1"),
        price_per_share=Decimal("100"),
        currency="USD",
        fx_rate_to_chf=Decimal("1"),
        fees_chf=Decimal("0"),
        taxes_chf=Decimal("0"),
        total_chf=Decimal("100"),
        cost_basis_at_sale=Decimal("80"),
        realized_pnl_chf=Decimal("20"),
        realized_pnl=Decimal("20"),
        bucket_id_at_sale=old_bucket.id,
    )
    db.add(sale)
    await db.commit()
    return user, sale, old_bucket.id, new_bucket.id


async def _bucket_at_sale(db, txn_id) -> uuid.UUID:
    row = await db.execute(
        select(Transaction.bucket_id_at_sale)
        .where(Transaction.id == txn_id)
        .execution_options(populate_existing=True)
    )
    return row.scalar_one()


async def test_apply_changes_only_the_named_user(db, capsys):
    module = _load_script()
    target, target_sale, target_old, target_new = await _user_with_moved_sale(db, "AAA")
    other, other_sale, other_old, _ = await _user_with_moved_sale(db, "ZZZ")

    assert await module.main(["--user", target.email.upper(), "--apply"]) == 0

    assert await _bucket_at_sale(db, target_sale.id) == target_new
    # Frueher wanderte auch der Verkauf des anderen Nutzers in dessen heutigen Bucket.
    assert await _bucket_at_sale(db, other_sale.id) == other_old

    out = capsys.readouterr().out
    assert "ZZZ" not in out and other.email not in out
    assert target.email in out


async def test_old_values_are_printed_as_csv_before_the_write(db, capsys):
    module = _load_script()
    target, sale, old_bucket, new_bucket = await _user_with_moved_sale(db, "AAA")

    assert await module.main(["--user", str(target.id), "--apply"]) == 0

    out = capsys.readouterr().out
    block = out.split("--- CSV alte Werte: Anfang ---\n", 1)[1].split("--- CSV alte Werte: Ende ---", 1)[0]
    rows = list(csv.DictReader(io.StringIO(block)))
    assert rows == [
        {
            "transaction_id": str(sale.id),
            "user_id": str(target.id),
            "position_id": str(sale.position_id),
            "ticker": "AAA",
            "date": "2025-03-10",
            "realized_pnl_chf": "20.00",
            "bucket_id_at_sale_old": str(old_bucket),
            "bucket_id_at_sale_new": str(new_bucket),
        }
    ]
    assert out.index("CSV alte Werte: Ende") < out.index("[APPLY]")


async def test_dry_run_is_default_and_writes_nothing(db, capsys):
    module = _load_script()
    target, sale, old_bucket, _ = await _user_with_moved_sale(db, "AAA")

    assert await module.main(["--user", target.email]) == 0

    assert await _bucket_at_sale(db, sale.id) == old_bucket
    assert "[DRY-RUN]" in capsys.readouterr().out


async def test_user_is_mandatory(db):
    module = _load_script()
    _, sale, old_bucket, _ = await _user_with_moved_sale(db, "AAA")

    with pytest.raises(SystemExit) as exc:
        await module.main(["--apply"])

    assert exc.value.code == 2
    assert await _bucket_at_sale(db, sale.id) == old_bucket


async def test_unknown_user_changes_nothing(db, capsys):
    module = _load_script()
    _, sale, old_bucket, _ = await _user_with_moved_sale(db, "AAA")

    assert await module.main(["--user", "niemand@test.local", "--apply"]) == 1
    assert await module.main(["--user", str(uuid.uuid4()), "--apply"]) == 1

    assert await _bucket_at_sale(db, sale.id) == old_bucket
    assert "Nichts geändert" in capsys.readouterr().err
