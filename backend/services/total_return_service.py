"""Total return calculation: unrealized + realized + dividends - fees - taxes."""
import logging
import uuid
from datetime import date

from sqlalchemy import func, select, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from models.portfolio_snapshot import PortfolioSnapshot
from models.position import Position
from models.transaction import Transaction, TransactionType
from services.portfolio_service import get_portfolio_summary

logger = logging.getLogger(__name__)


async def get_total_return(db: AsyncSession, user_id: uuid.UUID | None = None, summary: dict | None = None) -> dict:
    """Aggregate total return from all components."""
    if summary is None:
        summary = await get_portfolio_summary(db, user_id=user_id)

    # Exclude private_equity from unrealized P&L (not part of liquid performance)
    pe_pnl = sum(
        p.get("pnl_chf", 0) or 0
        for p in summary.get("positions", [])
        if p.get("type") == "private_equity"
    )
    unrealized_pnl_chf = summary["total_pnl_chf"] - pe_pnl

    # Build user-scoped base filter for transactions
    def _user_filter(q):
        if user_id is not None:
            return q.where(Transaction.user_id == user_id)
        return q

    # Realized P&L (from sell transactions with computed realized_pnl_chf)
    result = await db.execute(_user_filter(
        select(func.coalesce(func.sum(Transaction.realized_pnl_chf), 0))
        .where(Transaction.type == TransactionType.sell)
    ))
    realized_pnl_chf = float(result.scalar())

    # Dividends
    result = await db.execute(_user_filter(
        select(
            func.coalesce(func.sum(Transaction.total_chf), 0),
            func.coalesce(func.sum(Transaction.gross_amount), 0),
            func.coalesce(func.sum(Transaction.tax_amount), 0),
        )
        .where(Transaction.type == TransactionType.dividend)
    ))
    div_row = result.one()
    dividends_net_chf = float(div_row[0])
    dividends_gross_chf = float(div_row[1]) if div_row[1] else dividends_net_chf
    dividends_tax_chf = float(div_row[2]) if div_row[2] else 0.0

    # Capital gains (fund distributions)
    result = await db.execute(_user_filter(
        select(func.coalesce(func.sum(Transaction.total_chf), 0))
        .where(Transaction.type == TransactionType.capital_gain)
    ))
    capital_gains_dist_chf = float(result.scalar())

    # Interest
    result = await db.execute(_user_filter(
        select(func.coalesce(func.sum(Transaction.total_chf), 0))
        .where(Transaction.type == TransactionType.interest)
    ))
    interest_chf = float(result.scalar())

    # Trading fees (on buy/sell transactions)
    result = await db.execute(_user_filter(
        select(func.coalesce(func.sum(Transaction.fees_chf), 0))
        .where(Transaction.type.in_([TransactionType.buy, TransactionType.sell]))
    ))
    trading_fees_chf = float(result.scalar())

    # Other fees (standalone fee transactions)
    result = await db.execute(_user_filter(
        select(func.coalesce(func.sum(func.abs(Transaction.total_chf)), 0))
        .where(Transaction.type == TransactionType.fee)
    ))
    other_fees_chf = float(result.scalar())

    total_fees_chf = trading_fees_chf + other_fees_chf

    # Total return = unrealized + realized + dividends + capital_gains_dist + interest - fees
    # Note: fees on sell transactions are already deducted from realized_pnl_chf,
    # and fees on buy transactions are included in cost_basis (via total_chf).
    # So we don't subtract trading_fees again — only standalone fees.
    total_return_chf = (
        unrealized_pnl_chf
        + realized_pnl_chf
        + dividends_net_chf
        + capital_gains_dist_chf
        + interest_chf
        - other_fees_chf
    )

    # Exclude private_equity from invested total (not part of liquid performance)
    pe_invested = sum(
        p.get("cost_basis_chf", 0) or 0
        for p in summary.get("positions", [])
        if p.get("type") == "private_equity"
    )
    total_invested = summary["total_invested_chf"] - pe_invested

    # All-time return % via XIRR (annualized, money-weighted)
    from services.performance_history_service import calculate_xirr_for_period
    first_snap_result = await db.execute(
        select(PortfolioSnapshot.date)
        .where(PortfolioSnapshot.user_id == user_id)
        .order_by(PortfolioSnapshot.date.asc())
        .limit(1)
    )
    first_snap_date = first_snap_result.scalar()
    today = date.today()

    if first_snap_date:
        alltime_xirr = await calculate_xirr_for_period(db, user_id, first_snap_date, today)
        if alltime_xirr is not None:
            total_return_pct = round(alltime_xirr * 100, 2)
        else:
            total_return_pct = (total_return_chf / total_invested * 100) if total_invested > 0 else 0
    else:
        total_return_pct = (total_return_chf / total_invested * 100) if total_invested > 0 else 0

    # YTD performance via XIRR
    ytd = await _calc_ytd(db, user_id, unrealized_pnl_chf)

    return {
        "unrealized_pnl_chf": round(unrealized_pnl_chf, 2),
        "realized_pnl_chf": round(realized_pnl_chf, 2),
        "dividends_net_chf": round(dividends_net_chf, 2),
        "dividends_gross_chf": round(dividends_gross_chf, 2),
        "dividends_tax_chf": round(dividends_tax_chf, 2),
        "capital_gains_dist_chf": round(capital_gains_dist_chf, 2),
        "interest_chf": round(interest_chf, 2),
        "trading_fees_chf": round(trading_fees_chf, 2),
        "other_fees_chf": round(other_fees_chf, 2),
        "total_fees_chf": round(total_fees_chf, 2),
        "total_return_chf": round(total_return_chf, 2),
        "total_invested_chf": round(total_invested, 2),
        "total_return_pct": round(total_return_pct, 2),
        **ytd,
    }


