"""Vollreview 2026-11-13, Fixer «schema»: Models, Migrationen 100–102, Entrypoint, env.py.

Die Suite baut das Schema per ``create_all`` auf SQLite. Geprüft wird deshalb:
die Deklaration in den Models (Typen, Indizes, CHECK-Constraints), ihr Verhalten
auf SQLite und ihre Deckung mit den Migrationen. Die Migrationen selbst laufen
nur gegen Postgres (Wegwerf-DB, siehe Bericht des Fixers).
"""

import importlib.util
import io
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable

from models import Base
from models.api_write_log import API_WRITE_LOG_ACTIONS, ApiWriteLog
from models.app_setting import FRESH_INSTALL_SETTINGS, AppSetting, seed_fresh_install_settings
from models.bucket import Bucket, BucketKind, BucketSystemRole, PositionBucketHistory
from models.eps_quarterly import EpsQuarterly
from models.pending_order import PendingOrder
from models.price_alert import PriceAlert
from models.price_cache import PriceCache
from models.property import Mortgage, PropertyExpense, PropertyIncome

BACKEND = Path(__file__).resolve().parent.parent
VERSIONS = BACKEND / "alembic" / "versions"

REPORT_ACTIONS = (
    "report_upload",
    "report_update",
    "report_delete",
    "report_prune",
    "report_archive",
    "report_unarchive",
)


def _load_migration(filename: str):
    spec = importlib.util.spec_from_file_location(f"vr11_{filename[:3]}", VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alembic_config() -> Config:
    # Ohne alembic.ini: env.py ruft sonst logging.fileConfig auf und schaltet
    # die Logger der übrigen Suite ab.
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _model_checks() -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and constraint.name:
                found[str(constraint.name)] = (table.name, str(constraint.sqltext))
    return found


def _index(table, name: str):
    return next((ix for ix in table.indexes if ix.name == name), None)


# ---------------------------------------------------------------------------
# K078 — CHECK-Constraints stehen in den Models und greifen nach create_all
# ---------------------------------------------------------------------------

EXPECTED_CHECKS = {
    "ck_api_write_log_action",
    "ck_buckets_kind",
    "ck_buckets_system_role",
    "ck_buckets_target_xor",
    "ck_buckets_user_no_system_role",
    "ck_import_bucket_rules_at_least_one_filter",
    "ck_pbh_changed_by",
    "ck_pending_dividend_status",
    "ck_pending_orders_expiry_type",
    "ck_pending_orders_gtd_date",
    "ck_pending_orders_limit_positive",
    "ck_pending_orders_shares_positive",
    "ck_pending_orders_side",
    "ck_pending_orders_status",
    "ck_pending_orders_stop_positive",
}


def test_models_declare_every_check_constraint_of_the_migrated_schema():
    assert set(_model_checks()) == EXPECTED_CHECKS


def test_repair_migration_and_models_use_the_same_check_clauses():
    """Migration 102 und die Models dürfen nicht auseinanderlaufen."""
    migration = _load_migration("102_check_constraints_repair.py")
    model_checks = _model_checks()

    assert len(migration._CHECKS) == 12
    for table, name, clause in migration._CHECKS:
        assert model_checks[name] == (table, clause), name


def _order(**overrides) -> PendingOrder:
    values = dict(
        user_id=uuid.uuid4(),
        ticker="NVDA",
        side="buy",
        shares=Decimal("1"),
        limit_price=Decimal("100"),
        expiry_type="gtc",
        status="open",
    )
    values.update(overrides)
    return PendingOrder(**values)


@pytest.mark.asyncio
async def test_valid_pending_orders_pass_the_checks(db):
    db.add(_order())
    db.add(_order(side="sell", stop_price=Decimal("90"), status="filled"))
    db.add(_order(expiry_type="gtd", expiry_date=date(2027, 1, 15), status="cancelled"))
    db.add(_order(expiry_type="day"))
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides, constraint",
    [
        ({"side": "hold"}, "ck_pending_orders_side"),
        ({"status": "expired"}, "ck_pending_orders_status"),
        ({"expiry_type": "ioc"}, "ck_pending_orders_expiry_type"),
        ({"shares": Decimal("0")}, "ck_pending_orders_shares_positive"),
        ({"limit_price": Decimal("0")}, "ck_pending_orders_limit_positive"),
        ({"stop_price": Decimal("-1")}, "ck_pending_orders_stop_positive"),
        ({"expiry_type": "gtd"}, "ck_pending_orders_gtd_date"),
        ({"expiry_date": date(2027, 1, 15)}, "ck_pending_orders_gtd_date"),
    ],
)
async def test_pending_order_checks_reject_invalid_rows(db, overrides, constraint):
    db.add(_order(**overrides))
    with pytest.raises(IntegrityError, match=constraint):
        await db.commit()


