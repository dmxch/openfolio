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

from db import async_session
from models.bucket import Bucket, BucketSnapshot, BucketSystemRole, BucketKind
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import Position, AssetType
from models.transaction import Transaction, TransactionType
from models.user import User
from yf_patch import yf_download

logger = logging.getLogger(__name__)

from constants.cashflow import INFLOW_TYPES, OUTFLOW_TYPES
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
            saldo = float(pos.cost_basis_chf or 0)
            if pos.currency != "CHF":
                fx = fx_rates.get(pos.currency)
                if fx is None:
                    from services.cache_service import get_cached_price_sync
                    cached = get_cached_price_sync(f"{pos.currency}CHF=X", fallback_days=30)
                    if cached:
                        fx = cached["price"]
                        logger.warning(f"FX {pos.currency}: using stale rate {fx} for cash/pension {pos.ticker}")
                    else:
                        logger.error(f"FX {pos.currency}: NO RATE AVAILABLE for cash/pension {pos.ticker}")
                        fx = 1.0
                saldo *= fx
            total_value += saldo
            cash_value += saldo
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
            # Zuerst spezifischen Metal-Key, dann Legacy-Gold-Key (für XAUCHF=X).
            cached = cache.get(f"metal_chf:{pos.ticker}") or (
                cache.get("gold_chf") if pos.ticker == "XAUCHF=X" else None
            )
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
            fx = _fx_or_none(pos.currency, fx_rates, pos.ticker)
            if fx is None:
                total_value += float(pos.cost_basis_chf or 0)
            else:
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
                # Pro User eigene AsyncSession — SQLAlchemy 2.0 verbietet
                # parallele Operationen auf derselben Session, und mehrere
                # Snapshot-Branches lesen DB. Siehe screening_service._isolated_db_call.
                async with async_session() as user_db:
                    await _record_user_snapshot(user_db, user_id, today)
                    await user_db.commit()
                return True
            except Exception as e:
                logger.error(f"Snapshot failed for user {user_id}: {e}", exc_info=True)
                return False

    results = await asyncio.gather(*[_safe_snapshot(u.id) for u in users])
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

    # Bucket-Snapshots: parallel zur portfolio_snapshot, gleiche Liquid-Logik.
    # Toleranzen / Konsistenz: sum(bucket_snapshots) sollte == portfolio_snapshot
    # binnen ±1 CHF / ±0.05% sein (siehe bucket_consistency_service).
    await _record_user_bucket_snapshots(db, user_id, snapshot_date)


# ---------------------------------------------------------------------------
# Bucket-Snapshots (v2.1)
# ---------------------------------------------------------------------------

# Welche Asset-Typen flow'n in den Liquid-Default-Bucket bzw. user-buckets.
# Identisch zur Logik in _calc_portfolio_value_fast (PE excluded).
_LIQUID_ASSET_TYPES = {
    AssetType.stock,
    AssetType.etf,
    AssetType.crypto,
    AssetType.commodity,
    AssetType.cash,
    AssetType.pension,  # Vorsorge zaehlt zu cash im PortfolioSnapshot
}

# System-Buckets, fuer die KEINE bucket_snapshots geschrieben werden, weil
# ihre Positions-Typen aus portfolio_snapshots ausgeschlossen sind.
# (real_estate, private_equity sind komplett excluded; pension-Bucket bekommt
# nur dann snapshots wenn Position.bucket_id darauf zeigt — handled implizit.)
_EXCLUDED_FROM_BUCKET_SUMS = {
    BucketSystemRole.real_estate,
    BucketSystemRole.private_equity,
}


