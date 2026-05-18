"""Korrelations-Matrix zwischen Buckets eines Users.

Basiert auf bucket_snapshots.total_value_chf, cashflow-bereinigt nach TWR-Logik:
  r[t] = (value[t] - net_cash_flow_chf[t]) / value[t-1] - 1

Filterung:
  - Nur Buckets mit deleted_at IS NULL.
  - System-Buckets real_estate, private_equity, pension immer ausgeschlossen
    (HEILIGE Regeln 4/5/6 — keine liquide Performance).
  - liquid_default + user-Buckets sind drin.

Mindest-Anforderungen:
  - >= 2 Buckets nach Filterung
  - >= _MIN_COMMON_DAYS gemeinsame Datenpunkte pro Paar

Output kompatibel zur Position-Korrelations-Matrix (correlation_service):
  matrix als List[List[float|None]], high_correlations als sortierte Paare,
  warnings als String-Liste.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bucket import Bucket, BucketSnapshot, BucketSystemRole

logger = logging.getLogger(__name__)

_EXCLUDED_SYSTEM_ROLES: set[BucketSystemRole] = {
    BucketSystemRole.real_estate,
    BucketSystemRole.private_equity,
    BucketSystemRole.pension,
}

_PERIOD_DAYS: dict[str, int | None] = {
    "30d": 30,
    "90d": 90,
    "180d": 180,
    "1y": 365,
    "all": None,
}

_MIN_COMMON_DAYS = 20
_HIGH_CORR_THRESHOLD = 0.7
_CORR_DECIMALS = 4


def _period_start(period: str) -> date | None:
    days = _PERIOD_DAYS.get(period)
    if days is None:
        return None
    return date.today() - timedelta(days=days)


def _classify_pair(r: float) -> str:
    """Neutrale Klassifikation eines Bucket-Paares.

    Bewusst keine Handlungsempfehlung — beschreibt nur Stärke und Richtung.
    """
    direction = "positiv" if r >= 0 else "negativ"
    if abs(r) >= 0.85:
        strength = "stark"
    elif abs(r) >= _HIGH_CORR_THRESHOLD:
        strength = "erhöht"
    else:
        strength = "moderat"
    return f"{strength} {direction} korreliert"


async def compute_bucket_correlation_matrix(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    period: str = "90d",
) -> dict[str, Any]:
    """Berechnet paarweise Korrelationen zwischen User-Buckets über bucket_snapshots.

    Raises:
        ValueError: wenn nach Filterung < 2 Buckets oder unzureichende Historie.
    """
    if period not in _PERIOD_DAYS:
        raise ValueError(f"Unbekannter Zeitraum: {period}")

    start = _period_start(period)

    buckets_q = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.deleted_at.is_(None),
        )
    )
    buckets = [
        b for b in buckets_q.scalars().all()
        if b.system_role not in _EXCLUDED_SYSTEM_ROLES
    ]

    if len(buckets) < 2:
        raise ValueError("Mindestens 2 vergleichbare Buckets nötig")

    bucket_ids = [b.id for b in buckets]

    snap_stmt = select(BucketSnapshot).where(
        BucketSnapshot.user_id == user_id,
        BucketSnapshot.bucket_id.in_(bucket_ids),
    )
    if start is not None:
        snap_stmt = snap_stmt.where(BucketSnapshot.date >= start)
    snap_stmt = snap_stmt.order_by(BucketSnapshot.date.asc())

    snap_q = await db.execute(snap_stmt)
    snapshots = list(snap_q.scalars().all())

    if not snapshots:
        raise ValueError("Keine bucket_snapshots im Zeitraum")

    # Wide DataFrames: rows=date, cols=bucket_id
    rows: dict[tuple[date, uuid.UUID], tuple[float, float]] = {}
    for s in snapshots:
        rows[(s.date, s.bucket_id)] = (
            float(s.total_value_chf),
            float(s.net_cash_flow_chf or 0.0),
        )

    all_dates = sorted({d for (d, _) in rows.keys()})
    value_df = pd.DataFrame(index=all_dates, columns=bucket_ids, dtype=float)
    cashflow_df = pd.DataFrame(index=all_dates, columns=bucket_ids, dtype=float)
    for (d, bid), (val, cf) in rows.items():
        value_df.at[d, bid] = val
        cashflow_df.at[d, bid] = cf

    cashflow_df = cashflow_df.fillna(0.0)

    # TWR-daily-Return: r[t] = (V[t] - cf[t]) / V[t-1] - 1
    prev = value_df.shift(1)
    returns = (value_df - cashflow_df) / prev - 1.0
    returns = returns.replace([float("inf"), float("-inf")], pd.NA)
    returns = returns.dropna(how="all")

    warnings: list[str] = []

    keep_cols: list[uuid.UUID] = []
    for bid in returns.columns:
        count = int(returns[bid].notna().sum())
        if count < _MIN_COMMON_DAYS:
            bucket_label = next((b.name for b in buckets if b.id == bid), str(bid))
            warnings.append(f"insufficient_history:{bucket_label}:{count}_days")
        else:
            keep_cols.append(bid)

    returns = returns[keep_cols]
    if not returns.empty:
        returns = returns.dropna(how="any")

    if returns.empty or len(returns.columns) < 2:
        raise ValueError("Unzureichende gemeinsame Historie für Korrelation")

    if len(returns) < _MIN_COMMON_DAYS:
        warnings.append(f"insufficient_joint_history:{len(returns)}_days")
        raise ValueError("Unzureichende gemeinsame Historie für Korrelation")

    corr = returns.corr()
    matrix_bids = list(corr.columns)

    matrix: list[list[float | None]] = []
    for i, _ in enumerate(matrix_bids):
        row = []
        for j, _ in enumerate(matrix_bids):
            v = corr.iat[i, j]
            row.append(None if pd.isna(v) else round(float(v), _CORR_DECIMALS))
        matrix.append(row)

    by_id = {b.id: b for b in buckets}
    buckets_out = [
        {
            "id": str(bid),
            "name": by_id[bid].name,
            "color": by_id[bid].color,
            "kind": by_id[bid].kind.value,
        }
        for bid in matrix_bids
    ]

    pairs: list[dict] = []
    for i in range(len(matrix_bids)):
        for j in range(i + 1, len(matrix_bids)):
            v = corr.iat[i, j]
            if pd.isna(v):
                continue
            r = float(v)
            if abs(r) >= _HIGH_CORR_THRESHOLD:
                bi = by_id[matrix_bids[i]]
                bj = by_id[matrix_bids[j]]
                pairs.append({
                    "bucket_a_id": str(bi.id),
                    "bucket_a_name": bi.name,
                    "bucket_b_id": str(bj.id),
                    "bucket_b_name": bj.name,
                    "correlation": round(r, _CORR_DECIMALS),
                    "interpretation": _classify_pair(r),
                })
    pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "observations": int(len(returns)),
        "buckets": buckets_out,
        "matrix": matrix,
        "high_correlations": pairs,
        "warnings": warnings,
    }
