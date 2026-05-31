"""Portfolio drawdown calculation.

Peak-to-trough drawdown per period, plus the Drawdown-Bremse flag (active when
current drawdown vs. peak >= 6%).

Methodology: cash-flow-adjusted TWR so that Einzahlungen/Auszahlungen keinen
Drawdown vortaeuschen.

Portfolio-level (``bucket_id is None``) leitet den Drawdown aus DERSELBEN
rekonstruierten ``portfolio_indexed``-Kurve ab wie ``/performance/history``
(history_service). Damit koennen die beiden Endpoints nicht mehr divergieren
und sparse/fehlerhafte PortfolioSnapshot-Rohwerte erzeugen keinen
Phantom-Drawdown mehr. peak_value_chf/trough_value_chf sind die nominalen
Portfoliowerte (Feld ``value``) an den Peak-/Trough-Tagen des Index — sie
muessen wegen zwischenzeitlicher Cashflows NICHT zu max_drawdown_pct passen.
Verbindlich ist max_drawdown_pct.

Bucket-level (``bucket_id`` gesetzt) rechnet unveraendert auf BucketSnapshot.
"""
import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bucket import BucketSnapshot

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


def _empty(period: str, threshold: float, bucket_id: uuid.UUID | None) -> dict:
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
        "drawdown_brake_threshold_pct": threshold,
        "bucket_id": str(bucket_id) if bucket_id else None,
        "warning": "keine_snapshots_im_zeitraum",
    }


def _running_peak_drawdown(series: list[tuple[date, float, float]], threshold: float):
    """series = [(date, wealth_index, raw_value)] in chronologischer Reihenfolge.

    Liefert das fertige Drawdown-Dict (ohne period/snapshots_count/bucket_id).
    """
    running_peak_index = 0.0
    running_peak_date: date | None = None
    running_peak_value = 0.0
    max_dd_pct = 0.0
    max_dd_peak_date: date | None = None
    max_dd_peak_value = 0.0
    max_dd_trough_date: date | None = None
    max_dd_trough_value = 0.0

    for d, w, v in series:
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

    current_value = series[-1][2]
    current_index = series[-1][1]
    current_vs_peak_pct = None
    if running_peak_index > 0:
        current_vs_peak_pct = round((current_index / running_peak_index - 1) * 100, 2)

    max_drawdown_pct = round(max_dd_pct, 2) if max_dd_pct < 0 else 0.0
    brake_active = (
        current_vs_peak_pct is not None and current_vs_peak_pct <= -threshold
    )

    return {
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
        "drawdown_brake_threshold_pct": threshold,
    }


async def _portfolio_drawdown(
    db: AsyncSession, user_id: uuid.UUID, period: str, start: date | None, today: date
) -> dict:
    """Portfolio-level: aus der rekonstruierten portfolio_indexed-Kurve."""
    from services.history_service import get_portfolio_history

    threshold = DRAWDOWN_BRAKE_THRESHOLD_PCT

    # "all" spiegelt exakt den /performance/history-Endpoint (start = 2000-01-01),
    # damit beide Endpoints dieselbe Kurve sehen und ein Drawdown vor dem ersten
    # PortfolioSnapshot nicht uebersehen wird.
    hist_start = start if start is not None else date(2000, 1, 1)

    hist = await get_portfolio_history(db, hist_start, today, user_id=user_id)
    points = hist.get("data", [])

    if not points:
        return _empty(period, threshold, None)

    series = [
        (date.fromisoformat(p["date"]), float(p["portfolio_indexed"]), float(p["value"]))
        for p in points
    ]
    out = {
        "period": period,
        "snapshots_count": len(points),
        **_running_peak_drawdown(series, threshold),
        "bucket_id": None,
    }
    return out


async def _bucket_drawdown(
    db: AsyncSession,
    user_id: uuid.UUID,
    period: str,
    start: date | None,
    bucket_id: uuid.UUID,
    brake_threshold_pct: float | None,
) -> dict:
    """Bucket-level: unveraendert auf BucketSnapshot (TWR wealth index)."""
    stmt = select(BucketSnapshot).where(
        BucketSnapshot.user_id == user_id,
        BucketSnapshot.bucket_id == bucket_id,
    )
    if start is not None:
        stmt = stmt.where(BucketSnapshot.date >= start)
    stmt = stmt.order_by(BucketSnapshot.date.asc())
    threshold = (
        brake_threshold_pct
        if brake_threshold_pct is not None
        else DRAWDOWN_BRAKE_THRESHOLD_PCT
    )

    result = await db.execute(stmt)
    snapshots = result.scalars().all()

    if not snapshots:
        return _empty(period, threshold, bucket_id)

    # Build TWR wealth index: cash-flow-adjusted daily returns so that
    # Einzahlungen/Auszahlungen keinen Drawdown vortaeuschen.
    # Convention: net_cash_flow_chf is included in total_value_chf for that day.
    # Pure return day t = (V_t - NetCF_t) / V_{t-1}.
    series: list[tuple[date, float, float]] = []  # (date, wealth_index, raw_value)
    prev_value = float(snapshots[0].total_value_chf or 0)
    wealth = 1.0
    series.append((snapshots[0].date, wealth, prev_value))
    for snap in snapshots[1:]:
        value = float(snap.total_value_chf or 0)
        netcf = float(snap.net_cash_flow_chf or 0)
        if prev_value > 0:
            ret_factor = (value - netcf) / prev_value
            if ret_factor > 0:
                wealth *= ret_factor
        series.append((snap.date, wealth, value))
        prev_value = value

    out = {
        "period": period,
        "snapshots_count": len(snapshots),
        **_running_peak_drawdown(series, threshold),
        "bucket_id": str(bucket_id),
    }
    return out


async def get_max_drawdown(
    db: AsyncSession,
    user_id: uuid.UUID,
    period: str = "ytd",
    *,
    bucket_id: uuid.UUID | None = None,
    brake_threshold_pct: float | None = None,
) -> dict:
    """Compute max drawdown (peak-to-trough) over the period.

    Portfolio-level (kein bucket_id) leitet aus der ``/performance/history``-
    Kurve (portfolio_indexed) ab — konsistent mit jenem Endpoint, kein
    Phantom-Drawdown aus rohen PortfolioSnapshot-Werten.

    Bucket-level (``bucket_id`` gesetzt) rechnet unveraendert auf
    BucketSnapshot, mit ``brake_threshold_pct`` als Override (Default 6%).
    """
    if period not in _VALID_PERIODS:
        raise ValueError(f"Ungueltige Periode: {period}")

    today = date.today()
    start = _period_start(period, today)

    if bucket_id is None:
        return await _portfolio_drawdown(db, user_id, period, start, today)
    return await _bucket_drawdown(
        db, user_id, period, start, bucket_id, brake_threshold_pct
    )
