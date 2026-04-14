"""Portfolio drawdown calculation from PortfolioSnapshot history.

Peak-to-trough drawdown per period, plus the Drawdown-Bremse flag (active when
current drawdown vs. peak >= 6%).
"""
import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.portfolio_snapshot import PortfolioSnapshot

logger = logging.getLogger(__name__)

DRAWDOWN_BRAKE_THRESHOLD_PCT = 6.0

_VALID_PERIODS = {"ytd", "1m", "3m", "6m", "1y", "all"}


def _period_start(period: str, today: date) -> date | None:
    if period == "ytd":
        return date(today.year, 1, 1)
    if period == "1m":
        return today - timedelta(days=30)
    if period == "3m":
        return today - timedelta(days=90)
    if period == "6m":
        return today - timedelta(days=182)
    if period == "1y":
        return today - timedelta(days=365)
    return None  # all


async def get_max_drawdown(
    db: AsyncSession,
    user_id: uuid.UUID,
    period: str = "ytd",
) -> dict:
    """Compute max drawdown (peak-to-trough) over the period."""
    if period not in _VALID_PERIODS:
        raise ValueError(f"Ungueltige Periode: {period}")

    today = date.today()
    start = _period_start(period, today)

    stmt = select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
    if start is not None:
        stmt = stmt.where(PortfolioSnapshot.date >= start)
    stmt = stmt.order_by(PortfolioSnapshot.date.asc())

    result = await db.execute(stmt)
    snapshots = result.scalars().all()

    if not snapshots:
        return {
            "period": period,
            "snapshots_count": 0,
            "max_drawdown_pct": None,
            "peak_date": None,
            "peak_value_chf": None,
            "trough_date": None,
            "trough_value_chf": None,
            "current_value_chf": None,
            "running_peak_date": None,
            "running_peak_value_chf": None,
            "current_vs_peak_pct": None,
            "drawdown_brake_active": False,
            "drawdown_brake_threshold_pct": DRAWDOWN_BRAKE_THRESHOLD_PCT,
            "warning": "keine_snapshots_im_zeitraum",
        }

    running_peak_value = 0.0
    running_peak_date: date | None = None
    max_dd_pct = 0.0
    max_dd_peak_date: date | None = None
    max_dd_peak_value = 0.0
    max_dd_trough_date: date | None = None
    max_dd_trough_value = 0.0

    for snap in snapshots:
        value = float(snap.total_value_chf or 0)
        if value > running_peak_value:
            running_peak_value = value
            running_peak_date = snap.date
        if running_peak_value > 0:
            dd_pct = (value / running_peak_value - 1) * 100
            if dd_pct < max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_peak_date = running_peak_date
                max_dd_peak_value = running_peak_value
                max_dd_trough_date = snap.date
                max_dd_trough_value = value

    current_value = float(snapshots[-1].total_value_chf or 0)
    current_vs_peak_pct = None
    if running_peak_value > 0:
        current_vs_peak_pct = round((current_value / running_peak_value - 1) * 100, 2)

    max_drawdown_pct = round(max_dd_pct, 2) if max_dd_pct < 0 else 0.0

    brake_active = (
        current_vs_peak_pct is not None
        and current_vs_peak_pct <= -DRAWDOWN_BRAKE_THRESHOLD_PCT
    )

    return {
        "period": period,
        "snapshots_count": len(snapshots),
        "max_drawdown_pct": max_drawdown_pct,
        "peak_date": max_dd_peak_date.isoformat() if max_dd_peak_date else None,
        "peak_value_chf": round(max_dd_peak_value, 2) if max_dd_peak_date else None,
        "trough_date": max_dd_trough_date.isoformat() if max_dd_trough_date else None,
        "trough_value_chf": round(max_dd_trough_value, 2) if max_dd_trough_date else None,
        "current_value_chf": round(current_value, 2),
        "running_peak_date": running_peak_date.isoformat() if running_peak_date else None,
        "running_peak_value_chf": round(running_peak_value, 2) if running_peak_date else None,
        "current_vs_peak_pct": current_vs_peak_pct,
        "drawdown_brake_active": brake_active,
        "drawdown_brake_threshold_pct": DRAWDOWN_BRAKE_THRESHOLD_PCT,
    }
