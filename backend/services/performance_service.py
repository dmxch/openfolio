"""Performance waterfall with true TWR (sub-period chaining) and IRR (bisection)."""
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import Position
from models.transaction import Transaction, TransactionType
from services.portfolio_service import get_portfolio_summary
from services.history_service import get_portfolio_history

logger = logging.getLogger(__name__)


def _bisection_irr(cashflows: list[tuple[float, float]], tol=1e-6, max_iter=100) -> float:
    """Solve for IRR using bisection method.

    cashflows: list of (amount, year_fraction) where year_fraction = days/365.
    The first entry is typically -V_start (negative), last is +V_end.
    Returns annualized rate as percentage.
    """
    def npv(r):
        return sum(cf / (1 + r) ** t for cf, t in cashflows)

    lo, hi = -0.99, 10.0  # -99% to +1000%

    # Check if NPV has different signs at boundaries
    npv_lo = npv(lo)
    npv_hi = npv(hi)
    if npv_lo * npv_hi > 0:
        # No sign change — return simple approximation
        return 0.0

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        val = npv(mid)
        if abs(val) < tol:
            break
        if val * npv_lo > 0:
            lo = mid
            npv_lo = val
        else:
            hi = mid

    return mid * 100


async def get_performance_waterfall(db: AsyncSession, date_from: date, date_to: date) -> dict:
    # Get all transactions in period
    result = await db.execute(
        select(Transaction)
        .where(Transaction.date >= date_from, Transaction.date <= date_to)
        .order_by(Transaction.date.asc())
    )
    txns = result.scalars().all()

    deposits = 0.0
    withdrawals = 0.0
    dividends = 0.0
    fees = 0.0
    taxes = 0.0
    realized_gains = 0.0

    for txn in txns:
        t = txn.type
        total = float(txn.total_chf)
        txn_fees = float(txn.fees_chf)
        txn_taxes = float(txn.taxes_chf)

        fees += txn_fees
        taxes += txn_taxes

        if t == TransactionType.buy:
            deposits += total
        elif t == TransactionType.sell:
            realized_gains += total
        elif t == TransactionType.dividend:
            dividends += total
        elif t == TransactionType.fee:
            fees += total
        elif t == TransactionType.tax:
            taxes += total
        elif t == TransactionType.tax_refund:
            taxes -= total
        elif t == TransactionType.deposit:
            deposits += total
        elif t == TransactionType.withdrawal:
            withdrawals += total

    # Current portfolio value
    summary = await get_portfolio_summary(db)
    final_value = summary["total_market_value_chf"]
    total_invested = summary["total_invested_chf"]

    # Capital gains = current market value - total cost basis (unrealized)
    capital_gains = final_value - total_invested

    # Total return
    total_return = capital_gains + realized_gains + dividends - fees - taxes
    total_return_pct = (total_return / total_invested * 100) if total_invested > 0 else 0

    # --- True TWR via sub-period chaining using portfolio history ---
    twr_pct = await _compute_twr(db, txns, date_from, date_to)

    # --- IRR via bisection ---
    irr_pct = _compute_irr(txns, final_value, date_from, date_to)

    return {
        "initial_value": 0,
        "final_value": round(final_value, 2),
        "capital_gains": round(capital_gains, 2),
        "realized_gains": round(realized_gains, 2),
        "dividends": round(dividends, 2),
        "fees": round(-abs(fees), 2),
        "taxes": round(-abs(taxes), 2),
        "deposits": round(deposits, 2),
        "withdrawals": round(-abs(withdrawals), 2),
        "total_return_pct": round(total_return_pct, 2),
        "twr_pct": round(twr_pct, 2),
        "irr_pct": round(irr_pct, 2),
    }


async def _compute_twr(db: AsyncSession, txns, date_from: date, date_to: date) -> float:
    """Compute TWR using sub-period chaining at each external cashflow."""
    # Get daily portfolio history
    history = await get_portfolio_history(db, date_from, date_to, benchmark="")
    daily_values = {p["date"]: p["value"] for p in history.get("data", [])}

    if len(daily_values) < 2:
        return 0.0

    # Find external cashflow dates (deposits/withdrawals)
    external_flows = []
    for txn in txns:
        if txn.type in (TransactionType.deposit, TransactionType.withdrawal):
            flow = float(txn.total_chf)
            if txn.type == TransactionType.withdrawal:
                flow = -flow
            external_flows.append((txn.date.isoformat(), flow))

    if not external_flows:
        # No external flows — simple return
        sorted_dates = sorted(daily_values.keys())
        v_start = daily_values[sorted_dates[0]]
        v_end = daily_values[sorted_dates[-1]]
        return ((v_end / v_start) - 1) * 100 if v_start > 0 else 0.0

    # Sub-period chaining: at each cashflow, close the sub-period
    sorted_dates = sorted(daily_values.keys())
    twr_product = 1.0
    period_start_value = daily_values[sorted_dates[0]]

    # Group flows by date
    flow_by_date = {}
    for dt, flow in external_flows:
        flow_by_date[dt] = flow_by_date.get(dt, 0) + flow

    for dt in sorted_dates:
        if dt in flow_by_date and period_start_value > 0:
            # Value just before the cashflow
            v_before = daily_values[dt]
            sub_return = v_before / period_start_value
            twr_product *= sub_return
            # New period starts after the cashflow
            period_start_value = v_before + flow_by_date[dt]

    # Final sub-period
    if period_start_value > 0:
        v_end = daily_values[sorted_dates[-1]]
        twr_product *= v_end / period_start_value

    return (twr_product - 1) * 100


def _compute_irr(txns, final_value: float, date_from: date, date_to: date) -> float:
    """Compute IRR using bisection method."""
    total_days = (date_to - date_from).days
    if total_days <= 0:
        return 0.0

    # Build cashflows: negative = money in, positive = money out
    cashflows = []

    for txn in txns:
        t = txn.type
        total = float(txn.total_chf)
        days_from_start = (txn.date - date_from).days
        year_frac = days_from_start / 365.0

        if t in (TransactionType.buy, TransactionType.deposit):
            cashflows.append((-total, year_frac))  # money going in
        elif t in (TransactionType.sell, TransactionType.withdrawal):
            cashflows.append((total, year_frac))  # money coming out
        elif t == TransactionType.dividend:
            cashflows.append((total, year_frac))

    # Final value as terminal cashflow
    cashflows.append((final_value, total_days / 365.0))

    if not cashflows:
        return 0.0

    return _bisection_irr(cashflows)
