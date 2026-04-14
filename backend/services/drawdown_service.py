"""Portfolio drawdown calculation from PortfolioSnapshot history.

Peak-to-trough drawdown per period, plus the Drawdown-Bremse flag (active when
current drawdown vs. peak >= 6%).

Methodology: TWR wealth index (cash-flow-adjusted daily returns), so deposits
and withdrawals do not produce spurious drawdowns. peak_value_chf and
trough_value_chf are the nominal portfolio values on the peak/trough dates —
they may not match max_drawdown_pct directly when cash flows occurred between
them. Use max_drawdown_pct as the performance metric.
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

    # Build TWR wealth index: cash-flow-adjusted daily returns so that
    # Einzahlungen/Auszahlungen keinen Drawdown vortaeuschen.
    # Convention: net_cash_flow_chf is included in total_value_chf for that day.
    # Pure return day t = (V_t - NetCF_t) / V_{t-1}.
    index: list[tuple[date, float, float]] = []  # (date, wealth_index, raw_value)
    prev_value = float(snapshots[0].total_value_chf or 0)
    wealth = 1.0
    index.append((snapshots[0].date, wealth, prev_value))
    for snap in snapshots[1:]:
        value = float(snap.total_value_chf or 0)
        netcf = float(snap.net_cash_flow_chf or 0)
        if prev_value > 0:
            ret_factor = (value - netcf) / prev_value
            if ret_factor > 0:
                wealth *= ret_factor
        index.append((snap.date, wealth, value))
        prev_value = value

    running_peak_index = 0.0
    running_peak_date: date | None = None
    running_peak_value = 0.0
    max_dd_pct = 0.0
    max_dd_peak_date: date | None = None
    max_dd_peak_value = 0.0
    max_dd_trough_date: date | None = None
    max_dd_trough_value = 0.0

    for d, w, v in index:
        if w > running_peak_index:
            running_peak_index = w
            running_peak_date = d
            running_peak_value = v
        if running_peak_index > 0:
            dd_pct = (w / running_peak_index - 1) * 100
            if dd_pct < max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_peak_date = running_peak_date
                max_dd_peak_value = running_peak_value
                max_dd_trough_date = d
                max_dd_trough_value = v

    current_value = index[-1][2]
    current_index = index[-1][1]
    current_vs_peak_pct = None
    if running_peak_index > 0:
        current_vs_peak_pct = round((current_index / running_peak_index - 1) * 100, 2)

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
