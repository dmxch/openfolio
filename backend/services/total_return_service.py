"""Total return calculation: unrealized + realized + dividends - fees - taxes."""
import logging
import uuid
from datetime import date

from sqlalchemy import and_, func, select, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from models.portfolio_snapshot import PortfolioSnapshot
from models.position import Position
from models.transaction import Transaction, TransactionType
from services import cache
from services.portfolio_service import (
    get_portfolio_summary,
    get_portfolio_summary_cached,
    portfolio_cache_version,
    single_flight,
)

logger = logging.getLogger(__name__)

# So lange wie die Summary, aus der unrealized_pnl stammt.
TOTAL_RETURN_CACHE_TTL = 60


def _sum_if(condition, expr):
    """``COALESCE(SUM(expr) FILTER (WHERE condition), 0)``, portabel als CASE."""
    return func.coalesce(func.sum(case((condition, expr))), 0)


async def get_total_return(db: AsyncSession, user_id: uuid.UUID | None = None, summary: dict | None = None) -> dict:
    """Aggregate total return from all components.

    Ohne übergebene ``summary`` kommt das Ergebnis für 60 Sekunden aus dem
    Cache; Buchungen und Snapshot-Regen entwerten es über die Versionsmarke.
    """
    if summary is not None or user_id is None:
        return await _compute_total_return(db, user_id, summary)

    cache_key = f"total_return:{user_id}:v{portfolio_cache_version(user_id)}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    async def _compute() -> dict:
        result = await _compute_total_return(db, user_id, None)
        cache.set(cache_key, result, ttl=TOTAL_RETURN_CACHE_TTL)
        return result

    # Die Performance-Seite ruft die Route je Aufbau zweimal parallel auf.
    return await single_flight(cache_key, _compute)


