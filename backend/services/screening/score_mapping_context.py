"""Context-Builder fuer die nicht-deterministischen Score-Mappings.

`percentile` und `hybrid` aus `score_mappings.py` brauchen eine empirische
CDF (Cumulative Distribution Function) aus den letzten N Tagen Composite-
Scans. Dieser Builder erzeugt dieses ctx-Dict aus der DB.

Hot-Path (Iteration-2.5-Item-G nach Live-Switch): einmal pro Scan im
`_persist_results` bauen, ggf. Redis-cachen (TTL 25 h).

Backtest-Path (Iteration-2.5-Item-E): per-Tag-CDF auf historische Scans
anwenden, ohne Cache (Offline-Reproduzierbarkeit).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.screening import ScreeningResult, ScreeningScan


async def build_percentile_ctx(
    db: AsyncSession,
    *,
    window_days: int = 30,
    as_of: datetime | None = None,
) -> dict:
    """Baut CDF + Upper-CDF aus den letzten `window_days` Tagen completed
    Composite-Scans (relativ zu `as_of`, default = jetzt).

    Returns:
        `{'cdf': [(raw, pct), ...], 'upper_cdf': [(raw, display), ...]}`

    - `cdf` deckt alle vorkommenden raw-Scores, aufsteigend, mit
      kumulativem Perzentil-Rang in der Population.
    - `upper_cdf` deckt nur raw ≥ 4, kumulativer Rang innerhalb dieser
      Subpopulation, linear auf den Display-Bereich [40, 100] gemappt.
    """
    cutoff = (as_of or datetime.utcnow()) - timedelta(days=window_days)

    scan_ids_subq = (
        select(ScreeningScan.id)
        .where(ScreeningScan.status == "completed")
        .where(ScreeningScan.started_at >= cutoff)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(ScreeningResult.score, func.count())
        .where(ScreeningResult.scan_id.in_(scan_ids_subq))
        .group_by(ScreeningResult.score)
        .order_by(ScreeningResult.score)
    )
    counts = [(int(raw), int(n)) for raw, n in rows.all()]

    total = sum(n for _, n in counts)
    if total == 0:
        return {"cdf": [], "upper_cdf": []}

    cdf: list[tuple[int, int]] = []
    cumulative = 0
    for raw, n in counts:
        cumulative += n
        cdf.append((raw, int(round(100 * cumulative / total))))

    upper_counts = [(raw, n) for raw, n in counts if raw >= 4]
    upper_total = sum(n for _, n in upper_counts)
    upper_cdf: list[tuple[int, int]] = []
    if upper_total > 0:
        cumulative = 0
        for raw, n in upper_counts:
            cumulative += n
            rank = cumulative / upper_total
            display = 40 + int(round(60 * rank))
            upper_cdf.append((raw, display))

    return {"cdf": cdf, "upper_cdf": upper_cdf}