@pytest.mark.asyncio
async def test_bucket_checks(db):
    user_id = uuid.uuid4()
    db.add(Bucket(user_id=user_id, name="Core"))
    db.add(
        Bucket(
            user_id=user_id,
            name="Vorsorge",
            kind=BucketKind.system,
            system_role=BucketSystemRole.pension,
        )
    )
    await db.commit()

    # Ein User-Bucket darf keine Systemrolle tragen.
    db.add(Bucket(user_id=user_id, name="Falsch", system_role=BucketSystemRole.real_estate))
    with pytest.raises(IntegrityError, match="ck_buckets_user_no_system_role"):
        await db.commit()
    await db.rollback()

    # kind und system_role prüft das Enum schon in Python; die DB-Regel greift
    # bei Schreibzugriffen am ORM vorbei.
    for column, value, constraint in (
        ("kind", "admin", "ck_buckets_kind"),
        ("system_role", "crypto", "ck_buckets_system_role"),
    ):
        with pytest.raises(IntegrityError, match=constraint):
            await db.execute(
                text(f"UPDATE buckets SET {column} = :v WHERE name = 'Vorsorge'"), {"v": value}
            )
        await db.rollback()


@pytest.mark.asyncio
async def test_position_bucket_history_changed_by_check(db):
    db.add(
        PositionBucketHistory(
            position_id=uuid.uuid4(), to_bucket_id=uuid.uuid4(), changed_by="migration_rollback"
        )
    )
    await db.commit()

    db.add(
        PositionBucketHistory(
            position_id=uuid.uuid4(), to_bucket_id=uuid.uuid4(), changed_by="api"
        )
    )
    with pytest.raises(IntegrityError, match="ck_pbh_changed_by"):
        await db.commit()


# ---------------------------------------------------------------------------
# K160 — Report-Aktionen im Audit-Log
# ---------------------------------------------------------------------------


def test_report_actions_are_whitelisted_in_model_and_migration():
    migration = _load_migration("102_check_constraints_repair.py")

    assert set(REPORT_ACTIONS) <= set(API_WRITE_LOG_ACTIONS)
    assert migration._NEW_ACTIONS == API_WRITE_LOG_ACTIONS
    # Downgrade stellt den Stand von Migration 085 her.
    assert migration._OLD_ACTIONS == _load_migration(
        "085_api_write_log_ui_parity_actions.py"
    )._NEW_ACTIONS
    assert max(len(a) for a in API_WRITE_LOG_ACTIONS) <= ApiWriteLog.__table__.c.action.type.length


@pytest.mark.asyncio
async def test_audit_log_accepts_report_actions_and_rejects_unknown_ones(db):
    user_id = uuid.uuid4()
    for action in REPORT_ACTIONS:
        db.add(ApiWriteLog(user_id=user_id, ticker="-", action=action))
    await db.commit()

    db.add(ApiWriteLog(user_id=user_id, ticker="-", action="report_shred"))
    with pytest.raises(IntegrityError, match="ck_api_write_log_action"):
        await db.commit()