async def _compute_total_return(db: AsyncSession, user_id: uuid.UUID | None, summary: dict | None) -> dict:
    if summary is None:
        if user_id is None:
            summary = await get_portfolio_summary(db, user_id=user_id)
        else:
            summary = await get_portfolio_summary_cached(db, user_id)

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

    today = date.today()
    year_start = date(today.year, 1, 1)
    is_sell = Transaction.type == TransactionType.sell
    is_dividend = Transaction.type == TransactionType.dividend

    # Alle Summen in EINER Abfrage (K061: vorher acht Einzelabfragen über
    # dieselben Zeilen). Je Summe dieselbe Bedingung wie zuvor im WHERE.
    #
    # Dividends. gross_amount/tax_amount sind in TRANSAKTIONSWÄHRUNG
    # gespeichert (Parser: total_chf = (gross - tax) × fx) — für die
    # _chf-Ausgabe MUSS mit fx_rate_to_chf multipliziert werden, sonst
    # werden USD-Beträge als CHF ausgewiesen (Review 2026-06-10, M2).
    # Bug-Fix in der Aggregation, Semantik (net via total_chf) unverändert.
    # Rows ohne gross_amount gehen mit ihrem Netto (total_chf, bereits CHF)
    # in die Gross-Summe ein — sonst faellt die Row aus der SUM und
    # gross < net wird moeglich (Review 2026-07-02, LOW).
    sums = (await db.execute(_user_filter(
        select(
            # Realized P&L (from sell transactions with computed realized_pnl_chf)
            _sum_if(is_sell, Transaction.realized_pnl_chf),
            _sum_if(is_dividend, Transaction.total_chf),
            _sum_if(
                is_dividend,
                func.coalesce(
                    Transaction.gross_amount * func.coalesce(Transaction.fx_rate_to_chf, 1),
                    Transaction.total_chf,
                ),
            ),
            _sum_if(
                is_dividend,
                Transaction.tax_amount * func.coalesce(Transaction.fx_rate_to_chf, 1),
            ),
            # Capital gains (fund distributions)
            _sum_if(Transaction.type == TransactionType.capital_gain, Transaction.total_chf),
            # Interest
            _sum_if(Transaction.type == TransactionType.interest, Transaction.total_chf),
            # Trading fees (on buy/sell transactions)
            _sum_if(
                Transaction.type.in_([TransactionType.buy, TransactionType.sell]),
                Transaction.fees_chf,
            ),
            # Other fees (standalone fee transactions)
            _sum_if(Transaction.type == TransactionType.fee, func.abs(Transaction.total_chf)),
            # YTD: sells und Dividenden des laufenden Jahres (für _calc_ytd)
            _sum_if(and_(is_sell, Transaction.date >= year_start), Transaction.realized_pnl_chf),
            _sum_if(and_(is_dividend, Transaction.date >= year_start), Transaction.total_chf),
        )
    ))).one()
    realized_pnl_chf = float(sums[0])
    dividends_net_chf = float(sums[1])
    dividends_gross_chf = float(sums[2]) if sums[2] else dividends_net_chf
    dividends_tax_chf = float(sums[3]) if sums[3] else 0.0
    capital_gains_dist_chf = float(sums[4])
    interest_chf = float(sums[5])
    trading_fees_chf = float(sums[6])
    other_fees_chf = float(sums[7])
    ytd_realized = float(sums[8])
    ytd_dividends = float(sums[9])

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

    # Invariante #2: private_equity UND Vorsorge (pension) zaehlen NICHT zur
    # liquiden Performance — aus der invested-Basis des Fallback-Renditeprozents
    # ausschliessen. PE nutzt cost_basis_chf (CHF); fuer pension wurde im Summary
    # der FX-konvertierte Saldo (market_value_chf) als invested gezaehlt
    # (portfolio_service: invested = market_value_chf bei cash/pension), daher den
    # abziehen — NICHT cost_basis_chf (das ist bei pension der Roh-Saldo in
    # Fremdwaehrung). real_estate (shares=0) ist bereits aus dem Summary gefiltert,
    # und pension-PnL ist 0, daher bleibt der Zaehler konsistent.
    pe_invested = sum(
        p.get("cost_basis_chf", 0) or 0
        for p in summary.get("positions", [])
        if p.get("type") == "private_equity"
    )
    pension_invested = sum(
        p.get("market_value_chf", 0) or 0
        for p in summary.get("positions", [])
        if p.get("type") == "pension"
    )
    total_invested = summary["total_invested_chf"] - pe_invested - pension_invested

    # All-time return % via XIRR (annualized, money-weighted). Snapshots und
    # Transaktionen einmal laden und an beide XIRR-Rechnungen (Gesamt und YTD)
    # weiterreichen — vorher lud jede alles neu, als ORM-Objekte (K061).
    from services.performance_history_service import calculate_xirr_for_period, load_return_inputs
    all_snapshots, all_transactions = await load_return_inputs(db, user_id)
    first_snap_date = all_snapshots[0].date if all_snapshots else None

    if first_snap_date:
        alltime_xirr = await calculate_xirr_for_period(
            db, user_id, first_snap_date, today,
            all_snapshots=all_snapshots, all_transactions=all_transactions,
        )
        if alltime_xirr is not None:
            total_return_pct = round(alltime_xirr * 100, 2)
        else:
            total_return_pct = (total_return_chf / total_invested * 100) if total_invested > 0 else 0
    else:
        total_return_pct = (total_return_chf / total_invested * 100) if total_invested > 0 else 0

    # YTD performance via XIRR
    ytd = await _calc_ytd(
        db, user_id, unrealized_pnl_chf,
        all_snapshots=all_snapshots, all_transactions=all_transactions,
        ytd_realized=ytd_realized, ytd_dividends=ytd_dividends,
    )

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


async def _calc_ytd(
    db: AsyncSession, user_id, current_unrealized: float,
    all_snapshots: list | None = None, all_transactions: list | None = None,
    ytd_realized: float | None = None, ytd_dividends: float | None = None,
) -> dict:
    """Calculate YTD performance with breakdown: unrealized, realized, dividends.

    Die optionalen Parameter sind vorab geladene Daten des Aufrufers
    (``load_return_inputs`` und die YTD-Summen). Ohne sie lädt die Funktion selbst.
    """
    today = date.today()
    year_start = date(today.year, 1, 1)
    null_result = {
        "ytd_chf": None, "ytd_pct": None, "ytd_year": today.year,
        "ytd_unrealized_chf": None, "ytd_realized_chf": None, "ytd_dividends_chf": None,
    }

    # --- TTWROR from snapshots (for ytd_pct) ---
    dec_start = date(today.year - 1, 12, 1)
    if all_snapshots is not None:
        snapshots = [s for s in all_snapshots if s.date >= dec_start]
    else:
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
        db, user_id, date(current_year - 1, 12, 31), today,
        all_snapshots=all_snapshots, all_transactions=all_transactions,
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
    if ytd_realized is None:
        result = await db.execute(_user_filter(
            select(func.coalesce(func.sum(Transaction.realized_pnl_chf), 0))
            .where(Transaction.type == TransactionType.sell)
            .where(Transaction.date >= year_start)
        ))
        ytd_realized = float(result.scalar())

    # YTD Dividends: dividends in current year
    if ytd_dividends is None:
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


