"""Daily Sanity-Check: sum(bucket_snapshots) ~= portfolio_snapshots.

Toleranz: max(±1.00 CHF absolut, ±0.05% relativ). Begruendung Plan v2.1 R-4.2:
FX-Konvertierungen produzieren Floating-Point-Rundungsdifferenzen, die mit
strenger ±0.01-Toleranz taeglich False-Positive-Alerts produzieren wuerden.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bucket import BucketSnapshot
from models.portfolio_snapshot import PortfolioSnapshot

logger = logging.getLogger(__name__)

ABSOLUTE_TOLERANCE_CHF = 1.00
RELATIVE_TOLERANCE_PCT = 0.0005  # 0.05%


def _within_tolerance(portfolio_value: float, bucket_sum: float) -> bool:
    diff_abs = abs(portfolio_value - bucket_sum)
    if diff_abs <= ABSOLUTE_TOLERANCE_CHF:
        return True
    rel = diff_abs / max(abs(portfolio_value), 1.0)
    return rel <= RELATIVE_TOLERANCE_PCT


async def check_user_consistency(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    days: int = 30,
) -> list[dict]:
    """Liefert eine Liste mismatches der letzten N Tage.

    Returns: Liste von {date, portfolio_total, bucket_sum, diff} fuer alle
    Tage, an denen die Differenz die Toleranz uebersteigt.

    Cutoff: max(cutoff_param, frueheste_bucket_snapshot_date). User ohne
    rueckwirkende bucket_snapshots (Migration-Effekt) bekommen keine
    False-Positive-Mismatches fuer die Vergangenheit gemeldet — Backfill
    historischer bucket_snapshots ist Phase-2-Scope.
    """
    cutoff = date.today() - timedelta(days=days)

    earliest_q = await db.execute(
        select(func.min(BucketSnapshot.date)).where(
            BucketSnapshot.user_id == user_id,
        )
    )
    earliest_bucket_date = earliest_q.scalar()
    if earliest_bucket_date is None:
        # Noch nie ein bucket_snapshot geschrieben — nichts zu pruefen
        return []
    if earliest_bucket_date > cutoff:
        cutoff = earliest_bucket_date

    p_q = await db.execute(
        select(PortfolioSnapshot.date, PortfolioSnapshot.total_value_chf)
        .where(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.date >= cutoff,
        )
    )
    portfolio = {row.date: float(row.total_value_chf) for row in p_q.all()}

    b_q = await db.execute(
        select(
            BucketSnapshot.date,
            func.sum(BucketSnapshot.total_value_chf).label("total"),
        )
        .where(
            BucketSnapshot.user_id == user_id,
            BucketSnapshot.date >= cutoff,
        )
        .group_by(BucketSnapshot.date)
    )
    bucket_sums = {row.date: float(row.total) for row in b_q.all()}

    mismatches = []
    for d, pval in portfolio.items():
        bval = bucket_sums.get(d, 0.0)
        if not _within_tolerance(pval, bval):
            mismatches.append({
                "date": d.isoformat(),
                "portfolio_total_chf": round(pval, 2),
                "bucket_sum_chf": round(bval, 2),
                "diff_chf": round(pval - bval, 2),
                "diff_pct": round(
                    ((pval - bval) / max(abs(pval), 1.0)) * 100, 4
                ),
            })
    return mismatches


async def check_all_users(db: AsyncSession, *, days: int = 7) -> dict:
    """Sweep ueber alle User. Loggt Warnungen bei Mismatches.

    Returns Summary fuer Admin-Notification.
    """
    from models.user import User
    users_q = await db.execute(select(User.id).where(User.is_active.is_(True)))
    user_ids = [row[0] for row in users_q.all()]

    total_checked = len(user_ids)
    users_with_issues = 0
    sample_mismatches = []

    for uid in user_ids:
        mm = await check_user_consistency(db, uid, days=days)
        if mm:
            users_with_issues += 1
            logger.warning(
                "Bucket consistency mismatch user=%s days=%s count=%d sample=%s",
                uid,
                days,
                len(mm),
                mm[0] if mm else None,
            )
            if len(sample_mismatches) < 5:
                sample_mismatches.append({"user_id": str(uid), "mismatch": mm[0]})

    return {
        "total_checked": total_checked,
        "users_with_issues": users_with_issues,
        "samples": sample_mismatches,
        "tolerance": {
            "absolute_chf": ABSOLUTE_TOLERANCE_CHF,
            "relative_pct": RELATIVE_TOLERANCE_PCT * 100,
        },
    }
