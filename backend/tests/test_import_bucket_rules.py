"""Tests fuer F-15 Import-Bucket-Mapping-Regeln.

Coverage:
  - resolve_bucket_for_import: source-match (Substring case-insensitive)
  - resolve_bucket_for_import: ticker_pattern-match (Glob)
  - Priority-Order: erste passende gewinnt
  - Geloeschter Bucket wird ueberschritten
  - create_rule erzwingt mind. einen Filter
"""
from __future__ import annotations

import uuid

import pytest

from models.user import User, UserSettings
from services.bucket_service import create_bucket, create_system_buckets
from services.import_bucket_rule_service import (
    ImportRuleError,
    create_rule,
    delete_rule,
    list_rules,
    resolve_bucket_for_import,
)

pytestmark = pytest.mark.asyncio


async def _make_user(db):
    u = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(u)
    await db.commit()
    db.add(UserSettings(user_id=u.id, noticed_buckets_migration=True))
    await db.commit()
    return u


async def test_create_rule_requires_at_least_one_filter(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Crypto")
    await db.commit()
    with pytest.raises(ImportRuleError):
        await create_rule(db, user.id, bucket_id=bucket.id)


async def test_create_rule_invalid_bucket(db):
    user = await _make_user(db)
    with pytest.raises(ImportRuleError):
        await create_rule(
            db, user.id,
            bucket_id=uuid.uuid4(),
            source="swissquote",
        )


async def test_resolve_by_source(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="SwissquoteBucket")
    await db.commit()
    await create_rule(db, user.id, bucket_id=bucket.id, source="swissquote", priority=10)
    await db.commit()
    resolved = await resolve_bucket_for_import(
        db, user.id, ticker="ABBN.SW", source="swissquote_csv"
    )
    assert resolved == bucket.id


async def test_resolve_by_ticker_pattern(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Crypto")
    await db.commit()
    await create_rule(
        db, user.id, bucket_id=bucket.id,
        ticker_pattern="BTC*", priority=10,
    )
    await db.commit()
    resolved = await resolve_bucket_for_import(
        db, user.id, ticker="BTC-USD", source="any"
    )
    assert resolved == bucket.id
    # negativ test
    none_resolved = await resolve_bucket_for_import(
        db, user.id, ticker="AAPL", source="any"
    )
    assert none_resolved is None


async def test_priority_order_wins(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    b_low = await create_bucket(db, user.id, name="LowPrio")
    b_high = await create_bucket(db, user.id, name="HighPrio")
    await db.commit()
    # Lower priority value = checked first
    await create_rule(
        db, user.id, bucket_id=b_high.id,
        source="swissquote", priority=10,
    )
    await create_rule(
        db, user.id, bucket_id=b_low.id,
        source="swissquote", priority=100,
    )
    await db.commit()
    resolved = await resolve_bucket_for_import(
        db, user.id, ticker="X", source="swissquote_csv"
    )
    assert resolved == b_high.id


async def test_deleted_bucket_skipped(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    b_deleted = await create_bucket(db, user.id, name="WillBeDeleted")
    b_kept = await create_bucket(db, user.id, name="Kept")
    await db.commit()
    await create_rule(
        db, user.id, bucket_id=b_deleted.id,
        source="x", priority=10,
    )
    await create_rule(
        db, user.id, bucket_id=b_kept.id,
        source="x", priority=20,
    )
    await db.commit()
    # delete b_deleted
    from dateutils import utcnow
    b_deleted.deleted_at = utcnow()
    await db.commit()

    resolved = await resolve_bucket_for_import(
        db, user.id, ticker="Y", source="x_csv"
    )
    assert resolved == b_kept.id


async def test_combined_filters_must_both_match(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="SwissCrypto")
    await db.commit()
    await create_rule(
        db, user.id, bucket_id=bucket.id,
        source="swissquote", ticker_pattern="*-USD",
    )
    await db.commit()
    # nur source matched, nicht ticker_pattern
    none_resolved = await resolve_bucket_for_import(
        db, user.id, ticker="ABBN.SW", source="swissquote_csv"
    )
    assert none_resolved is None
    # beide matched
    resolved = await resolve_bucket_for_import(
        db, user.id, ticker="BTC-USD", source="swissquote_csv"
    )
    assert resolved == bucket.id


async def test_delete_rule(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="X")
    await db.commit()
    rule = await create_rule(db, user.id, bucket_id=bucket.id, source="x")
    await db.commit()
    deleted = await delete_rule(db, user.id, rule.id)
    assert deleted is True
    rules = await list_rules(db, user.id)
    assert rules == []
