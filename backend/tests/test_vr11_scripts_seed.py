"""Vollreview 11/2026 — Seed-Skripte.

- GS14: ``seed.py`` schreibt nur in ein ausdruecklich genanntes, leeres Konto.
- GS07: ``scripts/seed_loadtest.py`` prueft den Datenbanknamen statt der ganzen
  URL, zeigt kein Passwort und verlangt ``--yes-delete-all``.
"""
from __future__ import annotations

import types
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from models import Mortgage, Property, WatchlistItem
from models.bucket import Bucket
from models.position import AssetType, Position, PriceSource, PricingMode
from models.transaction import Transaction
from models.user import User
from services.bucket_service import create_system_buckets

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_user(db, *, is_admin: bool = False, email: str | None = None) -> User:
    user = User(
        email=email or f"u{uuid.uuid4().hex[:8]}@test.local",
        password_hash="x",
        is_admin=is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _give_position(db, user: User, ticker: str = "REAL") -> Position:
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket_id = (
        await db.execute(select(Bucket.id).where(Bucket.user_id == user.id).limit(1))
    ).scalar()
    pos = Position(
        bucket_id=bucket_id,
        user_id=user.id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="CHF",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=Decimal("1"),
        cost_basis_chf=Decimal("1000"),
        current_price=Decimal("100"),
    )
    db.add(pos)
    await db.commit()
    return pos


async def _count(db, model, user_id) -> int:
    rows = await db.execute(select(model.id).where(model.user_id == user_id))
    return len(rows.all())


@pytest.fixture
def seed_module(monkeypatch):
    import seed as module

    # alembic laeuft nur gegen die echte Docker-DB — im SQLite-Test stubben.
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: None)
    return module


# ---------------------------------------------------------------------------
# GS14 — seed.py
# ---------------------------------------------------------------------------

async def test_seed_writes_only_into_the_named_account(db, seed_module):
    admin = await _make_user(db, is_admin=True)
    demo = await _make_user(db, email="Demo@Test.Local")

    assert await seed_module.seed("demo@test.local") is True

    # Frueher landete alles beim ersten Admin der Instanz.
    for model in (Position, Transaction, Property, WatchlistItem):
        assert await _count(db, model, admin.id) == 0, model.__name__
    assert await _count(db, Position, demo.id) == len(seed_module.POSITIONS)
    assert await _count(db, WatchlistItem, demo.id) == len(seed_module.WATCHLIST)
    assert await _count(db, Property, demo.id) == 1
    assert len((await db.execute(select(Mortgage))).scalars().all()) == 2


async def test_seed_refuses_an_account_that_already_has_data(db, seed_module):
    """Kernfall des Befunds: Konto mit Positionen, aber ohne Immobilie."""
    admin = await _make_user(db, is_admin=True)
    await _give_position(db, admin)

    assert await seed_module.seed(admin.email) is False

    assert await _count(db, Property, admin.id) == 0
    assert await _count(db, Position, admin.id) == 1
    assert await _count(db, WatchlistItem, admin.id) == 0


async def test_seed_is_not_blocked_by_data_of_other_users(db, seed_module):
    """Die Existenzpruefungen gelten dem Zielkonto, nicht der ganzen Instanz."""
    other = await _make_user(db, is_admin=True)
    await _give_position(db, other)
    db.add(Property(user_id=other.id, name="Fremd", property_type="efh", purchase_price=1))
    await db.commit()
    demo = await _make_user(db)

    assert await seed_module.seed(demo.email) is True

    assert await _count(db, Position, demo.id) == len(seed_module.POSITIONS)
    assert await _count(db, Property, demo.id) == 1
    assert await _count(db, Position, other.id) == 1
    assert await _count(db, Property, other.id) == 1


async def test_seed_unknown_account_writes_nothing(db, seed_module):
    await _make_user(db, is_admin=True)

    assert await seed_module.seed("niemand@test.local") is False
    assert await seed_module.seed("   ") is False

    assert (await db.execute(select(Position))).scalars().all() == []
    assert (await db.execute(select(Property))).scalars().all() == []