async def _calc_ytd(db: AsyncSession, user_id, current_unrealized: float) -> dict:
    """Calculate YTD performance with breakdown: unrealized, realized, dividends."""
    today = date.today()
    year_start = date(today.year, 1, 1)
    null_result = {
        "ytd_chf": None, "ytd_pct": None, "ytd_year": today.year,
        "ytd_unrealized_chf": None, "ytd_realized_chf": None, "ytd_dividends_chf": None,
    }

    # --- TTWROR from snapshots (for ytd_pct) ---
    dec_start = date(today.year - 1, 12, 1)
    query = (
        select(PortfolioSnapshot)
        .where(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.date >= dec_start,
        )
        .order_by(PortfolioSnapshot.date.asc())
    )
    result = await db.execute(query)
    snapshots = result.scalars().all()

    if not snapshots:
        return null_result

    baseline_snap = None
    ytd_snapshots = []
    for snap in snapshots:
        if snap.date < year_start:
            baseline_snap = snap
        else:
            ytd_snapshots.append(snap)

    if baseline_snap is None or not ytd_snapshots:
        return null_result

    baseline_value = float(baseline_snap.total_value_chf)
    if baseline_value <= 0:
        return null_result

    # YTD via XIRR (geldgewichtete Rendite)
    from services.performance_history_service import calculate_xirr_for_period, deannualize_xirr
    current_year = today.year
    xirr_rate = await calculate_xirr_for_period(
        db, user_id, date(current_year - 1, 12, 31), today
    )
    if xirr_rate is not None:
        days_ytd = (today - date(current_year, 1, 1)).days
        ytd_pct = round(deannualize_xirr(xirr_rate * 100, days_ytd), 2)
    else:
        # Fallback: simple return
        current_value = float(ytd_snapshots[-1].total_value_chf) if ytd_snapshots else 0
        ytd_pct = round(((current_value / baseline_value) - 1) * 100, 2) if baseline_value > 0 else 0.0

    # --- Breakdown: unrealized, realized, dividends ---

    def _user_filter(q):
        if user_id is not None:
            return q.where(Transaction.user_id == user_id)
        return q

    # YTD Realized: sells in current year
    result = await db.execute(_user_filter(
        select(func.coalesce(func.sum(Transaction.realized_pnl_chf), 0))
        .where(Transaction.type == TransactionType.sell)
        .where(Transaction.date >= year_start)
    ))
    ytd_realized = float(result.scalar())

    # YTD Dividends: dividends in current year
    result = await db.execute(_user_filter(
        select(func.coalesce(func.sum(Transaction.total_chf), 0))
        .where(Transaction.type == TransactionType.dividend)
        .where(Transaction.date >= year_start)
    ))
    ytd_dividends = float(result.scalar())

    # YTD Unrealized: current unrealized P&L minus unrealized P&L at year-end
    # Unrealized at year-end = baseline portfolio value - cost basis at that time
    # We approximate: ytd_total - ytd_realized - ytd_dividends = ytd_unrealized
    current_value = float(ytd_snapshots[-1].total_value_chf)
    total_cf = sum(float(s.net_cash_flow_chf) for s in ytd_snapshots)
    ytd_total = round(current_value - baseline_value - total_cf, 2)
    ytd_unrealized = round(ytd_total - ytd_realized - ytd_dividends, 2)

    return {
        "ytd_chf": ytd_total,
        "ytd_pct": ytd_pct,
        "ytd_year": today.year,
        "ytd_unrealized_chf": ytd_unrealized,
        "ytd_realized_chf": round(ytd_realized, 2),
        "ytd_dividends_chf": round(ytd_dividends, 2),
    }


