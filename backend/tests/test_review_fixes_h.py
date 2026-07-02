"""Regression-Tests fuer Review-Fix Batch H (Code-Review 2026-07-02).

Abgedeckt:
- H4:  seed.py legt Positionen mit Pflicht-bucket_id an (Migration 064)
- H5:  Preis-Alert-Emails: Delivery-Tracking via PriceAlert.notification_sent —
       Throttle verzoegert nur noch, der naechste Lauf liefert nach
- M9:  Per-User-except-Bloecke der Alert-Services rollen die Session zurueck
       (kein PendingRollbackError-Kaskadeneffekt)
- LOW-worker-tasks: _spawn_task haelt starke Task-Referenzen (GC-Schutz)
- LOW-price-refresh-batch: gebatchtes positions.current_price-UPDATE
"""

import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from dateutils import utcnow
from models.bucket import Bucket, BucketSystemRole
from models.position import AssetType, Position, PriceSource, PricingMode
from models.price_alert import PriceAlert
from models.smtp_config import SmtpConfig
from models.user import User, UserSettings
from models.watchlist import WatchlistItem
from services.bucket_service import create_system_buckets

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_user(db, is_admin=False) -> User:
    user = User(
        email=f"u{uuid.uuid4().hex[:8]}@test.local",
        password_hash="x",
        is_admin=is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_position(db, user, ticker="AAPL", shares="1", **kwargs) -> Position:
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
        shares=Decimal(shares),
        cost_basis_chf=Decimal("1000"),
        current_price=Decimal("100"),
        **kwargs,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


async def _make_email_alert(db, user, ticker="ANET") -> PriceAlert:
    alert = PriceAlert(
        user_id=user.id,
        ticker=ticker,
        alert_type="price_below",
        target_value=Decimal("156.00"),
        currency="CHF",
        notify_email=True,
    )
    db.add(alert)
    await db.commit()
    return alert


async def _add_smtp_config(db, user) -> None:
    from services.auth_service import encrypt_value

    db.add(SmtpConfig(
        user_id=user.id,
        host="smtp.test.local",
        port=587,
        username="alerts@test.local",
        password_encrypted=encrypt_value("secret"),
        from_email="alerts@test.local",
        use_tls=True,
    ))
    await db.commit()


def _fake_price(monkeypatch, price=155.94):
    from services import cache

    monkeypatch.setattr(cache, "get", lambda key: {"price": price, "change_pct": 0})


def _mock_smtp(monkeypatch, fail=False):
    """aiosmtplib.send im Service-Modul mocken. Returns Aufruf-Liste."""
    calls = []

    async def _send(msg, **kwargs):
        if fail:
            raise ConnectionError("smtp down")
        calls.append(msg)

    import services.price_alert_service as pas

    monkeypatch.setattr(pas.aiosmtplib, "send", _send)
    return calls


# ---------------------------------------------------------------------------
# H4 — seed.py legt Positionen mit bucket_id an
# ---------------------------------------------------------------------------

async def test_seed_creates_positions_with_bucket_id(db, monkeypatch):
    import seed as seed_module

    # alembic laeuft nur gegen die echte Docker-DB — im SQLite-Test stubben
    # (Tabellen kommen aus dem create_all der conftest).
    monkeypatch.setattr(seed_module.subprocess, "run", lambda *a, **k: None)

    admin = await _make_user(db, is_admin=True)
    await db.commit()

    await seed_module.seed()

    positions = (await db.execute(select(Position))).scalars().all()
    assert len(positions) == len(seed_module.POSITIONS)
    # JEDE Position hat einen Bucket (positions.bucket_id NOT NULL, Migration 064)
    assert all(p.bucket_id is not None for p in positions)
    assert all(p.user_id == admin.id for p in positions)

    # Pension-Position landet im Pension-System-Bucket, liquide im liquid_default
    buckets = {
        b.id: b for b in (await db.execute(
            select(Bucket).where(Bucket.user_id == admin.id)
        )).scalars().all()
    }
    for p in positions:
        role = buckets[p.bucket_id].system_role
        if p.type == AssetType.pension:
            assert role == BucketSystemRole.pension
        else:
            assert role == BucketSystemRole.liquid_default

    # Watchlist wurde ebenfalls angelegt
    wl_count = len((await db.execute(select(WatchlistItem))).scalars().all())
    assert wl_count == len(seed_module.WATCHLIST)


async def test_seed_is_idempotent(db, monkeypatch):
    import seed as seed_module

    monkeypatch.setattr(seed_module.subprocess, "run", lambda *a, **k: None)
    await _make_user(db, is_admin=True)

    await seed_module.seed()
    first_count = len((await db.execute(select(Position))).scalars().all())
    await seed_module.seed()  # zweiter Lauf: Guard greift, nichts doppelt
    second_count = len((await db.execute(select(Position))).scalars().all())
    assert first_count == second_count == len(seed_module.POSITIONS)


# ---------------------------------------------------------------------------
# H5 — Email-Delivery-Tracking via notification_sent
# ---------------------------------------------------------------------------

async def test_trigger_sets_notification_sent_false(db, monkeypatch):
    from services.price_alert_service import check_price_alerts

    user = await _make_user(db)
    await _make_position(db, user, ticker="ANET", shares="10")
    alert = await _make_email_alert(db, user, ticker="ANET")
    _fake_price(monkeypatch)

    triggered = await check_price_alerts(db)

    assert len(triggered) == 1
    await db.refresh(alert)
    assert alert.is_triggered is True
    assert alert.notification_sent is False


async def test_throttled_alert_is_delivered_on_next_run(db, monkeypatch):
    """Kern-Fix H5: Throttle verwirft nicht mehr — naechster Lauf liefert nach."""
    from services.price_alert_service import check_price_alerts, send_alert_emails

    user = await _make_user(db)
    await _make_position(db, user, ticker="ANET", shares="10")
    alert = await _make_email_alert(db, user, ticker="ANET")
    await _add_smtp_config(db, user)

    # Digest-Throttle aktiv: letzte Email vor 5 Minuten
    db.add(UserSettings(user_id=user.id, last_email_digest_at=utcnow() - timedelta(minutes=5)))
    await db.commit()

    _fake_price(monkeypatch)
    calls = _mock_smtp(monkeypatch)

    triggered = await check_price_alerts(db)
    assert len(triggered) == 1

    # Lauf 1: gethrottlet — keine Email, aber Alert bleibt unversandt (kein Verlust)
    await send_alert_emails(triggered)
    assert calls == []
    await db.refresh(alert)
    assert alert.notification_sent is False

    # Throttle-Fenster abgelaufen
    settings_row = (await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )).scalars().first()
    settings_row.last_email_digest_at = utcnow() - timedelta(minutes=16)
    await db.commit()

    # Lauf 2: KEIN neuer Trigger — Backlog wird trotzdem nachgeliefert
    await send_alert_emails([])
    assert len(calls) == 1
    assert "ANET" in str(calls[0]["Subject"])
    await db.refresh(alert)
    assert alert.notification_sent is True

    # Lauf 3: Backlog leer — keine Doppel-Email
    await send_alert_emails([])
    assert len(calls) == 1