async def get_realized_gains(
    db: AsyncSession,
    user_id: uuid.UUID | None = None,
    bucket_id: uuid.UUID | None = None,
) -> dict:
    """List all realized gains from sell transactions, grouped by position.

    bucket_id (optional): wenn gesetzt, nur Sells deren bucket_id_at_sale
    diesem Bucket entspricht. Snapshot zum Verkaufszeitpunkt, nicht der
    aktuelle Bucket der Position.
    """
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
    if bucket_id is not None:
        sell_query = sell_query.where(Transaction.bucket_id_at_sale == bucket_id)
    sell_query = sell_query.order_by(Transaction.date.desc())
    result = await db.execute(sell_query)
    sells = result.scalars().all()

    # Get first buy date per position for context.
    # User-Scoping (Review 2026-07-02, M25): ohne Filter war das ein
    # Full-Table-GROUP-BY ueber die Transaktionen ALLER User.
    buy_query = (
        select(Transaction.position_id, func.min(Transaction.date))
        .where(Transaction.type == TransactionType.buy)
        .group_by(Transaction.position_id)
    )
    if user_id is not None:
        buy_query = buy_query.where(Transaction.user_id == user_id)
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


async def get_bucket_total_return(
    db: AsyncSession,
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
    summary: dict | None = None,
) -> dict:
    """Bucket-scoped total-return breakdown (additive, non-protected helper).

    Bewusst getrennt von get_total_return(), damit der whole-portfolio-Pfad
    (HEILIGE Regel 11) byte-genau unveraendert bleibt. Attribution:
      - unrealized / invested: Positionen mit Position.bucket_id == bucket_id
      - realized P&L: Sells via Transaction.bucket_id_at_sale (Snapshot zum
        Verkauf, konsistent mit get_realized_gains)
      - Dividenden / Zinsen / Capital Gains / Gebuehren: ueber den aktuellen
        Bucket der Position (Position.bucket_id), konsistent mit Cashflows

    total_return_pct ist hier eine einfache Geld-auf-Geld-Rendite
    (total_return_chf / total_invested) — KEIN XIRR. Die zeitgewichtete
    Bucket-Rendite (TWR) liefert /buckets/{id}/benchmark-comparison +
    /monthly-returns. YTD-Breakdown bewusst ausgelassen (Bucket-Sektion zeigt
    YTD via benchmark-comparison?period=ytd).
    """
    if summary is None:
        summary = await get_portfolio_summary_cached(db, user_id)

    bstr = str(bucket_id)
    bucket_positions = [
        p for p in summary.get("positions", [])
        if p.get("bucket_id") == bstr and p.get("type") != "private_equity"
    ]
    unrealized_pnl_chf = sum((p.get("pnl_chf", 0) or 0) for p in bucket_positions)
    # invested = market_value_chf - pnl_chf rekonstruiert exakt das "invested",
    # das portfolio_service in total_invested_chf akkumuliert: fuer Aktien/ETF/
    # Crypto/Commodity ist das die cost_basis (= MV - PnL), fuer Cash/Vorsorge der
    # FX-konvertierte market_value (PnL = 0). NICHT rohes cost_basis_chf nehmen —
    # das ist fuer Cash/Vorsorge ein Fremdwaehrungs-Saldo, kein CHF (siehe
    # reference_cash_saldo_manual), und wuerde den Nenner verzerren, sobald ein
    # Fremdwaehrungs-Cash-Konto in einem liquiden Bucket liegt.
    total_invested = sum(
        ((p.get("market_value_chf", 0) or 0) - (p.get("pnl_chf", 0) or 0))
        for p in bucket_positions
    )

    # Positionen dieses Buckets (fuer Cashflow-Attribution ueber aktuellen Bucket)
    pos_ids_subq = (
        select(Position.id)
        .where(Position.user_id == user_id, Position.bucket_id == bucket_id)
        .subquery()
    )

    def _bucket_pos_filter(q):
        return q.where(Transaction.position_id.in_(select(pos_ids_subq.c.id)))

    # Realized P&L: Sells via bucket_id_at_sale (Snapshot zum Verkaufszeitpunkt)
    result = await db.execute(
        select(func.coalesce(func.sum(Transaction.realized_pnl_chf), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.type == TransactionType.sell)
        .where(Transaction.bucket_id_at_sale == bucket_id)
    )
    realized_pnl_chf = float(result.scalar())

    # Dividenden (gross/net/tax) — Attribution via aktuellen Bucket der Position.
    # NULL-gross-Rows zaehlen mit ihrem Netto in die Gross-Summe (gross >= net),
    # gleiche Logik wie im whole-portfolio-Pfad (Review 2026-07-02, LOW).
    result = await db.execute(_bucket_pos_filter(
        select(
            func.coalesce(func.sum(Transaction.total_chf), 0),
            func.coalesce(
                func.sum(
                    func.coalesce(
                        Transaction.gross_amount * func.coalesce(Transaction.fx_rate_to_chf, 1),
                        Transaction.total_chf,
                    )
                ), 0
            ),
            func.coalesce(
                func.sum(Transaction.tax_amount * func.coalesce(Transaction.fx_rate_to_chf, 1)), 0
            ),
        )
        .where(Transaction.user_id == user_id)
        .where(Transaction.type == TransactionType.dividend)
    ))
    div_row = result.one()
    dividends_net_chf = float(div_row[0])
    dividends_gross_chf = float(div_row[1]) if div_row[1] else dividends_net_chf
    dividends_tax_chf = float(div_row[2]) if div_row[2] else 0.0

    result = await db.execute(_bucket_pos_filter(
        select(func.coalesce(func.sum(Transaction.total_chf), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.type == TransactionType.capital_gain)
    ))
    capital_gains_dist_chf = float(result.scalar())

    result = await db.execute(_bucket_pos_filter(
        select(func.coalesce(func.sum(Transaction.total_chf), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.type == TransactionType.interest)
    ))
    interest_chf = float(result.scalar())

    result = await db.execute(_bucket_pos_filter(
        select(func.coalesce(func.sum(Transaction.fees_chf), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.type.in_([TransactionType.buy, TransactionType.sell]))
    ))
    trading_fees_chf = float(result.scalar())

    result = await db.execute(_bucket_pos_filter(
        select(func.coalesce(func.sum(func.abs(Transaction.total_chf)), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.type == TransactionType.fee)
    ))
    other_fees_chf = float(result.scalar())

    total_fees_chf = trading_fees_chf + other_fees_chf

    # Gleiche Formel-Struktur wie whole-portfolio: Trading-Fees stecken bereits
    # in realized_pnl (Sells) bzw. cost_basis (Buys); nur standalone Fees abziehen.
    total_return_chf = (
        unrealized_pnl_chf
        + realized_pnl_chf
        + dividends_net_chf
        + capital_gains_dist_chf
        + interest_chf
        - other_fees_chf
    )

    total_return_pct = (total_return_chf / total_invested * 100) if total_invested > 0 else 0.0

    return {
        "bucket_id": bstr,
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
        "is_money_weighted": False,
    }


async def get_fee_summary(
    db: AsyncSession,
    user_id: uuid.UUID | None = None,
    bucket_id: uuid.UUID | None = None,
) -> dict:
    """Monthly breakdown of trading fees, other fees, and taxes.

    bucket_id (optional): wenn gesetzt, nur Transaktionen von Positionen im
    angegebenen Bucket (aktueller Bucket der Position). Rein additiver Filter —
    der bucket_id=None-Pfad ist unveraendert (HEILIGE Regel 11).
    """
    pos_query = select(Position.id)
    if user_id is not None:
        pos_query = pos_query.where(Position.user_id == user_id)
    if bucket_id is not None:
        pos_query = pos_query.where(Position.bucket_id == bucket_id)
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
