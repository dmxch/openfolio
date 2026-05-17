"""Rueckwirkender bucket_snapshots-Backfill (Plan §8.2, Phase 2 F-16).

Vereinfachte Annahme: Bucket-Zuordnung der Vergangenheit == Bucket-Zuordnung
heute (position.bucket_id). Korrekt ist diese Annahme nur, wenn der User
noch keine Bucket-Wechsel gemacht hat — sonst ist die Historie eine
Approximation und der User wird im UI darauf hingewiesen.

Berechnungs-Logik:
  Fuer jeden Tag T mit portfolio_snapshot[user_id, T]:
    - Verteile portfolio_total_value_chf proportional zur aktuellen Bucket-
      Allokation auf die Buckets.
    - Schreibe bucket_snapshots[user, bucket, T] mit total_value_chf
      anteilig, running_peak_chf als max(prev_peak, total).
  Bei Tagen ohne portfolio_snapshot: skip.

Bestehende bucket_snapshots werden NICHT ueberschrieben — Backfill ist
non-destructive.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bucket import Bucket, BucketSnapshot, BucketSystemRole
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import Position

logger = logging.getLogger(__name__)


_EXCLUDED_ROLES = {
    BucketSystemRole.real_estate,
    BucketSystemRole.private_equity,
}


async def _current_bucket_shares(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[uuid.UUID, float]:
    """Liefert die aktuelle Allokation: {bucket_id: share_0_to_1}.

    Basiert auf position.cost_basis_chf (proxy, kein FX-Bezug). Buckets mit
    excluded system_role werden ignoriert.
    """
    pos_q = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.is_active.is_(True),
        )
    )
    positions = list(pos_q.scalars().all())

    bucket_q = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.deleted_at.is_(None),
        )
    )
    buckets = {b.id: b for b in bucket_q.scalars().all()}

    totals: dict[uuid.UUID, float] = defaultdict(float)
    grand = 0.0
    for p in positions:
        if p.bucket_id is None:
            continue
        b = buckets.get(p.bucket_id)
        if b is None or b.system_role in _EXCLUDED_ROLES:
            continue
        v = float(p.cost_basis_chf or 0)
        totals[p.bucket_id] += v
        grand += v

    if grand <= 0:
        # Equal split als Fallback
        eligible_ids = [
            b.id for b in buckets.values()
            if b.system_role not in _EXCLUDED_ROLES
        ]
        if not eligible_ids:
            return {}
        share = 1.0 / len(eligible_ids)
        return {bid: share for bid in eligible_ids}
    return {bid: v / grand for bid, v in totals.items()}


async def backfill_bucket_snapshots(
    db: AsyncSession, user_id: uuid.UUID
) -> dict:
    """Rueckwirkender Backfill der bucket_snapshots fuer einen User.

    Returns: {"days_filled": int, "buckets_touched": int, "skipped_existing": int}
    """
    shares = await _current_bucket_shares(db, user_id)
    if not shares:
        return {"days_filled": 0, "buckets_touched": 0, "skipped_existing": 0}

    # Alle portfolio_snapshots des Users laden
    ps_q = await db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.user_id == user_id)
        .order_by(PortfolioSnapshot.date.asc())
    )
    portfolio_snaps = list(ps_q.scalars().all())
    if not portfolio_snaps:
        return {"days_filled": 0, "buckets_touched": 0, "skipped_existing": 0}

    # Bereits existierende bucket_snapshots-Termine: skip
    existing_q = await db.execute(
        select(BucketSnapshot.date, BucketSnapshot.bucket_id)
        .where(BucketSnapshot.user_id == user_id)
    )
    existing_keys: set[tuple[date, uuid.UUID]] = {
        (row.date, row.bucket_id) for row in existing_q.all()
    }

    # Running peaks pro Bucket vorab (von vorhandenen Snapshots)
    running_peak: dict[uuid.UUID, float] = defaultdict(float)
    pq_q = await db.execute(
        select(BucketSnapshot)
        .where(BucketSnapshot.user_id == user_id)
        .order_by(BucketSnapshot.date.asc())
    )
    for s in pq_q.scalars().all():
        running_peak[s.bucket_id] = max(running_peak[s.bucket_id], float(s.total_value_chf))

    days_filled = 0
    buckets_touched: set[uuid.UUID] = set()
    skipped = 0

    for ps in portfolio_snaps:
        total = float(ps.total_value_chf or 0)
        net_cf_total = float(ps.net_cash_flow_chf or 0)
        cash_total = float(ps.cash_chf or 0)
        for bid, share in shares.items():
            if (ps.date, bid) in existing_keys:
                skipped += 1
                continue
            v = round(total * share, 2)
            prev = running_peak.get(bid, 0.0)
            peak = max(prev, v)
            running_peak[bid] = peak
            db.add(BucketSnapshot(
                user_id=user_id,
                bucket_id=bid,
                date=ps.date,
                total_value_chf=Decimal(str(v)),
                cash_chf=Decimal(str(round(cash_total * share, 2))),
                net_cash_flow_chf=Decimal(str(round(net_cf_total * share, 2))),
                running_peak_chf=Decimal(str(peak)),
            ))
            buckets_touched.add(bid)
            days_filled += 1

    await db.flush()
    return {
        "days_filled": days_filled,
        "buckets_touched": len(buckets_touched),
        "skipped_existing": skipped,
    }