async def get_realized_gains(db: AsyncSession, user_id: uuid.UUID | None = None) -> dict:
    """List all realized gains from sell transactions, grouped by position."""
    pos_query = select(Position)
    if user_id is not None:
        pos_query = pos_query.where(Position.user_id == user_id)
    result = await db.execute(pos_query)
    positions = {str(p.id): p for p in result.scalars().all()}

    # Get all sell transactions with realized P&L
    sell_query = (
        select(Transaction)
        .where(Transaction.type == TransactionType.sell)
        .where(Transaction.realized_pnl_chf.isnot(None))
    )
    if user_id is not None:
        sell_query = sell_query.where(Transaction.user_id == user_id)
    sell_query = sell_query.order_by(Transaction.date.desc())
    result = await db.execute(sell_query)
    sells = result.scalars().all()

    # Get first buy date per position for context
    buy_query = (
        select(Transaction.position_id, func.min(Transaction.date))
        .where(Transaction.type == TransactionType.buy)
        .group_by(Transaction.position_id)
    )
    result = await db.execute(buy_query)
    first_buy = {str(pid): d for pid, d in result}

    items = []
    total = 0.0
    for txn in sells:
        pos = positions.get(str(txn.position_id))
        if not pos:
            continue
        rpnl = float(txn.realized_pnl_chf)
        cost = float(txn.cost_basis_at_sale) if txn.cost_basis_at_sale else 0
        proceeds = float(txn.total_chf)
        pct = (rpnl / cost * 100) if cost > 0 else 0

        buy_date = first_buy.get(str(txn.position_id))
        holding_days = (txn.date - buy_date).days if buy_date else None

        items.append({
            "transaction_id": str(txn.id),
            "order_id": txn.order_id,
            "ticker": pos.ticker,
            "name": pos.name,
            "buy_date": buy_date.isoformat() if buy_date else None,
            "sell_date": txn.date.isoformat(),
            "shares": float(txn.shares),
            "cost_basis_chf": round(cost, 2),
            "proceeds_chf": round(proceeds, 2),
            "fees_chf": round(float(txn.fees_chf), 2),
            "realized_pnl_chf": round(rpnl, 2),
            "realized_pnl_pct": round(pct, 2),
            "holding_period_days": holding_days,
        })
        total += rpnl

    return {
        "positions": items,
        "total_realized_pnl_chf": round(total, 2),
    }


async def get_fee_summary(db: AsyncSession, user_id: uuid.UUID | None = None) -> dict:
    """Monthly breakdown of trading fees, other fees, and taxes."""
    pos_query = select(Position.id)
    if user_id is not None:
        pos_query = pos_query.where(Position.user_id == user_id)
    pos_ids_subq = pos_query.subquery()

    # Monthly aggregation
    month_expr = func.date_trunc("month", Transaction.date)
    result = await db.execute(
        select(
            func.extract("year", Transaction.date).label("year"),
            func.extract("month", Transaction.date).label("month"),
            # Trading fees (on buy/sell)
            func.coalesce(func.sum(
                case(
                    (Transaction.type.in_([TransactionType.buy, TransactionType.sell]), Transaction.fees_chf),
                    else_=literal_column("0"),
                )
            ), 0).label("trading_fees"),
            # Standalone fees
            func.coalesce(func.sum(
                case(
                    (Transaction.type == TransactionType.fee, func.abs(Transaction.total_chf)),
                    else_=literal_column("0"),
                )
            ), 0).label("other_fees"),
            # Taxes (withholding on dividends + standalone tax transactions)
            func.coalesce(func.sum(
                case(
                    (Transaction.type == TransactionType.dividend, Transaction.taxes_chf),
                    (Transaction.type == TransactionType.tax, func.abs(Transaction.total_chf)),
                    else_=literal_column("0"),
                )
            ), 0).label("taxes"),
        )
        .where(Transaction.position_id.in_(select(pos_ids_subq.c.id)))
        .group_by(func.extract("year", Transaction.date), func.extract("month", Transaction.date))
        .order_by(func.extract("year", Transaction.date), func.extract("month", Transaction.date))
    )
    rows = result.all()

    by_month = []
    total_trading = 0.0
    total_other = 0.0
    total_taxes = 0.0
    for row in rows:
        tf = float(row.trading_fees)
        of = float(row.other_fees)
        tx = float(row.taxes)
        if tf == 0 and of == 0 and tx == 0:
            continue
        by_month.append({
            "year": int(row.year),
            "month": int(row.month),
            "trading_fees_chf": round(tf, 2),
            "other_fees_chf": round(of, 2),
            "taxes_chf": round(tx, 2),
        })
        total_trading += tf
        total_other += of
        total_taxes += tx

    return {
        "by_month": by_month,
        "total_trading_fees_chf": round(total_trading, 2),
        "total_other_fees_chf": round(total_other, 2),
        "total_taxes_chf": round(total_taxes, 2),
    }
