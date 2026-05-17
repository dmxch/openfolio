"""Service-Layer fuer import_bucket_rules (Plan §2.5 + Phase 2 F-15).

Public API:
  - list_rules(db, user_id)
  - create_rule(db, user_id, bucket_id, source, ticker_pattern, priority)
  - delete_rule(db, user_id, rule_id)
  - resolve_bucket_for_import(db, user_id, ticker, source) -> UUID | None

Erste passende Regel (priority asc) gewinnt. Wenn keine Regel matcht,
liefert resolve_bucket_for_import None — Caller faellt auf liquid_default
zurueck.
"""
from __future__ import annotations

import fnmatch
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bucket import Bucket, BucketKind
from models.import_bucket_rule import ImportBucketRule

logger = logging.getLogger(__name__)


class ImportRuleError(Exception):
    """Domain-Fehler im import_bucket_rule_service."""


async def list_rules(
    db: AsyncSession, user_id: uuid.UUID
) -> list[ImportBucketRule]:
    result = await db.execute(
        select(ImportBucketRule)
        .where(ImportBucketRule.user_id == user_id)
        .order_by(ImportBucketRule.priority.asc(), ImportBucketRule.created_at.asc())
    )
    return list(result.scalars().all())


async def create_rule(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    bucket_id: uuid.UUID,
    source: str | None = None,
    ticker_pattern: str | None = None,
    priority: int = 100,
) -> ImportBucketRule:
    if not source and not ticker_pattern:
        raise ImportRuleError(
            "Mindestens einer der Filter (source, ticker_pattern) muss gesetzt sein"
        )
    # Bucket-Existenz pruefen + dem User gehoeren + nicht system-only (User-Buckets sind erlaubt)
    b_q = await db.execute(
        select(Bucket).where(
            Bucket.id == bucket_id,
            Bucket.user_id == user_id,
            Bucket.deleted_at.is_(None),
        )
    )
    bucket = b_q.scalar_one_or_none()
    if bucket is None:
        raise ImportRuleError("Bucket nicht gefunden")

    rule = ImportBucketRule(
        user_id=user_id,
        bucket_id=bucket_id,
        source=source or None,
        ticker_pattern=ticker_pattern or None,
        priority=priority,
    )
    db.add(rule)
    await db.flush()
    return rule


async def delete_rule(
    db: AsyncSession, user_id: uuid.UUID, rule_id: uuid.UUID
) -> bool:
    rule_q = await db.execute(
        select(ImportBucketRule).where(
            ImportBucketRule.id == rule_id,
            ImportBucketRule.user_id == user_id,
        )
    )
    rule = rule_q.scalar_one_or_none()
    if rule is None:
        return False
    await db.delete(rule)
    await db.flush()
    return True


async def resolve_bucket_for_import(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    ticker: str | None,
    source: str | None,
) -> uuid.UUID | None:
    """Erste passende Regel gewinnt. None wenn keine matcht.

    source-match: case-insensitive Substring (z.B. 'swissquote' matched
    'swissquote_csv'). ticker_pattern-match: fnmatch (Glob).
    """
    rules = await list_rules(db, user_id)
    for rule in rules:
        # Source-Filter
        if rule.source:
            if not source or rule.source.lower() not in source.lower():
                continue
        # Ticker-Pattern-Filter
        if rule.ticker_pattern:
            if not ticker or not fnmatch.fnmatch(ticker, rule.ticker_pattern):
                continue
        # Match! Validieren dass der Bucket noch aktiv ist
        b_q = await db.execute(
            select(Bucket).where(
                Bucket.id == rule.bucket_id,
                Bucket.deleted_at.is_(None),
            )
        )
        if b_q.scalar_one_or_none() is None:
            logger.debug(
                "import_bucket_rule %s: bucket %s ist geloescht — skip",
                rule.id, rule.bucket_id,
            )
            continue
        return rule.bucket_id
    return None