def _bucket_cashflow_by_date(all_txns, positions: dict, eligible_bucket_ids: set) -> dict:
    """Netto-Cashflow je (Bucket, Tag) fuer die Snapshot-Regeneration.

    Verkaeufe (OUTFLOW) werden dem Bucket ZUM VERKAUFSZEITPUNKT zugeordnet
    (``Transaction.bucket_id_at_sale``), nicht der ggf. spaeter gewechselten
    ``Position.bucket_id`` — analog total_return_service.list_realized_gains.
    Alle anderen Cashflows nutzen die aktuelle ``Position.bucket_id``. Buckets
    ausserhalb ``eligible_bucket_ids`` (PE/Immobilien) werden ignoriert.

    Returns: ``{bucket_id: {date: net_chf}}`` (INFLOW positiv, OUTFLOW negativ).
    """
    out: dict = {bid: defaultdict(float) for bid in eligible_bucket_ids}
    for txn in all_txns:
        pos = positions.get(str(txn.position_id))
        if pos is None:
            continue
        if txn.type in OUTFLOW_TYPES and txn.bucket_id_at_sale is not None:
            bid = txn.bucket_id_at_sale
        else:
            bid = pos.bucket_id
        if bid not in eligible_bucket_ids:
            continue
        if txn.type in INFLOW_TYPES:
            out[bid][txn.date] += float(txn.total_chf)
        elif txn.type in OUTFLOW_TYPES:
            out[bid][txn.date] -= float(txn.total_chf)
    return out


def _fx_or_none(currency: str, fx_rates: dict, ticker: str) -> float | None:
    """FX-Rate mit Stale-DB-Fallback (30 Tage) — None statt stillem 1.0.

    fx=1.0 bei fehlender Rate bewertet z.B. eine JPY-Position ~167× zu hoch
    (Review 2026-06-10, M4). portfolio_service behandelt den Fall korrekt
    als stale — der Snapshot-Pfad zieht hier nach: None → Caller fällt auf
    cost_basis zurück.
    """
    if currency == "CHF":
        return 1.0
    fx = fx_rates.get(currency)
    if fx is not None:
        return fx
    from services.cache_service import get_cached_price_sync
    cached = get_cached_price_sync(f"{currency}CHF=X", fallback_days=30)
    if cached:
        logger.warning(f"FX {currency}: using stale rate {cached['price']} for {ticker} (snapshot)")
        return float(cached["price"])
    logger.error(f"FX {currency}: NO RATE AVAILABLE for {ticker} — snapshot falls back to cost basis")
    return None


async def _calc_position_value_chf(pos, fx_rates) -> float:
    """Single-Position-Bewertung — identisch zur Logik in _calc_portfolio_value_fast."""
    from services import cache
    from services.cache_service import get_cached_price_sync

    if pos.type == AssetType.private_equity:
        return 0.0
    if pos.type in (AssetType.cash, AssetType.pension):
        saldo = float(pos.cost_basis_chf or 0)
        if pos.currency != "CHF":
            fx = fx_rates.get(pos.currency)
            if fx is None:
                cached = get_cached_price_sync(f"{pos.currency}CHF=X", fallback_days=30)
                if cached:
                    fx = cached["price"]
                else:
                    fx = 1.0
            saldo *= fx
        return saldo

    shares = float(pos.shares or 0)
    if shares <= 0:
        return 0.0

    price = None
    if pos.coingecko_id:
        cached = cache.get(f"crypto:{pos.coingecko_id}")
        if cached:
            price = cached.get("price")
            if price:
                return shares * price
    elif pos.gold_org:
        cached = cache.get(f"metal_chf:{pos.ticker}") or (
            cache.get("gold_chf") if pos.ticker == "XAUCHF=X" else None
        )
        if cached:
            price = cached.get("price")
            if price:
                return shares * price

    ticker = pos.yfinance_ticker or pos.ticker
    cached = cache.get(f"price:{ticker}")
    if cached:
        price = cached.get("price")
    elif pos.current_price:
        price = float(pos.current_price)

    if price:
        fx = _fx_or_none(pos.currency, fx_rates, pos.ticker)
        if fx is None:
            return float(pos.cost_basis_chf or 0)
        return shares * price * fx

    return float(pos.cost_basis_chf or 0)