async def test_smtp_failure_leaves_alert_unsent_for_retry(db, monkeypatch):
    from services.price_alert_service import check_price_alerts, send_alert_emails

    user = await _make_user(db)
    await _make_position(db, user, ticker="ANET", shares="10")
    alert = await _make_email_alert(db, user, ticker="ANET")
    await _add_smtp_config(db, user)
    _fake_price(monkeypatch)

    _mock_smtp(monkeypatch, fail=True)
    triggered = await check_price_alerts(db)
    await send_alert_emails(triggered)
    await db.refresh(alert)
    assert alert.notification_sent is False  # transienter Fehler → Retry

    calls = _mock_smtp(monkeypatch, fail=False)
    await send_alert_emails([])
    assert len(calls) == 1
    await db.refresh(alert)
    assert alert.notification_sent is True


async def test_no_smtp_config_marks_handled_without_send(db, monkeypatch):
    """Zustellung strukturell unmoeglich → als erledigt markieren (kein Endlos-Rescan)."""
    from services.price_alert_service import check_price_alerts, send_alert_emails

    user = await _make_user(db)
    await _make_position(db, user, ticker="ANET", shares="10")
    alert = await _make_email_alert(db, user, ticker="ANET")
    _fake_price(monkeypatch)
    calls = _mock_smtp(monkeypatch)

    triggered = await check_price_alerts(db)
    await send_alert_emails(triggered)

    assert calls == []
    await db.refresh(alert)
    assert alert.notification_sent is True


async def test_backlog_window_excludes_old_alerts(db, monkeypatch):
    """24h-Fenster: uralte unversandte Alerts fluten beim Deploy nicht die Inbox."""
    from services.price_alert_service import send_alert_emails

    user = await _make_user(db)
    await _add_smtp_config(db, user)
    old_alert = PriceAlert(
        user_id=user.id,
        ticker="OLD",
        alert_type="price_below",
        target_value=Decimal("10"),
        currency="CHF",
        notify_email=True,
        is_active=False,
        is_triggered=True,
        triggered_at=utcnow() - timedelta(hours=25),
        trigger_price=Decimal("9.50"),
        notification_sent=False,
    )
    db.add(old_alert)
    await db.commit()

    calls = _mock_smtp(monkeypatch)
    await send_alert_emails([])

    assert calls == []
    await db.refresh(old_alert)
    assert old_alert.notification_sent is False  # bleibt unangetastet


# ---------------------------------------------------------------------------
# M9 — Rollback in den per-User-except-Bloecken der Alert-Services
# ---------------------------------------------------------------------------