async def test_seed_cli_requires_demo_user(seed_module, monkeypatch):
    called = []
    monkeypatch.setattr(
        seed_module, "asyncio", types.SimpleNamespace(run=lambda coro: called.append(coro))
    )

    with pytest.raises(SystemExit) as exc:
        seed_module.main([])

    assert exc.value.code == 2
    assert called == []


async def test_seed_cli_exit_code_reports_refusal(seed_module, monkeypatch):
    seen = []

    async def _fake_seed(email):
        seen.append(email)

    def _run(coro, result):
        coro.close()
        return result

    monkeypatch.setattr(seed_module, "seed", _fake_seed)
    monkeypatch.setattr(seed_module, "asyncio", types.SimpleNamespace(run=lambda c: _run(c, False)))
    assert seed_module.main(["--demo-user", "demo@test.local"]) == 1

    monkeypatch.setattr(seed_module, "asyncio", types.SimpleNamespace(run=lambda c: _run(c, True)))
    assert seed_module.main(["--demo-user", "demo@test.local"]) == 0


# ---------------------------------------------------------------------------
# GS07 — scripts/seed_loadtest.py
# ---------------------------------------------------------------------------

_PROD_URL_WITH_MARKERS = "postgresql+asyncpg://openfolio:S3cret_test_pw@db_stage.internal:5432/openfolio"


@pytest.mark.parametrize(
    "url",
    [
        _PROD_URL_WITH_MARKERS,
        "postgresql+asyncpg://finance_stage:pw@db:5432/finance",
        "postgresql+asyncpg://u:pw@db:5432/",
        "kein-url",
    ],
)
async def test_loadtest_guard_checks_only_the_database_name(url):
    from scripts.seed_loadtest import _stage_safety_check

    with pytest.raises(SystemExit) as exc:
        _stage_safety_check(url)

    assert "REFUSING" in str(exc.value)


async def test_loadtest_guard_does_not_print_the_password():
    from scripts.seed_loadtest import _stage_safety_check

    with pytest.raises(SystemExit) as exc:
        _stage_safety_check(_PROD_URL_WITH_MARKERS)

    message = str(exc.value)
    assert "S3cret_test_pw" not in message
    assert "openfolio" in message  # Host und DB-Name bleiben zur Diagnose sichtbar


@pytest.mark.parametrize("db_name", ["finance_stage", "finance_test", "openfolio_stage_2"])
async def test_loadtest_guard_accepts_stage_and_test_databases(db_name):
    from scripts.seed_loadtest import _stage_safety_check

    _stage_safety_check(f"postgresql+asyncpg://u:prodlike-pw@db:5432/{db_name}")


def _capture_seed(monkeypatch):
    import scripts.seed_loadtest as module

    calls: list[dict] = []

    # Synchroner Ersatz: main() reicht das Ergebnis nur an asyncio.run weiter.
    def _fake_seed(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(module, "seed", _fake_seed)
    monkeypatch.setattr(module, "asyncio", types.SimpleNamespace(run=lambda _: None))
    return module, calls


async def test_loadtest_cli_requires_yes_delete_all(monkeypatch, capsys):
    module, calls = _capture_seed(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:pw@db:5432/finance_stage")

    with pytest.raises(SystemExit) as exc:
        module.main(["--users", "1"])

    assert exc.value.code == 1
    assert calls == []
    assert "--yes-delete-all" in capsys.readouterr().err


async def test_loadtest_cli_refuses_production_even_with_flag(monkeypatch):
    module, calls = _capture_seed(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", _PROD_URL_WITH_MARKERS)

    with pytest.raises(SystemExit) as exc:
        module.main(["--users", "1", "--yes-delete-all"])

    assert "REFUSING" in str(exc.value)
    assert calls == []


async def test_loadtest_cli_runs_with_flag_on_stage(monkeypatch):
    module, calls = _capture_seed(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:pw@db:5432/finance_stage")

    module.main(["--users", "3", "--buckets", "2", "--days", "5", "--yes-delete-all"])

    assert len(calls) == 1
    assert calls[0]["users"] == 3 and calls[0]["buckets"] == 2 and calls[0]["days"] == 5