async def _record_user_bucket_snapshots(
    db: AsyncSession, user_id: uuid.UUID, snapshot_date: date
) -> None:
    """Schreibt pro aktivem Bucket (kind=user oder system_role=liquid_default)
    einen BucketSnapshot mit running_peak_chf.

    PE/Real-Estate-Buckets werden ausgelassen — ihre Positionen sind aus
    portfolio_snapshots excluded, damit sum(bucket_snapshots) == portfolio_snapshot
    konsistent bleibt.
    """
    from services.utils import get_fx_rates_batch

    # Buckets dieses Users (aktiv)
    buckets_q = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.deleted_at.is_(None),
        )
    )
    buckets = list(buckets_q.scalars().all())
    eligible = [
        b for b in buckets
        if b.system_role not in _EXCLUDED_FROM_BUCKET_SUMS
    ]
    if not eligible:
        return

    # Positionen mit bucket_id
    pos_q = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.is_active.is_(True),
        )
    )
    positions = list(pos_q.scalars().all())

    fx_rates = await asyncio.to_thread(get_fx_rates_batch)

    # Aggregate pro Bucket
    totals: dict[uuid.UUID, dict] = {b.id: {"value": 0.0, "cash": 0.0} for b in eligible}
    for pos in positions:
        if pos.bucket_id is None:
            continue
        if pos.bucket_id not in totals:
            # Position ist in einem ausgeschlossenen Bucket (z.B. PE) — skip
            continue
        val = await _calc_position_value_chf(pos, fx_rates)
        totals[pos.bucket_id]["value"] += val
        if pos.type in (AssetType.cash, AssetType.pension):
            totals[pos.bucket_id]["cash"] += val

    # Cashflows pro Bucket fuer den Tag
    cashflows: dict[uuid.UUID, float] = {b.id: 0.0 for b in eligible}
    cf_q = await db.execute(
        select(
            Position.bucket_id,
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type.in_(INFLOW_TYPES), Transaction.total_chf),
                        (Transaction.type.in_(OUTFLOW_TYPES), -Transaction.total_chf),
                        else_=0,
                    )
                ),
                0,
            ).label("net"),
        )
        .join(Position, Transaction.position_id == Position.id, isouter=True)
        .where(
            Transaction.user_id == user_id,
            Transaction.date == snapshot_date,
        )
        .group_by(Position.bucket_id)
    )
    for row in cf_q.all():
        bid = row.bucket_id
        if bid is not None and bid in cashflows:
            cashflows[bid] = float(row.net)

    # Vorheriger Zustand pro Bucket fuer Wealth-Index-Chaining:
    # - prev total_value_chf (V_{t-1} fuer Sub-Return-Berechnung)
    # - prev wealth_index, running_peak_wealth_index, running_peak_chf
    # Wir holen pro Bucket den letzten Snapshot vor snapshot_date. Eine
    # einzige Query mit DISTINCT ON pro bucket_id.
    bucket_ids_list = [b.id for b in eligible]
    prev_q = await db.execute(
        select(BucketSnapshot)
        .where(
            BucketSnapshot.user_id == user_id,
            BucketSnapshot.bucket_id.in_(bucket_ids_list),
            BucketSnapshot.date < snapshot_date,
        )
        .order_by(BucketSnapshot.bucket_id, BucketSnapshot.date.desc())
    )
    prev_by_bucket: dict[uuid.UUID, BucketSnapshot] = {}
    for s in prev_q.scalars():
        if s.bucket_id not in prev_by_bucket:
            prev_by_bucket[s.bucket_id] = s

    # Pro Bucket: Wealth-Index-Chain + Upsert
    for b in eligible:
        agg = totals[b.id]
        total_value = round(agg["value"], 2)
        cash_value = round(agg["cash"], 2)
        net_cf = round(cashflows.get(b.id, 0.0), 2)

        prev_snap = prev_by_bucket.get(b.id)
        if prev_snap is None:
            # Erster Snapshot dieses Buckets: Initialwerte
            wealth_index = 1.0
            running_peak_wealth_index = 1.0
            running_peak = total_value
        else:
            prev_value = float(prev_snap.total_value_chf or 0)
            prev_wealth = float(prev_snap.wealth_index or 1.0)
            prev_peak_wealth = float(prev_snap.running_peak_wealth_index or 1.0)
            prev_peak_chf = float(prev_snap.running_peak_chf or 0)

            wealth_index = prev_wealth
            if prev_value > 0:
                ret_factor = (total_value - net_cf) / prev_value
                if ret_factor > 0:
                    wealth_index = prev_wealth * ret_factor

            if wealth_index > prev_peak_wealth:
                running_peak_wealth_index = wealth_index
                running_peak = total_value
            else:
                running_peak_wealth_index = prev_peak_wealth
                running_peak = prev_peak_chf

        stmt = pg_insert(BucketSnapshot).values(
            user_id=user_id,
            bucket_id=b.id,
            date=snapshot_date,
            total_value_chf=total_value,
            cash_chf=cash_value,
            net_cash_flow_chf=net_cf,
            running_peak_chf=running_peak,
            wealth_index=wealth_index,
            running_peak_wealth_index=running_peak_wealth_index,
        ).on_conflict_do_update(
            constraint="uq_bucket_snapshot",
            set_={
                "total_value_chf": total_value,
                "cash_chf": cash_value,
                "net_cash_flow_chf": net_cf,
                "running_peak_chf": running_peak,
                "wealth_index": wealth_index,
                "running_peak_wealth_index": running_peak_wealth_index,
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
            # Cash/Pension brauchen keinen Kurs, aber bei Fremdwährung den
            # FX-Kurs für die Saldo-Konvertierung (H8).
            if pos.type in (AssetType.cash, AssetType.pension) and pos.currency != "CHF":
                fx_pairs_needed.add(f"{pos.currency}CHF=X")
            continue
        yf_ticker = pos.yfinance_ticker or pos.ticker
        currency = pos.currency
        if pos.gold_org:
            from services.precious_metals_service import get_metal_futures
            fut = get_metal_futures(pos.ticker)
            if fut:
                yf_ticker, currency = fut
        tickers_needed.add(yf_ticker)
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
        logger.error(f"yfinance download failed: {e}", exc_info=True)
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

    # 6b. Cash/Pension-Salden (Review 2026-06-10, H8): vorher fehlten sie im
    # regenerierten total_value_chf komplett (cash_chf hartkodiert 0), während
    # deposit/withdrawal in net_cash_flow_chf zählten — Dietz/XIRR sahen
    # Zuflüsse ohne Wertzuwachs, und an der Regen→Daily-Grenze sprang die
    # Historie um den gesamten Cash-Saldo. Salden sind manuell gepflegt
    # (typisch ohne Txn-Historie); wir back-solven die Basis aus dem heutigen
    # Saldo minus aller Cash-Txns, sodass der Endstand dem heutigen entspricht,
    # und mutieren im Tages-Loop mit deposit/withdrawal. Für Fremdwährungs-
    # Cash ist die total_chf-basierte Mutation eine Näherung (Saldo liegt in
    # Fremdwährung vor, wie im Daily-Pfad).
    cash_balances: dict[str, float] = {}
    for pid, pos in positions.items():
        if pos.type in (AssetType.cash, AssetType.pension):
            saldo = float(pos.cost_basis_chf or 0)
            net_txn = sum(
                (float(t.total_chf) if t.type == TransactionType.deposit else -float(t.total_chf))
                for t in all_txns
                if str(t.position_id) == pid
                and t.type in (TransactionType.deposit, TransactionType.withdrawal)
            )
            cash_balances[pid] = saldo - net_txn

    # 6c. Bucket-Aggregation vorbereiten. BucketSnapshots wurden bisher NICHT aus
    # dem Ledger regeneriert (regenerate_snapshots schrieb nur PortfolioSnapshots).
    # Folge: rueckdatierte/nachgetragene Trades liessen net_cash_flow_chf UND
    # total_value_chf alter Bucket-Snapshots stale → der cash-flow-bereinigte TWR
    # (Drawdown, Perf-Card, Monatsrenditen) las abgezogenes Cash als Verlust
    # (Satellite-Phantom -49 %). Wir bauen die Bucket-Reihe hier im selben Replay
    # mit. Verkaufs-Cashflows via Transaction.bucket_id_at_sale (Bucket zum
    # Verkaufszeitpunkt, robust gegen spaetere Bucket-Wechsel), sonst aktuelle
    # Position.bucket_id.
    buckets_q = await db.execute(
        select(Bucket).where(Bucket.user_id == user_id, Bucket.deleted_at.is_(None))
    )
    eligible_buckets = [
        b for b in buckets_q.scalars().all()
        if b.system_role not in _EXCLUDED_FROM_BUCKET_SUMS
    ]
    eligible_bucket_ids = {b.id for b in eligible_buckets}
    bucket_cf_by_date = _bucket_cashflow_by_date(
        all_txns, positions, eligible_bucket_ids
    )
    bucket_rows: dict[uuid.UUID, list[dict]] = {b.id: [] for b in eligible_buckets}

    # Fallback-Bewertung NUR fuer Bucket-Werte (Portfolio-Total bleibt unveraendert):
    # Gold-Spot (XAUCHF=X) und Crypto haben keine/keine nutzbare yfinance-Historie
    # (Spezial-Preisquelle via current_price) — ohne Fallback setzt der Replay sie
    # auf 0/Cost-Basis (Hard Money=0, Crypto=Cost-Basis). Wir bewerten sie wie der
    # Daily-Recorder ueber den aktuellen Marktwert (current_price), skaliert auf die
    # am jeweiligen Tag gehaltenen Shares. Positionen OHNE Buy-Txn (Gold) tauchen
    # nie in current_holdings auf → als konstanter statischer Bucket-Wert addiert.
    from services.utils import get_fx_rates_batch
    fx_rates = await asyncio.to_thread(get_fx_rates_batch)
    positions_with_txns = {str(t.position_id) for t in all_txns}
    current_per_share_chf: dict[str, float] = {}
    static_bucket_value: dict = defaultdict(float)
    for pid, pos in positions.items():
        if pos.type in (
            AssetType.cash, AssetType.pension,
            AssetType.real_estate, AssetType.private_equity,
        ):
            continue
        if not pos.is_active or float(pos.shares or 0) <= 0:
            continue
        cur_total = await _calc_position_value_chf(pos, fx_rates)
        sh = float(pos.shares or 0)
        current_per_share_chf[pid] = (cur_total / sh) if sh > 0 else 0.0
        if pid not in positions_with_txns and pos.bucket_id in eligible_bucket_ids:
            static_bucket_value[pos.bucket_id] += cur_total

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
                    # Oversell-Clamp wie in recalculate_service (M3):
                    # Cost-Basis darf nie negativ werden.
                    sell_ratio = min(1.0, sell_shares / old_shares)
                    cost_basis[pid] *= (1 - sell_ratio)
                current_holdings[pid] = max(0, old_shares - sell_shares)
            elif txn.type == TransactionType.deposit and pid in cash_balances:
                cash_balances[pid] += float(txn.total_chf)
            elif txn.type == TransactionType.withdrawal and pid in cash_balances:
                cash_balances[pid] -= float(txn.total_chf)

        # Calculate portfolio value for this date (portfolio total + per bucket)
        total_value_chf = 0.0
        has_any_price = False
        bucket_value_today: dict = defaultdict(float)
        bucket_cash_today: dict = defaultdict(float)

        for pid, shares in current_holdings.items():
            if shares <= 0:
                continue
            pos = positions.get(pid)
            if not pos:
                continue

            if pos.type == AssetType.private_equity:
                continue  # PE excluded from snapshots entirely

            # Cash/pension/real_estate: use cost basis as value
            priced = True
            if pos.type in (AssetType.cash, AssetType.pension, AssetType.real_estate):
                val = cost_basis.get(pid, 0)
                total_value_chf += val
                has_any_price = True
            else:
                yf_ticker = pos.yfinance_ticker or pos.ticker
                currency = pos.currency
                if pos.gold_org:
                    from services.precious_metals_service import get_metal_futures
                    fut = get_metal_futures(pos.ticker)
                    if fut:
                        yf_ticker, currency = fut

                price = get_close(yf_ticker, current_date)
                if price is None:
                    # Use cost basis as fallback (kein has_any_price)
                    val = cost_basis.get(pid, 0)
                    total_value_chf += val
                    priced = False
                else:
                    # Correct GBX (pence) to GBP
                    if yf_ticker in gbx_tickers:
                        price /= 100
                    fx = 1.0
                    if currency != "CHF":
                        fx_price = get_close(f"{currency}CHF=X", current_date)
                        if fx_price:
                            fx = fx_price
                    val = shares * price * fx
                    total_value_chf += val
                    has_any_price = True

            # Bucket-Wert: historischer Preis wenn vorhanden, sonst aktueller
            # Marktwert × heute gehaltene Shares (Gold/Crypto-Fallback). Der
            # Portfolio-Total oben bleibt unveraendert (val).
            if pos.bucket_id in eligible_bucket_ids:
                if priced:
                    bval = val
                else:
                    per = current_per_share_chf.get(pid)
                    bval = shares * per if per else cost_basis.get(pid, 0)
                bucket_value_today[pos.bucket_id] += bval

        # Cash/Pension-Salden einrechnen (H8) — identisch zum Daily-Pfad,
        # der den manuellen Saldo (×FX bei Fremdwährung) in total UND cash_chf
        # führt. Vorher: cash_chf=0 → Sprung an der Regen→Daily-Grenze.
        cash_chf_today = 0.0
        for cpid, saldo in cash_balances.items():
            cpos = positions.get(cpid)
            val = saldo
            if cpos is not None and cpos.currency != "CHF":
                fx_price = get_close(f"{cpos.currency}CHF=X", current_date)
                if fx_price:
                    val = saldo * fx_price
            cash_chf_today += val
            if cpos is not None and cpos.bucket_id in eligible_bucket_ids:
                bucket_value_today[cpos.bucket_id] += val
                bucket_cash_today[cpos.bucket_id] += val
        total_value_chf += cash_chf_today

        # Collect snapshot for weekdays (batch insert later)
        if current_date.weekday() < 5 and current_date >= first_date:
            net_cf = cashflows_by_date.get(current_date, 0)
            batch_values.append({
                "user_id": user_id,
                "date": current_date,
                "total_value_chf": round(total_value_chf, 2),
                "cash_chf": round(cash_chf_today, 2),
                "net_cash_flow_chf": round(net_cf, 2),
            })
            snapshots_created += 1

        # Bucket-Snapshots: jeden Tag (inkl. Wochenende, wie der Daily-Recorder).
        # static_bucket_value = konstanter Wert der Nicht-Txn-Positionen (Gold).
        for b in eligible_buckets:
            tv = bucket_value_today.get(b.id, 0.0) + static_bucket_value.get(b.id, 0.0)
            bucket_rows[b.id].append({
                "date": current_date,
                "total_value_chf": round(tv, 2),
                "cash_chf": round(bucket_cash_today.get(b.id, 0.0), 2),
                "net_cash_flow_chf": round(bucket_cf_by_date[b.id].get(current_date, 0.0), 2),
            })

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

    # Bucket-Snapshots neu aufbauen: alte (stale) Rows loeschen, Reihe aus dem
    # Replay neu schreiben inkl. cash-flow-bereinigtem Wealth-Index-Chain
    # (ret>0-Guard wie der Daily-Recorder). Damit erfassen TWR/Drawdown
    # rueckdatierte Verkaeufe korrekt als Outflow statt als Verlust.
    bucket_count = 0
    if eligible_buckets:
        await db.execute(
            delete(BucketSnapshot).where(BucketSnapshot.user_id == user_id)
        )
        bucket_batch = []
        for bid, rows in bucket_rows.items():
            prev_value = None
            prev_wealth = 1.0
            prev_peak_wealth = 1.0
            prev_peak_chf = 0.0
            for r in rows:
                tv = r["total_value_chf"]
                ncf = r["net_cash_flow_chf"]
                if prev_value is None:
                    wealth = 1.0
                    peak_wealth = 1.0
                    peak_chf = tv
                else:
                    wealth = prev_wealth
                    if prev_value > 0:
                        ret = (tv - ncf) / prev_value
                        if ret > 0:
                            wealth = prev_wealth * ret
                    if wealth > prev_peak_wealth:
                        peak_wealth = wealth
                        peak_chf = tv
                    else:
                        peak_wealth = prev_peak_wealth
                        peak_chf = prev_peak_chf
                bucket_batch.append({
                    "user_id": user_id,
                    "bucket_id": bid,
                    "date": r["date"],
                    "total_value_chf": tv,
                    "cash_chf": r["cash_chf"],
                    "net_cash_flow_chf": ncf,
                    "running_peak_chf": round(peak_chf, 2),
                    "wealth_index": round(wealth, 6),
                    "running_peak_wealth_index": round(peak_wealth, 6),
                })
                prev_value = tv
                prev_wealth = wealth
                prev_peak_wealth = peak_wealth
                prev_peak_chf = peak_chf
        for i in range(0, len(bucket_batch), 500):
            chunk = bucket_batch[i:i + 500]
            await db.execute(pg_insert(BucketSnapshot).values(chunk))
        bucket_count = len(bucket_batch)

    await db.commit()
    logger.info(
        f"Regenerated {snapshots_created} portfolio + {bucket_count} bucket snapshots "
        f"for user {user_id} ({first_date} to {today})"
    )

    return {
        "snapshots_created": snapshots_created,
        "bucket_snapshots_created": bucket_count,
        "date_range": {"from": first_date.isoformat(), "to": today.isoformat()},
    }
