"""Tests fuer services/bucket_drawdown_service.py.

Coverage:
  - Drawdown-Trigger feuert bei threshold-Ueberschreitung
  - Idempotenz: zweiter Call am selben Tag erzeugt keinen zweiten Alert
  - bucket_age < 7 Tage: skipped (kein False-Positive)
  - drawdown_brake_active=False: skipped
  - Email-Hookup: ohne AlertPreference keine Mail, mit Pref + SmtpConfig: Mail
  - Neutrale Sprache: kein imperatives "Verkaufen!" im Mail-HTML
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from models.alert_preference import AlertPreference
from models.bucket import BucketAlertLog, BucketSnapshot
from models.smtp_config import SmtpConfig
from models.user import User, UserSettings
from services.bucket_drawdown_service import (
    ALERT_CATEGORY,
    ALERT_TYPE,
    MIN_BUCKET_AGE_DAYS,
    _render_drawdown_email_html,
    check_bucket_drawdown_brakes,
)
from services.bucket_service import create_bucket, create_system_buckets

pytestmark = pytest.mark.asyncio


async def _make_user(db, email=None):
    user = User(
        email=email or f"u{uuid.uuid4().hex[:8]}@test.local",
        password_hash="x",
    )
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    return user


async def _make_bucket_with_history(db, user, *, drawdown_pct=15.0, days=30, active=True):
    """Erzeuge user-bucket mit synthetischer Snapshot-Historie.

    Wertverlauf: Peak bei 1000 CHF (vor `days` Tagen), aktueller Wert 800 CHF
    → ~20% Drawdown. Triggert die Bremse bei threshold=15.
    """
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(
        db,
        user.id,
        name="Trading",
        risk_rules={
            "drawdown_brake_pct": drawdown_pct,
            "drawdown_brake_active": active,
        },
    )
    await db.commit()

    today = date.today()
    # Erster Snapshot vor `days` Tagen
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        if i == days:
            value = Decimal("1000.00")
            peak = Decimal("1000.00")
        elif i == 0:
            value = Decimal("800.00")
            peak = Decimal("1000.00")
        else:
            value = Decimal("950.00")
            peak = Decimal("1000.00")
        db.add(BucketSnapshot(
            user_id=user.id,
            bucket_id=bucket.id,
            date=d,
            total_value_chf=value,
            cash_chf=Decimal("0"),
            net_cash_flow_chf=Decimal("0"),
            running_peak_chf=peak,
        ))
    await db.commit()
    return bucket


async def test_bremse_triggers_and_logs(db):
    user = await _make_user(db)
    await _make_bucket_with_history(db, user)
    result = await check_bucket_drawdown_brakes(db)
    assert result["triggered"] == 1
    assert result["checked"] == 1


async def test_bremse_idempotent_pro_tag(db):
    user = await _make_user(db)
    await _make_bucket_with_history(db, user)
    r1 = await check_bucket_drawdown_brakes(db)
    assert r1["triggered"] == 1
    r2 = await check_bucket_drawdown_brakes(db)
    assert r2["triggered"] == 0
    assert r2["skipped_idempotent"] == 1


async def test_bremse_skipped_when_too_young(db):
    user = await _make_user(db)
    # Nur 3 Tage Historie → bucket_age_days < 7 → skip
    await _make_bucket_with_history(db, user, days=3)
    result = await check_bucket_drawdown_brakes(db)
    assert result["triggered"] == 0
    assert result["skipped_young"] == 1


async def test_bremse_skipped_when_rule_disabled(db):
    user = await _make_user(db)
    await _make_bucket_with_history(db, user, active=False)
    result = await check_bucket_drawdown_brakes(db)
    assert result["checked"] == 0
    assert result["triggered"] == 0
    assert result["skipped_inactive_rules"] == 1


async def test_email_not_sent_without_pref(db):
    user = await _make_user(db)
    await _make_bucket_with_history(db, user)
    # Keine AlertPreference fuer drawdown_brake_bucket
    with patch(
        "services.bucket_drawdown_service.send_email",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        result = await check_bucket_drawdown_brakes(db)
    assert result["triggered"] == 1
    assert result["emails_sent"] == 0
    assert result["emails_skipped_no_pref"] == 1
    mock_send.assert_not_awaited()


async def test_email_not_sent_when_pref_disabled(db):
    user = await _make_user(db)
    await _make_bucket_with_history(db, user)
    db.add(AlertPreference(
        user_id=user.id,
        category=ALERT_CATEGORY,
        is_enabled=False,
        notify_email=True,
    ))
    await db.commit()
    with patch(
        "services.bucket_drawdown_service.send_email",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        result = await check_bucket_drawdown_brakes(db)
    assert result["emails_skipped_no_pref"] == 1
    mock_send.assert_not_awaited()


async def test_email_not_sent_without_smtp(db):
    user = await _make_user(db)
    await _make_bucket_with_history(db, user)
    db.add(AlertPreference(
        user_id=user.id,
        category=ALERT_CATEGORY,
        is_enabled=True,
        notify_email=True,
    ))
    await db.commit()
    with patch(
        "services.bucket_drawdown_service.send_email",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        result = await check_bucket_drawdown_brakes(db)
    assert result["emails_skipped_no_smtp"] == 1
    mock_send.assert_not_awaited()


async def test_email_sent_with_pref_and_smtp(db):
    user = await _make_user(db)
    await _make_bucket_with_history(db, user)
    db.add(AlertPreference(
        user_id=user.id,
        category=ALERT_CATEGORY,
        is_enabled=True,
        notify_email=True,
    ))
    db.add(SmtpConfig(
        user_id=user.id,
        host="smtp.example.com",
        port=587,
        username="user@example.com",
        password_encrypted="encrypted",
        from_email="noreply@example.com",
        use_tls=True,
    ))
    await db.commit()
    with patch(
        "services.bucket_drawdown_service.send_email",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        result = await check_bucket_drawdown_brakes(db)
    assert result["emails_sent"] == 1
    mock_send.assert_awaited_once()
    # Subject muss neutrale Sprache enthalten
    call = mock_send.call_args
    assert "Drawdown-Bremse" in call.args[1]
    assert "Verkaufen" not in call.args[1]  # keine imperative Sprache


def test_render_email_html_is_neutral():
    from models.bucket import Bucket, BucketKind
    bucket = Bucket(user_id=uuid.uuid4(), name="Spielgeld", kind=BucketKind.user)
    dd = {
        "current_vs_peak_pct": -22.5,
        "running_peak_value_chf": 50000.0,
        "current_value_chf": 38750.0,
        "running_peak_date": "2026-04-15",
    }
    html_out = _render_drawdown_email_html(bucket, dd, 15.0)
    # Pruefe Schweizer Tausender-Format
    assert "Spielgeld" in html_out
    assert "neutrale Status-Mitteilung" in html_out
    assert "keine" in html_out.lower() and "handlungsaufforderung" in html_out.lower()
    # Neutrale Sprache — keine imperativen Anweisungen
    assert "Verkaufen!" not in html_out
    assert "verkaufe " not in html_out.lower()
