"""Daily portfolio snapshot for TTWROR tracking."""
import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import delete, select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models.portfolio_snapshot import PortfolioSnapshot
from models.position import Position, AssetType
from models.transaction import Transaction, TransactionType
from models.user import User
from yf_patch import yf_download

logger = logging.getLogger(__name__)

# Transaction types representing external cashflows
INFLOW_TYPES = {TransactionType.buy, TransactionType.deposit, TransactionType.delivery_in}
OUTFLOW_TYPES = {TransactionType.sell, TransactionType.withdrawal, TransactionType.delivery_out}
ADDITIVE_TYPES = {TransactionType.buy, TransactionType.delivery_in}
REDUCTIVE_TYPES = {TransactionType.sell, TransactionType.delivery_out}


async def _calc_portfolio_value_fast(db: AsyncSession, user_id: uuid.UUID) -> tuple[float, float]:
    """Fast portfolio value calculation using cached prices. No yfinance calls.

    Returns (total_value_chf, cash_chf).
    """
    from services import cache
    from services.utils import get_fx_rates_batch
    import asyncio

    result = await db.execute(
        select(Position).where(Position.user_id == user_id, Position.is_active == True)
    )
    positions = result.scalars().all()

    fx_rates = await asyncio.to_thread(get_fx_rates_batch)
    total_value = 0.0
    cash_value = 0.0

    for pos in positions:
        if pos.type == AssetType.private_equity:
            continue  # PE excluded from snapshots entirely (like real_estate)
        if pos.type in (AssetType.cash, AssetType.pension):
            val = float(pos.cost_basis_chf or 0)
            total_value += val
            cash_value += val
            continue

        shares = float(pos.shares or 0)
        if shares <= 0:
            continue

        # Get price from cache (Redis/memory) or position.current_price
        price = None
        if pos.coingecko_id:
            cached = cache.get(f"crypto:{pos.coingecko_id}")
            if cached:
                price = cached.get("price")
                # Crypto prices from CoinGecko are already in CHF
                if price:
                    total_value += shares * price
                    continue
        elif pos.gold_org:
            cached = cache.get("gold_chf")
            if cached:
                price = cached.get("price")
                if price:
                    total_value += shares * price
                    continue

        ticker = pos.yfinance_ticker or pos.ticker
        cached = cache.get(f"price:{ticker}")
        if cached:
            price = cached.get("price")
        elif pos.current_price:
            price = float(pos.current_price)

        if price:
            fx = fx_rates.get(pos.currency, 1.0) if pos.currency != "CHF" else 1.0
            total_value += shares * price * fx
        else:
            # Fallback: use cost basis
            total_value += float(pos.cost_basis_chf or 0)

    return total_value, cash_value


async def record_daily_snapshot(db: AsyncSession) -> int:
    """Record today's portfolio snapshot for each user. Returns count of snapshots saved."""
    today = date.today()

    # Get all users
    result = await db.execute(select(User))
    users = result.scalars().all()

    # Process users concurrently (max 10 at a time to avoid DB pool exhaustion)
    semaphore = asyncio.Semaphore(10)
    results = []

    async def _safe_snapshot(user_id):
        async with semaphore:
            try:
                await _record_user_snapshot(db, user_id, today)
                return True
            except Exception as e:
                logger.error(f"Snapshot failed for user {user_id}: {e}")
                return False

    results = await asyncio.gather(*[_safe_snapshot(u.id) for u in users])
    await db.commit()
    return sum(1 for r in results if r)


