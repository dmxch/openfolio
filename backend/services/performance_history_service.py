"""Monthly returns (Modified Dietz) + annual returns (XIRR/MWR)."""
import calendar
import logging
import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.portfolio_snapshot import PortfolioSnapshot
from models.transaction import Transaction, TransactionType
from services import cache

logger = logging.getLogger(__name__)

CACHE_TTL = 900  # 15 min

# Cashflow types
INFLOW_TYPES = {TransactionType.buy, TransactionType.deposit, TransactionType.delivery_in}
OUTFLOW_TYPES = {TransactionType.sell, TransactionType.withdrawal, TransactionType.delivery_out}


# --- XIRR (Extended Internal Rate of Return) ---

def xirr(cashflows: list[tuple[date, float]], guess: float = 0.1, max_iter: int = 100, tol: float = 1e-7) -> float | None:
    """Compute XIRR via Newton-Raphson with bisection fallback.

    Args:
        cashflows: List of (date, amount). First = negative start value, last = positive end value.
        guess: Initial rate estimate.

    Returns:
        Annualized rate as decimal (0.05 = 5%), or None if no convergence.
    """
    if not cashflows or len(cashflows) < 2:
        return None

    d0 = cashflows[0][0]

    def npv(rate):
        if rate <= -1:
            return float('inf')
        return sum(cf / (1 + rate) ** ((d - d0).days / 365.0) for d, cf in cashflows)

    def npv_deriv(rate):
        if rate <= -1:
            return float('inf')
        return sum(
            -((d - d0).days / 365.0) * cf / (1 + rate) ** ((d - d0).days / 365.0 + 1)
            for d, cf in cashflows
        )

    # Newton-Raphson
    rate = guess
    for _ in range(max_iter):
        f = npv(rate)
        df = npv_deriv(rate)
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        if abs(new_rate - rate) < tol:
            return new_rate
        rate = new_rate
        if rate <= -1:
            rate = -0.99

    # Bisection fallback
    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            return mid
    return (lo + hi) / 2


def deannualize_xirr(annualized_rate_pct: float, days: int) -> float:
    """Convert annualized XIRR to period return for periods < 1 year."""
    if days <= 0:
        return 0.0
    return ((1 + annualized_rate_pct / 100) ** (days / 365.0) - 1) * 100


async def calculate_xirr_for_period(
    db: AsyncSession, user_id: uuid.UUID, start_date: date, end_date: date,
    all_snapshots: list | None = None, all_transactions: list | None = None,
) -> float | None:
    """Calculate XIRR for a given period using snapshots and transactions.

    Accepts optional pre-loaded snapshots/transactions to avoid redundant DB queries (M-3).
    """
    if all_snapshots is None:
        result = await db.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.user_id == user_id)
            .order_by(PortfolioSnapshot.date.asc())
        )
        all_snapshots = result.scalars().all()

    if all_transactions is None:
        result = await db.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.date.asc())
        )
        all_transactions = result.scalars().all()

    return _calculate_xirr_from_data(all_snapshots, all_transactions, start_date, end_date)