# ---------------------------------------------------------------------------
# K049 / K017 / GS09 — price_cache
# ---------------------------------------------------------------------------


def test_price_cache_column_types():
    cols = PriceCache.__table__.c
    for name in ("open", "high", "low", "close"):
        assert (cols[name].type.precision, cols[name].type.scale) == (18, 8), name
    assert cols.ticker.type.length == 60

    pg_ddl = str(CreateTable(PriceCache.__table__).compile(dialect=postgresql.dialect()))
    assert "id BIGSERIAL NOT NULL" in pg_ddl
    assert "ticker VARCHAR(60) NOT NULL" in pg_ddl
    assert "close NUMERIC(18, 8) NOT NULL" in pg_ddl
    # SQLite zählt nur INTEGER PRIMARY KEY automatisch hoch.
    sqlite_ddl = str(CreateTable(PriceCache.__table__).compile(dialect=sqlite.dialect()))
    assert "id INTEGER NOT NULL" in sqlite_ddl


@pytest.mark.asyncio
async def test_price_cache_keeps_small_fx_rates_and_long_tickers(db):
    long_ticker = "X" * 60
    db.add(PriceCache(ticker="JPYCHF=X", date=date(2026, 11, 13), close=Decimal("0.00523456")))
    db.add(PriceCache(ticker=long_ticker, date=date(2026, 11, 13), close=Decimal("1.5")))
    await db.commit()
    db.expire_all()

    rows = (await db.execute(select(PriceCache).order_by(PriceCache.id))).scalars().all()
    assert [r.id for r in rows] == [1, 2]
    assert rows[0].close == Decimal("0.00523456")
    assert rows[1].ticker == long_ticker


def test_migration_100_widens_price_cache_in_one_statement():
    source = (VERSIONS / "100_price_cache_widen.py").read_text()
    upgrade = source.split("def upgrade()")[1].split("def downgrade()")[0]

    assert upgrade.count("ALTER TABLE price_cache") == 1
    for fragment in (
        "ALTER COLUMN id TYPE bigint",
        "ALTER COLUMN ticker TYPE varchar(60)",
        "ALTER COLUMN open TYPE numeric(18,8)",
        "ALTER COLUMN high TYPE numeric(18,8)",
        "ALTER COLUMN low TYPE numeric(18,8)",
        "ALTER COLUMN close TYPE numeric(18,8)",
        "ALTER SEQUENCE IF EXISTS price_cache_id_seq AS bigint",
    ):
        assert fragment in upgrade, fragment


# ---------------------------------------------------------------------------
# K127 / K132 / GS12 — Indizes
# ---------------------------------------------------------------------------


def test_foreign_key_indexes_are_declared():
    for model in (Mortgage, PropertyExpense, PropertyIncome):
        table = model.__table__
        index = _index(table, f"ix_{table.name}_property_id")
        assert index is not None, table.name
        assert [c.name for c in index.columns] == ["property_id"]


def test_open_price_alerts_have_a_partial_index():
    index = _index(PriceAlert.__table__, "ix_price_alerts_open")
    assert index is not None
    assert "WHERE is_active AND NOT is_triggered" in str(
        CreateIndex(index).compile(dialect=postgresql.dialect())
    )


def test_eps_quarterly_has_no_duplicate_of_its_unique_index():
    table = EpsQuarterly.__table__
    assert _index(table, "ix_eps_quarterly_ticker_period") is None
    assert {c.name for c in table.constraints} >= {"uq_eps_quarterly_ticker_period"}
    assert _index(table, "ix_eps_quarterly_fetched") is not None