async def _record_user_snapshot(db: AsyncSession, user_id: uuid.UUID, snapshot_date: date) -> None:
    """Record a single user's portfolio snapshot for the given date."""
    # Lightweight value calculation — uses cached prices from Redis, no yfinance calls
    total_value_chf, cash_chf = await _calc_portfolio_value_fast(db, user_id)

    # Net cashflow today = transaction-based flows + manual position changes
    # 1. Transaction-based cashflows (buys/deposits/sells/withdrawals)
    txn_result = await db.execute(
        select(func.coalesce(func.sum(
            case(
                (Transaction.type.in_(INFLOW_TYPES), Transaction.total_chf),
                (Transaction.type.in_(OUTFLOW_TYPES), -Transaction.total_chf),
                else_=0,
            )
        ), 0)).where(
            Transaction.user_id == user_id,
            Transaction.date == snapshot_date,
        )
    )
    txn_cash_flow = float(txn_result.scalar())

    # 2. Detect manual position changes by comparing with previous snapshot
    prev_result = await db.execute(
        select(PortfolioSnapshot.total_value_chf)
        .where(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.date < snapshot_date,
        )
        .order_by(PortfolioSnapshot.date.desc())
        .limit(1)
    )
    prev_value = prev_result.scalar()

    # If we have a previous snapshot, detect large unexplained jumps as cashflows
    manual_cash_flow = 0.0
    if prev_value is not None:
        prev_value = float(prev_value)
        # Expected change from market movement alone is typically < 5% per day
        # Anything beyond that + transaction flows is likely a manual position change
        unexplained = total_value_chf - prev_value - txn_cash_flow
        # If the unexplained change is > 10% of prev value, treat excess as cashflow
        threshold = prev_value * 0.10 if prev_value > 0 else 5000
        if abs(unexplained) > threshold:
            manual_cash_flow = unexplained

    net_cash_flow_chf = txn_cash_flow + manual_cash_flow

    # Upsert (insert or update on conflict)
    stmt = pg_insert(PortfolioSnapshot).values(
        user_id=user_id,
        date=snapshot_date,
        total_value_chf=round(total_value_chf, 2),
        cash_chf=round(cash_chf, 2),
        net_cash_flow_chf=round(net_cash_flow_chf, 2),
    ).on_conflict_do_update(
        constraint="uq_snapshot_user_date",
        set_={
            "total_value_chf": round(total_value_chf, 2),
            "cash_chf": round(cash_chf, 2),
            "net_cash_flow_chf": round(net_cash_flow_chf, 2),
        },
    )
    await db.execute(stmt)


