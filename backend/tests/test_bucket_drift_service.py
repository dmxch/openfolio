"""Tests fuer services/bucket_drift_service.py.

Coverage:
  - max_total_pct ueberschritten -> Alert + Idempotenz
  - max_total_pct unterschritten -> kein Alert
  - max_total_pct nicht gesetzt -> bucket wird skipped
  - Email-Hookup mit/ohne AlertPreference und SmtpConfig
  - Neutrale Sprache: kein imperatives "Verkaufen!" im Mail-HTML
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch

import pytest

from models.alert_preference import AlertPreference
from models.ntfy_config import NtfyConfig
from models.position import AssetType, Position, PricingMode, PriceSource
from models.smtp_config import SmtpConfig
from models.user import User, UserSettings
from services.bucket_drift_service import (
    ALERT_CATEGORY,
    _render_drift_email_html,
    check_bucket_total_drift,
)
from services.bucket_service import create_bucket, create_system_buckets

pytestmark = pytest.mark.asyncio


async def _make_user(db, email=None):
    user = User(email=email or f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    return user


async def _make_position(db, user, *, bucket_id, ticker="AAPL", value_chf=1000):
    pos = Position(
        user_id=user.id,
        bucket_id=bucket_id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="CHF",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=Decimal("1"),
        cost_basis_chf=Decimal(str(value_chf)),
        current_price=Decimal(str(value_chf)),
    )
    db.add(pos)
    await db.commit()
    return pos


@pytest.fixture
def patched_allocations():
    """Patcht get_allocations_by_bucket im drift-Service.

    Ohne Patch wuerde live FX-Lookup + cached prices benoetigt; das ist im
    Test-Setup nicht verfuegbar. Wir liefern stattdessen ein vorgefertigtes
    Allokations-Mapping pro Bucket-Namen.
    """
    def make(allocations_by_name: dict[str, dict]):
        async def _fake(_db, _user_id):
            # _user_id wird ignoriert — Test setzt nur 1 User auf
            from sqlalchemy import select
            from models.bucket import Bucket
            res = await _db.execute(
                select(Bucket).where(Bucket.user_id == _user_id)
            )
            buckets = list(res.scalars().all())
            out = []
            for b in buckets:
                if b.name in allocations_by_name:
                    a = allocations_by_name[b.name]
                    out.append({
                        "bucket_id": str(b.id),
                        "name": b.name,
                        "color": b.color,
                        "kind": b.kind.value,
                        "system_role": b.system_role.value if b.system_role else None,
                        "value_chf": a["value_chf"],
                        "pct": a["pct"],
                    })
            return out
        return _fake
    return make


# ---------- Trigger ----------------------------------------------------------

async def test_drift_triggers_when_pct_above_limit(db, patched_allocations):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(
        db, user.id, name="Spielgeld",
        risk_rules={"max_total_pct": 20.0, "drawdown_brake_active": False},
    )
    await db.commit()

    fake = patched_allocations({"Spielgeld": {"value_chf": 30000.0, "pct": 30.0}})
    with patch("services.bucket_drift_service.get_allocations_by_bucket", new=fake):
        result = await check_bucket_total_drift(db)
    assert result["checked"] == 1
    assert result["triggered"] == 1


async def test_drift_idempotent_per_day(db, patched_allocations):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    await create_bucket(
        db, user.id, name="Spielgeld",
        risk_rules={"max_total_pct": 20.0},
    )
    await db.commit()

    fake = patched_allocations({"Spielgeld": {"value_chf": 30000.0, "pct": 30.0}})
    with patch("services.bucket_drift_service.get_allocations_by_bucket", new=fake):
        r1 = await check_bucket_total_drift(db)
        r2 = await check_bucket_total_drift(db)
    assert r1["triggered"] == 1
    assert r2["triggered"] == 0
    assert r2["skipped_idempotent"] == 1


async def test_drift_no_trigger_when_within_limit(db, patched_allocations):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    await create_bucket(
        db, user.id, name="Spielgeld",
        risk_rules={"max_total_pct": 30.0},
    )
    await db.commit()

    fake = patched_allocations({"Spielgeld": {"value_chf": 20000.0, "pct": 20.0}})
    with patch("services.bucket_drift_service.get_allocations_by_bucket", new=fake):
        result = await check_bucket_total_drift(db)
    assert result["checked"] == 1
    assert result["triggered"] == 0


async def test_drift_skipped_when_no_rule(db, patched_allocations):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    await create_bucket(db, user.id, name="Core", risk_rules={})
    await db.commit()

    fake = patched_allocations({"Core": {"value_chf": 90000.0, "pct": 90.0}})
    with patch("services.bucket_drift_service.get_allocations_by_bucket", new=fake):
        result = await check_bucket_total_drift(db)
    assert result["checked"] == 0
    assert result["triggered"] == 0
    assert result["skipped_no_rule"] >= 1


# ---------- Email-Hookup -----------------------------------------------------

async def test_email_not_sent_without_pref(db, patched_allocations):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    await create_bucket(db, user.id, name="Spielgeld", risk_rules={"max_total_pct": 20.0})
    await db.commit()

    fake = patched_allocations({"Spielgeld": {"value_chf": 30000.0, "pct": 30.0}})
    with patch("services.bucket_drift_service.get_allocations_by_bucket", new=fake), \
         patch("services.bucket_drift_service.send_email", new=AsyncMock(return_value=True)) as mock_send:
        result = await check_bucket_total_drift(db)
    assert result["triggered"] == 1
    assert result["emails_sent"] == 0
    assert result["emails_skipped_no_pref"] == 1
    mock_send.assert_not_awaited()


async def test_email_sent_when_pref_and_smtp_present(db, patched_allocations):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    await create_bucket(db, user.id, name="Spielgeld", risk_rules={"max_total_pct": 20.0})
    await db.commit()
    db.add(AlertPreference(
        user_id=user.id, category=ALERT_CATEGORY,
        is_enabled=True, notify_email=True,
    ))
    db.add(SmtpConfig(
        user_id=user.id, host="smtp.test", port=587,
        username="x", password_encrypted="x", from_email=user.email,
    ))
    await db.commit()

    fake = patched_allocations({"Spielgeld": {"value_chf": 30000.0, "pct": 30.0}})
    with patch("services.bucket_drift_service.get_allocations_by_bucket", new=fake), \
         patch("services.bucket_drift_service.send_email", new=AsyncMock(return_value=True)) as mock_send:
        result = await check_bucket_total_drift(db)
    assert result["emails_sent"] == 1
    mock_send.assert_awaited()


# ---------- Push-Hookup ------------------------------------------------------

async def test_push_dispatched_with_pref_and_ntfy(db, patched_allocations):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    await create_bucket(db, user.id, name="Spielgeld", risk_rules={"max_total_pct": 20.0})
    await db.commit()
    db.add(AlertPreference(
        user_id=user.id, category=ALERT_CATEGORY,
        is_enabled=True, notify_email=False, notify_push=True,
    ))
    db.add(NtfyConfig(
        user_id=user.id, server_url="https://ntfy.example.com",
        topic="of-test", is_enabled=True,
    ))
    await db.commit()

    fake = patched_allocations({"Spielgeld": {"value_chf": 30000.0, "pct": 30.0}})
    with patch("services.bucket_drift_service.get_allocations_by_bucket", new=fake), \
         patch("services.bucket_drift_service.send_push_for_user", new=Mock()) as mock_push:
        result = await check_bucket_total_drift(db)
    assert result["pushes_sent"] == 1
    mock_push.assert_called_once()
    kwargs = mock_push.call_args.kwargs
    assert "Verkaufen" not in kwargs["title"] and "Verkaufen" not in kwargs["message"]


# ---------- Neutrale Sprache ------------------------------------------------

def test_email_html_has_neutral_language():
    from models.bucket import Bucket, BucketKind
    bucket = Bucket(
        id=uuid.uuid4(), user_id=uuid.uuid4(),
        name="Spielgeld", kind=BucketKind.user,
    )
    html = _render_drift_email_html(bucket, current_pct=35.0, threshold_pct=20.0, value_chf=12345.67)
    assert "Verkaufen" not in html
    assert "Kaufen" not in html
    assert "muss" not in html.lower()
    assert "Spielgeld" in html
    assert "35.00" in html
    assert "20.00" in html