def _calculate_xirr_from_data(
    all_snapshots: list, all_transactions: list,
    start_date: date, end_date: date
) -> float | None:
    """Calculate XIRR for a given period using pre-loaded snapshots and transactions."""
    # Start value (last snapshot before period)
    start_snap = None
    for snap in reversed(all_snapshots):
        if snap.date <= start_date:
            start_snap = snap
            break
    start_value = float(start_snap.total_value_chf) if start_snap else 0

    # End value (last snapshot on or before end_date)
    end_snap = None
    for snap in reversed(all_snapshots):
        if snap.date <= end_date:
            end_snap = snap
            break
    if not end_snap:
        return None
    end_value = float(end_snap.total_value_chf)

    if start_value <= 0 and end_value <= 0:
        return None

    # Transactions in period
    transactions = [t for t in all_transactions if start_date < t.date <= end_date]

    # Snapshot cashflows in period
    snap_cfs = [(s.date, s.net_cash_flow_chf) for s in all_snapshots if start_date < s.date <= end_date]

    # Build transaction-based cashflow by date
    txn_cf_by_date = defaultdict(float)
    for txn in transactions:
        if txn.type in INFLOW_TYPES:
            txn_cf_by_date[txn.date] -= float(txn.total_chf)  # money in = negative CF for XIRR
        elif txn.type in OUTFLOW_TYPES:
            txn_cf_by_date[txn.date] += float(txn.total_chf)  # money out = positive CF
        elif txn.type == TransactionType.dividend:
            txn_cf_by_date[txn.date] += float(txn.total_chf)  # dividend = positive CF

    # Build snapshot-based cashflow by date (for manual changes)
    snap_cf_by_date = {}
    for snap_date, snap_cf in snap_cfs:
        cf_val = float(snap_cf)
        if abs(cf_val) > 0:
            # Snapshot CFs: positive = inflow (buy), negative = outflow (sell)
            # For XIRR: inflow = negative, outflow = positive (inverted)
            snap_cf_by_date[snap_date] = -cf_val

    # Merge: use snapshot CF if it captures more than transactions on that date
    all_dates = set(txn_cf_by_date.keys()) | set(snap_cf_by_date.keys())
    cashflows = [(start_snap.date if start_snap else start_date, -start_value)]

    for d in sorted(all_dates):
        txn_val = txn_cf_by_date.get(d, 0)
        snap_val = snap_cf_by_date.get(d, 0)
        # Use the one with larger absolute value
        cf = snap_val if abs(snap_val) > abs(txn_val) * 1.1 else txn_val
        if abs(cf) > 0:
            cashflows.append((d, cf))

    cashflows.append((end_snap.date, end_value))
    cashflows.sort(key=lambda x: x[0])

    rate = xirr(cashflows)
    return rate


async def get_monthly_returns(db: AsyncSession, user_id: uuid.UUID | None = None) -> dict | list:
    """Returns monthly Modified Dietz returns + annual XIRR totals.

    Response format: {"months": [...], "annual_totals": {2024: -5.2, ...}}
    Falls cached als list (alter Format): wrapped in dict.
    """
    cache_key = f"monthly_returns:{user_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Find earliest transaction date (user-scoped directly)
    if user_id is not None:
        result = await db.execute(
            select(func.min(Transaction.date))
            .where(Transaction.user_id == user_id)
        )
    else:
        result = await db.execute(select(func.min(Transaction.date)))
    earliest = result.scalar()
    if not earliest:
        return {"months": [], "annual_totals": {}}

    # Try Modified Dietz from snapshots + transactions
    month_returns = await _monthly_returns_modified_dietz(db, user_id, earliest)
    if not month_returns:
        # Fallback below
        pass
    else:
        # Calculate annual XIRR totals — load all data once, then filter per year
        years = sorted(set(m["year"] for m in month_returns))
        annual_totals = {}
        today = date.today()

        # Pre-load all snapshots and transactions for XIRR calculations
        snap_result = await db.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.user_id == user_id)
            .order_by(PortfolioSnapshot.date.asc())
        )
        all_snapshots = snap_result.scalars().all()

        txn_result = await db.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.date.asc())
        )
        all_transactions = txn_result.scalars().all()

        for year in years:
            start = date(year - 1, 12, 31)
            end = date(year, 12, 31) if year < today.year else today
            rate = _calculate_xirr_from_data(all_snapshots, all_transactions, start, end)
            if rate is not None:
                if year == today.year:
                    # De-annualize for current year (partial year)
                    days = (end - date(year, 1, 1)).days
                    annual_totals[year] = round(deannualize_xirr(rate * 100, days), 2)
                else:
                    annual_totals[year] = round(rate * 100, 2)
            else:
                # Fallback: compound Modified Dietz months
                compound = 1.0
                for m in month_returns:
                    if m["year"] == year:
                        compound *= (1 + m["return_pct"] / 100)
                annual_totals[year] = round((compound - 1) * 100, 2)

        result_data = {"months": month_returns, "annual_totals": annual_totals}
        cache.set(cache_key, result_data, CACHE_TTL)
        return result_data

    # Fallback: empty result
    return {"months": [], "annual_totals": {}}