async def _run_rollback_check(db, monkeypatch, service_module, entry_fn_name, inner_fn_name):
    user_a = await _make_user(db)
    user_b = await _make_user(db)
    # IDs VOR dem Lauf snapshotten: der Service-Rollback expired die
    # ORM-Instanzen — user_a.id im Fake wuerde danach einen async Lazy-Load
    # ausloesen (MissingGreenlet). Genau dieser Effekt war der Grund, warum
    # die Services auf plain-ID-Iteration + db.get pro User umgestellt wurden.
    a_id, b_id = user_a.id, user_b.id

    processed = []

    async def _boom_or_ok(db_arg, user):
        uid = user.id  # frisch via db.get geladen — safe
        processed.append(uid)
        if uid == a_id:
            raise RuntimeError("simulated db failure")

    monkeypatch.setattr(service_module, inner_fn_name, _boom_or_ok)

    rollbacks = []
    orig_rollback = db.rollback

    async def _spy_rollback():
        rollbacks.append(1)
        await orig_rollback()

    monkeypatch.setattr(db, "rollback", _spy_rollback)

    await getattr(service_module, entry_fn_name)(db)

    # Fehler bei User A → rollback; User B wurde trotzdem verarbeitet
    assert len(rollbacks) == 1
    assert a_id in processed and b_id in processed


async def test_breakout_alert_rollback_on_user_failure(db, monkeypatch):
    import services.breakout_alert_service as svc

    await _run_rollback_check(
        db, monkeypatch, svc, "check_breakout_alerts", "_check_user_breakout_alerts"
    )


async def test_etf_200dma_alert_rollback_on_user_failure(db, monkeypatch):
    import services.etf_200dma_alert_service as svc

    await _run_rollback_check(db, monkeypatch, svc, "check_etf_200dma_alerts", "_check_user_alerts")


async def test_rule_alert_rollback_on_user_failure(db, monkeypatch):
    import services.rule_alert_service as svc

    await _run_rollback_check(db, monkeypatch, svc, "check_rule_alerts", "_check_user_rule_alerts")


# ---------------------------------------------------------------------------
# LOW-worker-tasks — starke Task-Referenzen im Worker
# ---------------------------------------------------------------------------

async def test_worker_spawn_task_holds_strong_reference():
    import worker

    release = asyncio.Event()

    async def _job():
        await release.wait()

    task = worker._spawn_task(_job())
    assert task in worker._pending_tasks  # starke Referenz solange pending

    release.set()
    await task
    await asyncio.sleep(0)  # done_callback (discard) laufen lassen
    assert task not in worker._pending_tasks


# ---------------------------------------------------------------------------
# LOW-price-refresh-batch — gebatchtes positions.current_price-UPDATE
# ---------------------------------------------------------------------------

async def test_batch_price_update_matches_ticker_and_yfinance_ticker(db):
    from services.cache_service import _update_position_prices_batch

    user = await _make_user(db)
    pos_direct = await _make_position(db, user, ticker="AAPL")
    pos_via_yf = await _make_position(db, user, ticker="PAAS", yfinance_ticker="PAAS.TO")
    pos_untouched = await _make_position(db, user, ticker="MSFT")

    await _update_position_prices_batch(db, [("AAPL", 123.45), ("PAAS.TO", 55.5)])
    await db.commit()

    await db.refresh(pos_direct)
    await db.refresh(pos_via_yf)
    await db.refresh(pos_untouched)
    assert float(pos_direct.current_price) == pytest.approx(123.45)
    assert float(pos_via_yf.current_price) == pytest.approx(55.5)  # via yfinance_ticker
    assert float(pos_untouched.current_price) == pytest.approx(100)


async def test_batch_price_update_skips_gold_and_inactive(db):
    from services.cache_service import _update_position_prices_batch

    user = await _make_user(db)
    pos_gold = await _make_position(db, user, ticker="Gold", gold_org=True)
    pos_inactive = await _make_position(db, user, ticker="DEAD", is_active=False)

    await _update_position_prices_batch(db, [("Gold", 999.0), ("DEAD", 1.0)])
    await db.commit()

    await db.refresh(pos_gold)
    await db.refresh(pos_inactive)
    assert float(pos_gold.current_price) == pytest.approx(100)  # gold_org=false-Guard
    assert float(pos_inactive.current_price) == pytest.approx(100)  # is_active-Guard


async def test_batch_price_update_prefers_yfinance_ticker_on_double_match(db):
    """Deterministik: bei Doppel-Match gewinnt der aufgeloeste Daten-Ticker."""
    from services.cache_service import _update_position_prices_batch

    user = await _make_user(db)
    pos = await _make_position(db, user, ticker="PAAS", yfinance_ticker="PAAS.TO")

    await _update_position_prices_batch(db, [("PAAS", 11.0), ("PAAS.TO", 22.0)])
    await db.commit()

    await db.refresh(pos)
    assert float(pos.current_price) == pytest.approx(22.0)


async def test_batch_price_update_empty_is_noop(db):
    from services.cache_service import _update_position_prices_batch

    await _update_position_prices_batch(db, [])  # darf nicht werfen