async def regenerate_snapshots(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Regenerate all portfolio snapshots from transaction history + historical prices."""

    # 1. Load all transactions sorted by date
    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.date.asc(), Transaction.created_at.asc())
    )
    all_txns = result.scalars().all()
    if not all_txns:
        return {"snapshots_created": 0, "date_range": None}

    # 2. Load positions for ticker/currency mapping
    result = await db.execute(select(Position).where(Position.user_id == user_id))
    positions = {str(p.id): p for p in result.scalars().all()}

    first_date = min(t.date for t in all_txns)
    today = date.today()

    # 3. Collect yfinance tickers and FX pairs needed
    tickers_needed = set()
    fx_pairs_needed = set()
    for pos in positions.values():
        if pos.type in (AssetType.cash, AssetType.pension, AssetType.real_estate, AssetType.private_equity):
            continue
        yf_ticker = pos.yfinance_ticker or pos.ticker
        if pos.gold_org:
            yf_ticker = "GC=F"
        tickers_needed.add(yf_ticker)
        currency = "USD" if pos.gold_org else pos.currency
        if currency != "CHF":
            fx_pairs_needed.add(f"{currency}CHF=X")

    all_download = list(tickers_needed | fx_pairs_needed)
    if not all_download:
        return {"snapshots_created": 0, "date_range": None}

    # 4. Batch download historical prices (one call for efficiency)
    logger.info(f"Downloading historical prices for {len(all_download)} tickers from {first_date}...")
    dl_start = first_date - timedelta(days=7)  # buffer for forward-fill
    try:
        price_data = await asyncio.to_thread(
            yf_download,
            all_download,
            start=dl_start.isoformat(),
            end=(today + timedelta(days=1)).isoformat(),
            auto_adjust=True,
        )
    except Exception as e:
        logger.error(f"yfinance download failed: {e}")
        return {"snapshots_created": 0, "error": str(e)}

    # Normalize to multi-index DataFrame with Close prices
    if len(all_download) == 1:
        single = all_download[0]
        if "Close" in price_data.columns:
            close_df = price_data[["Close"]].copy()
            close_df.columns = pd.MultiIndex.from_tuples([("Close", single)])
        else:
            return {"snapshots_created": 0, "error": "No price data returned"}
    else:
        if "Close" in price_data.columns:
            close_df = price_data["Close"]
        else:
            close_df = price_data

    def get_close(ticker: str, target_date: date) -> float | None:
        try:
            if len(all_download) == 1:
                col = close_df[("Close", ticker)]
            else:
                col = close_df[ticker]
            ts = pd.Timestamp(target_date)
            available = col.loc[:ts].dropna()
            if len(available) > 0:
                return float(available.iloc[-1])
        except (KeyError, IndexError) as e:
            logger.debug(f"Could not look up price for {ticker} on {target_date}: {e}")
        return None

    # 5. Detect GBX (pence) tickers — .L ETFs where yfinance returns pence instead of pounds
    gbx_tickers = set()
    for pos in positions.values():
        yf_ticker = pos.yfinance_ticker or pos.ticker
        if not yf_ticker.endswith(".L"):
            continue
        # Compare first buy price from transaction with yfinance price
        first_buy = next(
            (t for t in all_txns if str(t.position_id) == str(pos.id)
             and t.type in ADDITIVE_TYPES and float(t.price_per_share) > 0),
            None,
        )
        if first_buy:
            yf_price = get_close(yf_ticker, first_buy.date)
            buy_price = float(first_buy.price_per_share)
            if yf_price and buy_price > 0:
                ratio = yf_price / buy_price
                if 50 < ratio < 200:
                    gbx_tickers.add(yf_ticker)
                    logger.info(f"Detected GBX pricing for {yf_ticker} (ratio={ratio:.1f})")

    # 6. Build transaction lookup by date and cashflows by date
    txns_by_date = defaultdict(list)
    cashflows_by_date = defaultdict(float)
    for txn in all_txns:
        txns_by_date[txn.date].append(txn)
        if txn.type in INFLOW_TYPES:
            cashflows_by_date[txn.date] += float(txn.total_chf)
        elif txn.type in OUTFLOW_TYPES:
            cashflows_by_date[txn.date] -= float(txn.total_chf)

    # 6. Delete existing snapshots
    await db.execute(
        delete(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
    )

    # 7. Iterate day by day, building cumulative holdings and portfolio value
    current_holdings = defaultdict(float)  # position_id -> shares
    cost_basis = defaultdict(float)  # position_id -> cost_basis_chf
    snapshots_created = 0
    batch_values = []
    current_date = first_date

    while current_date <= today:
        # Apply transactions for this date
        for txn in txns_by_date.get(current_date, []):
            pid = str(txn.position_id)
            if txn.type in ADDITIVE_TYPES:
                current_holdings[pid] += float(txn.shares)
                cost_basis[pid] += float(txn.total_chf)
            elif txn.type in REDUCTIVE_TYPES:
                old_shares = current_holdings[pid]
                sell_shares = float(txn.shares)
                if old_shares > 0:
                    sell_ratio = sell_shares / old_shares
                    cost_basis[pid] *= (1 - sell_ratio)
                current_holdings[pid] = max(0, old_shares - sell_shares)

        # Calculate portfolio value for this date
        total_value_chf = 0.0
        has_any_price = False

        for pid, shares in current_holdings.items():
            if shares <= 0:
                continue
            pos = positions.get(pid)
            if not pos:
                continue

            # Cash/pension: use cost basis as value
            if pos.type == AssetType.private_equity:
                continue  # PE excluded from snapshots entirely
            if pos.type in (AssetType.cash, AssetType.pension, AssetType.real_estate):
                total_value_chf += cost_basis.get(pid, 0)
                has_any_price = True
                continue

            yf_ticker = pos.yfinance_ticker or pos.ticker
            currency = pos.currency
            if pos.gold_org:
                yf_ticker = "GC=F"
                currency = "USD"

            price = get_close(yf_ticker, current_date)
            if price is None:
                # Use cost basis as fallback
                total_value_chf += cost_basis.get(pid, 0)
                continue

            # Correct GBX (pence) to GBP
            if yf_ticker in gbx_tickers:
                price /= 100

            fx = 1.0
            if currency != "CHF":
                fx_price = get_close(f"{currency}CHF=X", current_date)
                if fx_price:
                    fx = fx_price

            total_value_chf += shares * price * fx
            has_any_price = True

        # Collect snapshot for weekdays (batch insert later)
        if current_date.weekday() < 5 and current_date >= first_date:
            net_cf = cashflows_by_date.get(current_date, 0)
            batch_values.append({
                "user_id": user_id,
                "date": current_date,
                "total_value_chf": round(total_value_chf, 2),
                "cash_chf": 0,
                "net_cash_flow_chf": round(net_cf, 2),
            })
            snapshots_created += 1

        current_date += timedelta(days=1)

    # Batch upsert all snapshots at once
    if batch_values:
        for i in range(0, len(batch_values), 500):
            chunk = batch_values[i:i + 500]
            stmt = pg_insert(PortfolioSnapshot).values(chunk)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_snapshot_user_date",
                set_={
                    "total_value_chf": stmt.excluded.total_value_chf,
                    "cash_chf": stmt.excluded.cash_chf,
                    "net_cash_flow_chf": stmt.excluded.net_cash_flow_chf,
                },
            )
            await db.execute(stmt)

    await db.commit()
    logger.info(f"Regenerated {snapshots_created} snapshots for user {user_id} ({first_date} to {today})")

    return {
        "snapshots_created": snapshots_created,
        "date_range": {"from": first_date.isoformat(), "to": today.isoformat()},
    }