async def _monthly_returns_modified_dietz(
    db: AsyncSession, user_id, earliest: date
) -> list[dict]:
    """Calculate monthly returns using Modified Dietz method.

    R = (V_end - V_start - sum(CF)) / (V_start + sum(w_i * CF_i))

    Where w_i = (days_in_month - day_of_cashflow) / days_in_month
    weights cashflows by how long they were invested during the month.
    """
    # Load all snapshots
    query = select(PortfolioSnapshot).where(
        PortfolioSnapshot.user_id == user_id,
        PortfolioSnapshot.date >= earliest,
    ).order_by(PortfolioSnapshot.date.asc())
    result = await db.execute(query)
    snapshots = result.scalars().all()

    if len(snapshots) < 2:
        return []

    # Load all transactions for cashflow calculation
    txn_query = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.date >= earliest,
    ).order_by(Transaction.date.asc())
    txn_result = await db.execute(txn_query)
    all_txns = txn_result.scalars().all()

    # Group transactions by (year, month)
    txns_by_month = defaultdict(list)
    for txn in all_txns:
        key = (txn.date.year, txn.date.month)
        txns_by_month[key].append(txn)

    # Group snapshots by (year, month) — need first and last per month
    snapshots_by_month = defaultdict(list)
    for snap in snapshots:
        key = (snap.date.year, snap.date.month)
        snapshots_by_month[key].append(snap)

    sorted_months = sorted(snapshots_by_month.keys())
    returns = []
    prev_month_end_value = None

    for year, month in sorted_months:
        month_snapshots = snapshots_by_month[(year, month)]
        month_end_value = float(month_snapshots[-1].total_value_chf)

        # Start value: last snapshot of previous month, or first snapshot of this month
        if prev_month_end_value is not None:
            month_start_value = prev_month_end_value
        else:
            # First month — use first snapshot as start
            month_start_value = float(month_snapshots[0].total_value_chf)
            if len(month_snapshots) < 2:
                prev_month_end_value = month_end_value
                returns.append({"year": year, "month": month, "return_pct": 0.0})
                continue

        days_in_month = calendar.monthrange(year, month)[1]

        # Calculate cashflows from TWO sources:
        # 1. Transactions (buys/sells/deposits/withdrawals)
        # 2. Snapshot net_cash_flow_chf (catches manual position changes not in transactions)
        # Use the LARGER of the two to ensure all value changes are accounted for.

        # Source 1: Transaction-based cashflows
        txn_cf_total = 0.0
        txn_cf_weighted = 0.0
        txn_cf_by_day = defaultdict(float)

        for txn in txns_by_month.get((year, month), []):
            if txn.type in INFLOW_TYPES:
                cf = float(txn.total_chf)
            elif txn.type in OUTFLOW_TYPES:
                cf = -float(txn.total_chf)
            else:
                continue

            day_of_month = txn.date.day - 1  # 0-based
            weight = (days_in_month - day_of_month) / days_in_month

            txn_cf_total += cf
            txn_cf_weighted += weight * cf
            txn_cf_by_day[txn.date.day] += cf

        # Source 2: Snapshot-based cashflows (includes manual changes)
        snap_cf_total = 0.0
        snap_cf_weighted = 0.0
        for snap in month_snapshots:
            cf = float(snap.net_cash_flow_chf)
            if abs(cf) > 0:
                day_of_month = snap.date.day - 1
                weight = (days_in_month - day_of_month) / days_in_month
                snap_cf_total += cf
                snap_cf_weighted += weight * cf

        # Use snapshot cashflows if they capture more (manual additions not in transactions)
        if abs(snap_cf_total) > abs(txn_cf_total) * 1.1:
            total_cf = snap_cf_total
            weighted_cf = snap_cf_weighted
        else:
            total_cf = txn_cf_total
            weighted_cf = txn_cf_weighted

        # Modified Dietz formula
        denominator = month_start_value + weighted_cf

        if abs(denominator) < 100:
            # Extreme case: nearly all money moved in/out
            # Fallback to simple return
            if month_start_value > 100:
                return_pct = ((month_end_value - month_start_value) / month_start_value) * 100
            else:
                return_pct = 0.0
        else:
            return_pct = ((month_end_value - month_start_value - total_cf) / denominator) * 100

        # Sanity cap: monthly returns beyond ±50% are suspicious but possible (crypto)
        # Don't cap, but log for awareness
        if abs(return_pct) > 50:
            logger.info(
                f"High monthly return {year}-{month:02d}: {return_pct:.1f}% "
                f"(start={month_start_value:.0f}, end={month_end_value:.0f}, cf={total_cf:.0f})"
            )

        returns.append({"year": year, "month": month, "return_pct": round(return_pct, 2)})
        prev_month_end_value = month_end_value

    return returns