def test_migration_101_matches_the_declared_indexes():
    source = (VERSIONS / "101_review_indexes.py").read_text()
    upgrade = source.split("def upgrade()")[1].split("def downgrade()")[0]
    downgrade = source.split("def downgrade()")[1]

    created = (
        "ix_reports_linked_transaction",
        "ix_mortgages_property_id",
        "ix_property_expenses_property_id",
        "ix_property_income_property_id",
        "ix_price_alerts_open",
    )
    for name in created:
        assert upgrade.count(f'"{name}"') == 1, name
        assert downgrade.count(f'"{name}"') == 1, name
    assert 'op.drop_index(\n        "ix_eps_quarterly_ticker_period"' in upgrade
    assert 'op.create_index(\n        "ix_eps_quarterly_ticker_period"' in downgrade


# ---------------------------------------------------------------------------
# Migrationskette
# ---------------------------------------------------------------------------


def test_migration_chain_is_linear_up_to_102():
    script = ScriptDirectory.from_config(_alembic_config())

    assert script.get_heads() == ["102"]
    chain = [rev.revision for rev in script.iterate_revisions("102", "099")]
    assert chain == ["102", "101", "100"]
    for revision in chain:
        module = script.get_revision(revision).module
        assert callable(module.upgrade) and callable(module.downgrade)


# ---------------------------------------------------------------------------
# K078 — Neuinstallation: mfa_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_install_seed_sets_mfa_policy_all(db):
    from db import engine as test_engine  # conftest: In-Memory-SQLite
    from services.mfa_policy_service import get_mfa_policy

    assert FRESH_INSTALL_SETTINGS == {"mfa_policy": "all"}
    assert await get_mfa_policy(db) == "off"

    async with test_engine.begin() as conn:
        await conn.run_sync(seed_fresh_install_settings)
        await conn.run_sync(seed_fresh_install_settings)  # idempotent

    rows = (
        await db.execute(select(AppSetting).where(AppSetting.key == "mfa_policy"))
    ).scalars().all()
    assert [r.value for r in rows] == ["all"]
    assert await get_mfa_policy(db) == "all"


@pytest.mark.asyncio
async def test_fresh_install_seed_keeps_an_existing_policy(db):
    from db import engine as test_engine  # conftest: In-Memory-SQLite

    db.add(AppSetting(key="mfa_policy", value="admins_only"))
    await db.commit()

    async with test_engine.begin() as conn:
        await conn.run_sync(seed_fresh_install_settings)

    db.expire_all()
    setting = (
        await db.execute(select(AppSetting).where(AppSetting.key == "mfa_policy"))
    ).scalars().one()
    assert setting.value == "admins_only"


def test_entrypoint_seeds_only_in_the_fresh_database_branch():
    script = (BACKEND / "entrypoint.sh").read_text()
    fresh, existing = script.split('if [ "$TABLE_COUNT" = "0" ]; then')[1].split("\nelse\n")

    assert "seed_fresh_install_settings(conn)" in fresh
    assert fresh.index("create_all(sync_engine)") < fresh.index("seed_fresh_install_settings(conn)")
    assert fresh.index("seed_fresh_install_settings(conn)") < fresh.index("alembic stamp head")
    assert "seed_fresh_install_settings" not in existing
    assert "alembic upgrade head" in existing


# ---------------------------------------------------------------------------
# GS13 — Prozentzeichen in DATABASE_URL
# ---------------------------------------------------------------------------


def test_alembic_env_accepts_url_encoded_password(monkeypatch):
    """env.py lief mit einem URL-kodierten Passwort in einen ValueError."""
    url = "postgresql+asyncpg://openfolio:p%40ss%25word@db:5432/openfolio"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic_config()
    cfg.output_buffer = io.StringIO()

    # Offline-Lauf: führt env.py aus, ohne eine Verbindung zu öffnen.
    command.upgrade(cfg, "092:093", sql=True)

    assert "idx_positions_ticker" in cfg.output_buffer.getvalue()
    assert cfg.get_main_option("sqlalchemy.url") == url
    assert cfg.get_section(cfg.config_ini_section)["sqlalchemy.url"] == url
