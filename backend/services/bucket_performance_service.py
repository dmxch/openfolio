"""Performance-Berechnung pro Bucket.

Architektur-Prinzip (siehe Plan §4.2):
  Die bestehenden Performance-Services (portfolio_service,
  performance_history_service, total_return_service) duerfen NICHT geaendert
  werden. Dieser Service wrapped sie mit zusaetzlichem bucket_id-Filter.

Cashflow-Zuordnung:
  Eine Transaktion gehoert zu Bucket der Position zum Zeitpunkt der Transaktion.
  Da Bucket-Wechsel prospektiv sind (Re-Labeling, kein Cost-Basis-Split), reicht
  fuer das Cashflow-Aggregat: Transaction.position_id → aktuelle Position.bucket_id.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from constants.cashflow import INFLOW_TYPES, OUTFLOW_TYPES
from models.bucket import Bucket, BucketSnapshot
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import Position
from models.transaction import Transaction

logger = logging.getLogger(__name__)


async def get_bucket_summary(
    db: AsyncSession, user_id: uuid.UUID, bucket_id: uuid.UUID
) -> dict:
    """Aktueller Markt-Wert + Cost-Basis fuer einen Bucket.

    Returns:
        {
          "bucket_id", "name", "total_value_chf", "cost_basis_chf",
          "unrealized_pnl_chf", "unrealized_pnl_pct",
          "position_count", "running_peak_chf"
        }
    """
    bucket_q = await db.execute(
        select(Bucket).where(Bucket.id == bucket_id, Bucket.user_id == user_id)
    )
    bucket = bucket_q.scalar_one_or_none()
    if bucket is None:
        return {}

    # Aktuelle Positionen im Bucket
    pos_q = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.bucket_id == bucket_id,
            Position.is_active.is_(True),
        )
    )
    positions = list(pos_q.scalars().all())

    # Letzter Bucket-Snapshot fuer current_value + running_peak
    snap_q = await db.execute(
        select(BucketSnapshot)
        .where(
            BucketSnapshot.user_id == user_id,
            BucketSnapshot.bucket_id == bucket_id,
        )
        .order_by(BucketSnapshot.date.desc())
        .limit(1)
    )
    snap = snap_q.scalar_one_or_none()

    total_value = Decimal("0")
    cost_basis = Decimal("0")
    for p in positions:
        cost_basis += Decimal(p.cost_basis_chf or 0)
        if p.shares and p.current_price:
            # Vereinfachung: CHF-Wert. FX-Konvertierung passiert in
            # snapshot_service._calc_portfolio_value_fast. Hier nur Naeherung
            # fuer Live-Ansicht; final value via bucket_snapshots.
            total_value += Decimal(str(float(p.shares) * float(p.current_price)))

    # Bevorzugt Snapshot-Wert (FX-akkurat)
    if snap is not None:
        total_value = snap.total_value_chf

    unrealized = total_value - cost_basis
    unrealized_pct = (
        float((unrealized / cost_basis) * 100) if cost_basis > 0 else 0.0
    )

    return {
        "bucket_id": str(bucket_id),
        "name": bucket.name,
        "color": bucket.color,
        "benchmark": bucket.benchmark,
        "total_value_chf": float(total_value),
        "cost_basis_chf": float(cost_basis),
        "unrealized_pnl_chf": float(unrealized),
        "unrealized_pnl_pct": round(unrealized_pct, 2),
        "position_count": len(positions),
        "running_peak_chf": float(snap.running_peak_chf) if snap else float(total_value),
        "snapshot_date": snap.date.isoformat() if snap else None,
    }


async def get_bucket_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
    *,
    period: str = "ytd",
) -> list[dict]:
    """Zeitreihe (date, total_value_chf, net_cash_flow_chf) aus bucket_snapshots.

    period: 'ytd' | '1m' | '3m' | '6m' | '1y' | 'all'.
    """
    today = date.today()
    if period == "ytd":
        start = date(today.year, 1, 1)
    elif period == "1m":
        start = today - timedelta(days=30)
    elif period == "3m":
        start = today - timedelta(days=90)
    elif period == "6m":
        start = today - timedelta(days=180)
    elif period == "1y":
        start = today - timedelta(days=365)
    elif period == "all":
        start = None
    else:
        raise ValueError(f"Unbekannter Zeitraum: {period}")

    stmt = (
        select(BucketSnapshot)
        .where(
            BucketSnapshot.user_id == user_id,
            BucketSnapshot.bucket_id == bucket_id,
        )
        .order_by(BucketSnapshot.date.asc())
    )
    if start is not None:
        stmt = stmt.where(BucketSnapshot.date >= start)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "date": s.date.isoformat(),
            "total_value_chf": float(s.total_value_chf),
            "net_cash_flow_chf": float(s.net_cash_flow_chf),
            "running_peak_chf": float(s.running_peak_chf),
        }
        for s in rows
    ]


async def get_allocations_by_bucket(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Live-Allokation pro Bucket (cached prices, kein yfinance).

    Returns: Liste sortiert nach value_chf desc, mit name/color/value/pct.
    Nur aktive Buckets, PE/RE-System-Buckets ausgeschlossen (analog
    snapshot_service-Logik). Cash/Pension/Stocks/ETFs/Crypto/Commodities
    werden gezaehlt.
    """
    from services.utils import get_fx_rates_batch
    import asyncio as _asyncio

    from models.bucket import BucketSystemRole
    excluded_roles = {BucketSystemRole.real_estate, BucketSystemRole.private_equity}

    buckets_q = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.deleted_at.is_(None),
        )
    )
    buckets = list(buckets_q.scalars().all())
    eligible = [b for b in buckets if b.system_role not in excluded_roles]
    by_id = {b.id: b for b in eligible}

    pos_q = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.is_active.is_(True),
        )
    )
    positions = list(pos_q.scalars().all())

    from services.snapshot_service import _calc_position_value_chf
    fx_rates = await _asyncio.to_thread(get_fx_rates_batch)

    totals: dict = {b.id: 0.0 for b in eligible}
    for pos in positions:
        if pos.bucket_id is None or pos.bucket_id not in by_id:
            continue
        val = await _calc_position_value_chf(pos, fx_rates)
        totals[pos.bucket_id] += val

    total_sum = sum(totals.values())
    result = []
    for b in eligible:
        v = totals.get(b.id, 0.0)
        result.append({
            "bucket_id": str(b.id),
            "name": b.name,
            "color": b.color,
            "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
            "system_role": b.system_role.value if b.system_role else None,
            "value_chf": round(v, 2),
            "pct": round((v / total_sum) * 100, 2) if total_sum > 0 else 0.0,
        })
    result.sort(key=lambda r: r["value_chf"], reverse=True)
    return result


async def get_bucket_cashflows(
    db: AsyncSession,
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """Netto-Cashflows in/aus dem Bucket fuer den Zeitraum.

    Verwendet die aktuelle position.bucket_id-Zuordnung (siehe Modul-Doc
    fuer Caveats bei Bucket-Wechseln).
    """
    stmt = (
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type.in_(INFLOW_TYPES), Transaction.total_chf),
                        (Transaction.type.in_(OUTFLOW_TYPES), -Transaction.total_chf),
                        else_=0,
                    )
                ),
                0,
            )
        )
        .join(Position, Transaction.position_id == Position.id)
        .where(
            Transaction.user_id == user_id,
            Position.bucket_id == bucket_id,
        )
    )
    if start is not None:
        stmt = stmt.where(Transaction.date >= start)
    if end is not None:
        stmt = stmt.where(Transaction.date <= end)

    result = await db.execute(stmt)
    net = result.scalar() or 0
    return {
        "net_cash_flow_chf": float(net),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    }
