"""Daily portfolio snapshot for TTWROR tracking."""
import asyncio
import bisect
import logging
import time
import uuid
from collections import defaultdict
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import delete, select, func, case, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from constants.limits import MAX_REGEN_SPAN_DAYS
from db import async_session
from models.bucket import Bucket, BucketSnapshot, BucketSystemRole, BucketKind
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import Position, AssetType, has_manual_price
from models.transaction import Transaction, TransactionType
from models.user import User
from yf_patch import yf_download

logger = logging.getLogger(__name__)

from constants.cashflow import INFLOW_TYPES, OUTFLOW_TYPES
ADDITIVE_TYPES = {TransactionType.buy, TransactionType.delivery_in}
REDUCTIVE_TYPES = {TransactionType.sell, TransactionType.delivery_out}


def _counts_as_cash(pos: Position) -> bool:
    """Zaehlt diese Wertschrift in der Cash-Quote (cash_chf)?

    Gemeint sind Geldmarkt-/T-Bill-Fonds: regulaer ueber shares × price × fx
    bepreist, in der Cash-Quote aber als Cash gefuehrt. Das Flag ist ETF-exklusiv —
    Anleihen sind kein Cash und tragen es nie; der Typ-Gate haelt das auch, wenn es
    direkt in der DB gesetzt wurde (die API validiert die Kombination nicht).

    Einzige Quelle fuer Daily- UND Regen-Pfad: liefen die beiden auseinander,
    spraenge cash_chf an der Regen→Daily-Grenze.
    """
    return pos.type == AssetType.etf and pos.count_as_cash


def _has_manual_price(pos) -> bool:
    """Trägt die Position einen von Hand gepflegten Kurs?

    Massgeblich ist ``models.position.has_manual_price``: Modus und Preisquelle
    manual. Ihr Kurs steht in ``current_price``. ``price:<Ticker>`` ist ein
    geteilter Yahoo-Kurs (Watchlist, Positionen anderer Nutzer) und gilt für
    sie nicht: die Summary rechnet mit ``current_price``, und der Snapshot muss
    denselben Wert schreiben.

    Eine Position mit Modus manual und anderer Preisquelle lädt der Worker
    weiter. Sie wird hier wie jede live bepreiste Position bewertet.
    """
    return has_manual_price(pos)


def _replays_at_manual_price(pos) -> bool:
    """Bewertet der Regen die Position mit dem manuellen Kurs statt mit Yahoo?

    Gleiche Rangfolge wie ``portfolio_service._compute_market_value``: Krypto
    mit ``coingecko_id`` und Edelmetall haben ihre eigene Kursquelle, sie geht
    dem manuellen Kurs vor. ``has_manual_price`` schliesst beide schon aus.
    """
    return _has_manual_price(pos)


# --- Sperre je Nutzer (K076) ---
#
# Regen und Tages-Snapshot schreiben dieselben Zeilen. Der Schutz in
# snapshot_trigger gilt nur je Prozess; das Backend läuft mit zwei
# uvicorn-Workern, dazu kommt der Worker-Prozess. Ein Advisory-Lock auf
# Transaktionsebene reiht alle Schreiber eines Nutzers ein: wer wartet, liest
# das Ledger erst, wenn der Vorgänger committet hat.
_SNAPSHOT_LOCK_NAMESPACE = 0x534E4150  # "SNAP", erster der beiden Lock-Schlüssel
_SNAPSHOT_LOCK_POLL_SECONDS = 0.5
_SNAPSHOT_LOCK_MAX_WAIT_SECONDS = 900.0


class SnapshotLockBusy(Exception):
    """Ein anderer Lauf schreibt gerade die Snapshots dieses Nutzers."""


async def _lock_user_snapshots(db: AsyncSession, user_id: uuid.UUID, *, wait: bool = True) -> None:
    """Nimmt die Snapshot-Sperre des Nutzers bis zum Ende der Transaktion.

    Nur Postgres; auf anderen Dialekten (Tests: SQLite) ohne Wirkung.
    ``pg_try_advisory_xact_lock`` in einer Schleife statt des blockierenden
    ``pg_advisory_xact_lock``: ein wartendes Statement fiele unter
    ``statement_timeout`` (DB_STATEMENT_TIMEOUT_MS), und die Wartezeit bliebe
    unbegrenzt. ``wait=False`` wirft sofort ``SnapshotLockBusy``.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    key = int.from_bytes(user_id.bytes[:4], "big", signed=True)
    deadline = time.monotonic() + _SNAPSHOT_LOCK_MAX_WAIT_SECONDS
    while True:
        acquired = (await db.execute(
            text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
            {"ns": _SNAPSHOT_LOCK_NAMESPACE, "key": key},
        )).scalar()
        if acquired:
            return
        if not wait or time.monotonic() >= deadline:
            raise SnapshotLockBusy(f"snapshot lock busy for user {user_id}")
        await asyncio.sleep(_SNAPSHOT_LOCK_POLL_SECONDS)


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
        if pos.type in (AssetType.private_equity, AssetType.real_estate):
            continue  # PE + Immobilien komplett aus Snapshots excluded (Invariante #2)
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

        # Wertschriften-Bewertung in `pos_value` sammeln, dann einmalig zu
        # total_value addieren. count_as_cash-Positionen (Geldmarkt-/T-Bill-ETFs)
        # zaehlen zusaetzlich zu cash_value — als Cash klassifiziert, aber
        # regulaer bepreist (kein Doppelzaehlen in total_value).
        pos_value = None
        # Die coingecko_id zählt nur beim Typ crypto. Bei jedem anderen Typ ist
        # sie ein Altbestand; die Position läuft dann wie im Worker über Yahoo.
        if pos.type == AssetType.crypto and pos.coingecko_id:
            cached = cache.get(f"crypto:{pos.coingecko_id}")
            if cached and cached.get("price"):
                # Crypto prices from CoinGecko are already in CHF
                pos_value = shares * cached["price"]
        elif pos.gold_org:
            # Zuerst spezifischen Metal-Key, dann Legacy-Gold-Key (für XAUCHF=X).
            cached = cache.get(f"metal_chf:{pos.ticker}") or (
                cache.get("gold_chf") if pos.ticker == "XAUCHF=X" else None
            )
            if cached and cached.get("price"):
                pos_value = shares * cached["price"]

        if pos_value is None:
            ticker = pos.yfinance_ticker or pos.ticker
            # Manuell gepflegter Kurs: current_price statt price:<Ticker>.
            cached = None if _has_manual_price(pos) else cache.get(f"price:{ticker}")
            if cached:
                price = cached.get("price")
            elif pos.current_price:
                price = float(pos.current_price)
            else:
                price = None

            if price:
                fx = _fx_or_none(pos.currency, fx_rates, pos.ticker)
                pos_value = float(pos.cost_basis_chf or 0) if fx is None else shares * price * fx
            else:
                # Fallback: use cost basis
                pos_value = float(pos.cost_basis_chf or 0)

        total_value += pos_value
        if _counts_as_cash(pos):
            cash_value += pos_value

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


async def _daily_txn_cash_flow(
    db: AsyncSession, user_id: uuid.UUID, snapshot_date: date, *, after_date: date | None = None
) -> float:
    """Transaktions-Cashflow eines Tages auf Portfolio-Ebene (INFLOW positiv, OUTFLOW negativ).

    Als eigene Funktion herausgezogen, damit der Cashflow-Vertrag testbar ist —
    ``_record_user_snapshot`` selbst laeuft ueber ``pg_insert`` und ist in der
    SQLite-Testsuite nicht aufrufbar. Verhalten unveraendert gegenueber der
    vorherigen Inline-Query.

    Mit ``after_date`` zählen alle Buchungen nach diesem Datum bis und mit
    ``snapshot_date``: die Zeile trägt dann auch die Tage ohne eigenen Snapshot.
    """
    if after_date is None:
        in_range = (Transaction.date == snapshot_date,)
    else:
        in_range = (Transaction.date > after_date, Transaction.date <= snapshot_date)
    txn_result = await db.execute(
        select(func.coalesce(func.sum(
            case(
                (Transaction.type.in_(INFLOW_TYPES), Transaction.total_chf),
                (Transaction.type.in_(OUTFLOW_TYPES), -Transaction.total_chf),
                else_=0,
            )
        ), 0)).where(
            Transaction.user_id == user_id,
            *in_range,
        )
    )
    return float(txn_result.scalar())


async def _record_user_snapshot(db: AsyncSession, user_id: uuid.UUID, snapshot_date: date) -> None:
    """Record a single user's portfolio snapshot for the given date."""
    # Vor dem ersten Lesen sperren: ein laufender Regen desselben Nutzers löscht
    # und schreibt dieselben Zeilen (K076).
    await _lock_user_snapshots(db, user_id)

    # Lightweight value calculation — uses cached prices from Redis, no yfinance calls
    total_value_chf, cash_chf = await _calc_portfolio_value_fast(db, user_id)

    # Letzter Snapshot vor snapshot_date: sein Wert für den Sprung-Guard unten,
    # sein Datum für die Cashflow-Spanne.
    prev_result = await db.execute(
        select(PortfolioSnapshot.date, PortfolioSnapshot.total_value_chf)
        .where(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.date < snapshot_date,
        )
        .order_by(PortfolioSnapshot.date.desc())
        .limit(1)
    )
    prev_row = prev_result.first()
    prev_date = prev_row[0] if prev_row is not None else None
    prev_value = prev_row[1] if prev_row is not None else None

    # Net cashflow = transaction-based flows + manual position changes.
    # Die Zeile trägt alle Buchungen seit dem letzten Snapshot, nicht nur die von
    # snapshot_date: der Regen schreibt Portfolio-Zeilen nur an Werktagen und
    # rollt Cashflows vom Wochenende auf den Montag (pending_cf). Summierte der
    # Heute-Snapshot nur den Montag, löschte er diesen Anteil beim Neuschreiben
    # aus net_cash_flow_chf. Ohne Vorzeile zählt wie bisher nur snapshot_date.
    txn_cash_flow = await _daily_txn_cash_flow(
        db, user_id, snapshot_date, after_date=prev_date
    )

    # 2. Detect manual position changes by comparing with previous snapshot.
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
#
# ACHTUNG: Diese Konstante hat KEINEN Consumer im Produktionscode (verifiziert per
# grep; nur Tests lesen sie). Die tatsaechliche Filterung passiert in
# _calc_portfolio_value_fast / _record_user_bucket_snapshots. Aus ihrem Inhalt darf
# NICHT gefolgert werden, dass ein Typ wirklich im Snapshot landet. Sie wird hier
# trotzdem gepflegt, weil ihr Name dazu einlaedt, sie zu verdrahten — passiert das,
# waehrend ein Typ fehlt, faellt der Typ in dem Moment still aus den Snapshots.
_LIQUID_ASSET_TYPES = {
    AssetType.stock,
    AssetType.etf,
    AssetType.bond,
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


def _resolve_price_ticker(pos) -> tuple[str, str]:
    """``(yfinance-Ticker, Notierungswaehrung)`` fuer eine Position.

    Crypto quotiert auf yfinance in USD (auch wenn ``pos.currency`` CHF sagt),
    Edelmetall laeuft ueber den Futures-Kontrakt — CHF-Spot-Ticker wie
    ``XAUCHF=X`` gibt es dort nicht. Eine Funktion statt dreimal derselbe
    Dreizeiler: die Ticker-Sammlung, der Holdings-Loop und die Bewertung der
    transaktionslosen Positionen muessen zwingend denselben Ticker waehlen,
    sonst laedt der Batch einen Kurs, den der Loop nie abfragt.
    """
    yf_ticker = pos.yfinance_ticker or pos.ticker
    currency = pos.currency
    if pos.type == AssetType.crypto:
        currency = "USD"
    if pos.gold_org:
        from services.precious_metals_service import get_metal_futures
        fut = get_metal_futures(pos.ticker)
        if fut:
            yf_ticker, currency = fut
    return yf_ticker, currency


def _bucket_cashflow_by_date(all_txns, positions: dict, eligible_bucket_ids: set) -> dict:
    """Netto-Cashflow je (Bucket, Tag) fuer die Snapshot-Regeneration.

    ALLE Cashflows — auch Verkaeufe — werden ueber die aktuelle
    ``Position.bucket_id`` zugeordnet. Das ist bewusst **dieselbe** Quelle, aus
    der derselbe Replay den Bucket-WERT aggregiert (regenerate_snapshots bucht
    ``bucket_value_today[pos.bucket_id]``). Der cashflow-bereinigte Sub-Return
    ``(V_t - cf_t)/V_{t-1}`` setzt Wert und Cashflow desselben Buckets in
    Beziehung — kommen die beiden Seiten aus verschiedenen Quellen, zerreisst es
    die TWR-Kette **beider** betroffener Buckets.

    Regression (Prod 2026-06-25, RSG 56 Stk / CHF 9'786): Die frueher hier
    genutzte ``Transaction.bucket_id_at_sale`` buchte den Abfluss nach Satellite,
    waehrend der Wert-Replay ueber ``pos.bucket_id`` in Core lag. Ergebnis am
    selben Tag: Satellite ``(29'830 + 9'786)/28'654`` = **+38.3 %** Phantomgewinn,
    Core ``94'900/104'125`` = **-8.9 %** Phantomverlust. Ueber das Fenster
    16.05.-30.06. hob das Satellite auf +55.6 % statt rund +15 % und drueckte
    Core auf -4.4 % statt +5.4 % — beim Core kippt das Vorzeichen.

    ``bucket_id_at_sale`` bleibt korrekt fuer die **Realized-Attribution**
    (``total_return_service.list_realized_gains``: wo wurde der Gewinn erzielt) —
    das ist eine andere Frage als die, gegen welche Wertreihe der Fluss
    verrechnet wird. Spaetere Bucket-Wechsel fangen die Re-Label-Guards in
    ``bucket_performance_service`` ab, nicht die Cashflow-Attribution: der
    Wert-Replay verschiebt bei einem Wechsel die *gesamte* Historie der Position
    in den neuen Bucket (Wechsel sind prospektiv, kein Cost-Basis-Split), die
    Cashflow-Seite muss dem folgen.

    Buckets ausserhalb ``eligible_bucket_ids`` (PE/Immobilien) werden ignoriert.

    Returns: ``{bucket_id: {date: net_chf}}`` (INFLOW positiv, OUTFLOW negativ).
    """
    out: dict = {bid: defaultdict(float) for bid in eligible_bucket_ids}
    for txn in all_txns:
        pos = positions.get(str(txn.position_id))
        if pos is None:
            continue
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

    if pos.type in (AssetType.private_equity, AssetType.real_estate):
        return 0.0  # PE + Immobilien aus liquider Bewertung excluded (Invariante #2)
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
    if pos.type == AssetType.crypto and pos.coingecko_id:
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
    # Manuell gepflegter Kurs: current_price statt price:<Ticker>.
    cached = None if _has_manual_price(pos) else cache.get(f"price:{ticker}")
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
        if pos.type in (AssetType.cash, AssetType.pension) or _counts_as_cash(pos):
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
    # Pro Bucket NUR den letzten Snapshot vor snapshot_date laden (max(date)-
    # Join, SQLite-portabel) — vorher kam die komplette Historie als ORM-
    # Objekte zurueck und wuchs linear mit (Review 2026-07-02, M24).
    bucket_ids_list = [b.id for b in eligible]
    latest_sq = (
        select(
            BucketSnapshot.bucket_id.label("bucket_id"),
            func.max(BucketSnapshot.date).label("max_date"),
        )
        .where(
            BucketSnapshot.user_id == user_id,
            BucketSnapshot.bucket_id.in_(bucket_ids_list),
            BucketSnapshot.date < snapshot_date,
        )
        .group_by(BucketSnapshot.bucket_id)
        .subquery()
    )
    prev_q = await db.execute(
        select(BucketSnapshot)
        .join(
            latest_sq,
            (BucketSnapshot.bucket_id == latest_sq.c.bucket_id)
            & (BucketSnapshot.date == latest_sq.c.max_date),
        )
        .where(BucketSnapshot.user_id == user_id)
    )
    prev_by_bucket: dict[uuid.UUID, BucketSnapshot] = {
        s.bucket_id: s for s in prev_q.scalars()
    }

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


# ---------------------------------------------------------------------------
# Regeneration aus dem Ledger
# ---------------------------------------------------------------------------

# Felder, die der Replay liest. Er läuft in einem Thread und bekommt Kopien
# statt ORM-Objekten: so löst dort kein Attributzugriff einen DB-Zugriff aus.
_REPLAY_POSITION_FIELDS = (
    "type", "currency", "bucket_id", "shares", "cost_basis_chf",
    "ticker", "yfinance_ticker", "gold_org", "count_as_cash",
)
_REPLAY_TXN_FIELDS = ("position_id", "type", "date", "shares", "total_chf")

# Ein Yahoo-Kurs in price_cache, der höchstens so alt ist, belegt: Yahoo führt
# den Ticker. Fehlt dann die Kursreihe, ist der Download gestört (K079).
_PRICE_EVIDENCE_DAYS = 7

_NO_SERIES: tuple[list, list] = ([], [])


def _plain(obj, fields: tuple[str, ...]) -> SimpleNamespace:
    return SimpleNamespace(**{f: getattr(obj, f) for f in fields})


def _build_close_series(price_data, all_download: list[str]) -> dict[str, tuple[list[date], list[float]]] | None:
    """Close-Reihen je Ticker als sortierte ``(dates, values)``. Reine Funktion.

    ``None``: der Download für genau einen Ticker lieferte keine Close-Spalte.
    Pro Ticker einmal extrahieren, danach O(log n) bisect-Lookup pro Tag —
    statt col.loc[:ts].dropna() (Slice + Kopie) für jede (Position+FX) ×
    Kalendertag-Kombination (Review 2026-07-02, M22).
    """
    # Normalize to multi-index DataFrame with Close prices
    if len(all_download) == 1:
        single = all_download[0]
        if "Close" in price_data.columns:
            close_df = price_data[["Close"]].copy()
            close_df.columns = pd.MultiIndex.from_tuples([("Close", single)])
        else:
            return None
    else:
        if "Close" in price_data.columns:
            close_df = price_data["Close"]
        else:
            close_df = price_data

    series_by_ticker: dict[str, tuple[list[date], list[float]]] = {}
    for ticker in all_download:
        dates: list[date] = []
        values: list[float] = []
        try:
            if len(all_download) == 1:
                col = close_df[("Close", ticker)]
            else:
                col = close_df[ticker]
            series = col.dropna()
            dates = [d.date() if hasattr(d, "date") else d for d in series.index]
            values = [float(v) for v in series.values]
        except (KeyError, IndexError) as e:
            logger.debug(f"Could not build price series for {ticker}: {e}")
        series_by_ticker[ticker] = (dates, values)
    return series_by_ticker


def _close_on(
    series_by_ticker: dict[str, tuple[list[date], list[float]]], ticker: str, target_date: date
) -> float | None:
    """Letzter Schlusskurs am oder vor ``target_date``, sonst None."""
    dates, values = series_by_ticker.get(ticker, _NO_SERIES)
    if not dates:
        return None
    i = bisect.bisect_right(dates, target_date) - 1
    if i >= 0:
        return values[i]
    return None


def _replay_ledger(
    *,
    user_id: uuid.UUID,
    all_txns: list,
    positions: dict,
    first_date: date,
    today: date,
    series_by_ticker: dict[str, tuple[list[date], list[float]]],
    gbx_tickers: set[str],
    eligible_bucket_ids: list,
    current_per_share_chf: dict[str, float],
    static_pids: list[str],
    static_fallback_chf: dict[str, float],
    manual_pids: frozenset[str] = frozenset(),
) -> tuple[list[dict], list[dict]]:
    """Tages-Replay des Ledgers: Portfolio- und Bucket-Zeilen von ``first_date`` bis ``today``.

    Reine Funktion ohne DB- und Netzzugriff; läuft über ``asyncio.to_thread``,
    weil sie Tage × Positionen rechnet und sonst den Event-Loop blockiert
    (K007). ``all_txns`` und ``positions`` sind Kopien (``_plain``), keine
    ORM-Objekte.

    ``manual_pids``: Positionen mit manuell gepflegtem Kurs. Für sie liest der
    Replay keinen Yahoo-Schlusskurs. Er bewertet sie wie der Tageslauf mit dem
    heutigen Wert je Stück (``current_per_share_chf``) mal gehaltene Stück;
    sonst spränge die Reihe an der Grenze Regen→Tageslauf.

    Returns ``(portfolio_rows, bucket_rows)``, fertig für den Insert.
    """
    def get_close(ticker: str, target_date: date) -> float | None:
        return _close_on(series_by_ticker, ticker, target_date)

    eligible_set = set(eligible_bucket_ids)
    # Der Kurs-Ticker hängt nur an der Position, nicht am Tag.
    price_ticker = {pid: _resolve_price_ticker(pos) for pid, pos in positions.items()}

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
    # mit. ALLE Cashflows folgen der aktuellen Position.bucket_id — derselben
    # Quelle, aus der unten der Bucket-WERT aggregiert wird. Warum das zwingend
    # ist (und warum bucket_id_at_sale hier NICHT taugt): Docstring von
    # _bucket_cashflow_by_date.
    bucket_cf_by_date = _bucket_cashflow_by_date(all_txns, positions, eligible_set)
    bucket_rows: dict[uuid.UUID, list[dict]] = {bid: [] for bid in eligible_bucket_ids}

    # 7. Iterate day by day, building cumulative holdings and portfolio value
    current_holdings = defaultdict(float)  # position_id -> shares
    cost_basis = defaultdict(float)  # position_id -> cost_basis_chf
    batch_values = []
    current_date = first_date
    # Cashflows von Nicht-Snapshot-Tagen (Wochenende — z.B. Krypto-Kauf am
    # Samstag) auf den nächsten geschriebenen Tag aufrollen statt verwerfen
    # (Review 2026-07-02, M2: sonst liest der Snapshot-CF-Zweig von Dietz/XIRR
    # den Kauf als Marktgewinn).
    pending_cf = 0.0

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
        bucket_value_today: dict = defaultdict(float)
        bucket_cash_today: dict = defaultdict(float)
        # count_as_cash-Wertschriften (Geldmarkt-/T-Bill-ETF): ihr Marktwert
        # zaehlt in total_value_chf (Wertschriften-Loop) UND als Cash — sonst
        # weicht cash_chf nach dem Regen vom Daily-Recorder ab.
        cash_securities_today = 0.0

        for pid, shares in current_holdings.items():
            if shares <= 0:
                continue
            pos = positions.get(pid)
            if not pos:
                continue

            if pos.type in (AssetType.private_equity, AssetType.real_estate):
                continue  # PE + Immobilien komplett aus Snapshots excluded (Invariante #2)

            # Cash/pension: use cost basis as value (real_estate ist oben raus)
            priced = True
            if pos.type in (AssetType.cash, AssetType.pension):
                val = cost_basis.get(pid, 0)
                total_value_chf += val
            else:
                # Crypto quotiert auf yfinance in USD (z.B. BTC-USD), auch wenn
                # pos.currency faelschlich CHF ist → FX anwenden, sonst ~25 % zu
                # hoch (USD-Preis als CHF). Edelmetall ueber den Futures-Kontrakt.
                yf_ticker, currency = price_ticker[pid]

                # Manuell gepflegter Kurs: kein Yahoo-Schlusskurs, sondern der
                # heutige Wert je Stück wie im Tageslauf (siehe Docstring).
                manual = pid in manual_pids
                price = None if manual else get_close(yf_ticker, current_date)
                if price is None:
                    # Use cost basis as fallback
                    per = current_per_share_chf.get(pid) if manual else None
                    val = shares * per if per else cost_basis.get(pid, 0)
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

            # Bucket-Wert: historischer Preis wenn vorhanden, sonst aktueller
            # Marktwert × heute gehaltene Shares (Gold/Crypto-Fallback). Der
            # Portfolio-Total oben bleibt unveraendert (val).
            if pos.bucket_id in eligible_set:
                if priced:
                    bval = val
                else:
                    per = current_per_share_chf.get(pid)
                    bval = shares * per if per else cost_basis.get(pid, 0)
                bucket_value_today[pos.bucket_id] += bval

            # count_as_cash-ETF: Marktwert zusaetzlich als Cash fuehren (Portfolio
            # + Bucket), spiegelt _calc_portfolio_value_fast/_record_user_bucket_
            # snapshots. Keine Doppelzaehlung — val ist bereits in total_value_chf.
            if _counts_as_cash(pos):
                cash_securities_today += val
                if pos.bucket_id in eligible_set:
                    bucket_cash_today[pos.bucket_id] += (val if priced else bval)

        # Transaktionslose Positionen (physisches Edelmetall): konstante
        # Stueckzahl, aber taegliche Bewertung zum historischen Kurs. Faellt der
        # Kurs aus, greift der heutige Marktwert als Rueckfall — das ist das
        # alte Verhalten, jetzt aber nur noch als Notnagel statt als Regel.
        #
        # Sie zaehlen in total_value_chf UND (bei eligible Bucket) im
        # Bucket-Wert. Der Regen liess sie im Portfolio-Total frueher ganz aus,
        # weil er nur ueber current_holdings iteriert — das entsteht
        # ausschliesslich aus Transaktionen. Der Daily-Recorder
        # (_calc_portfolio_value_fast) bewertet dagegen ALLE aktiven Positionen.
        # Folge: nach jedem Regen war die komplette Snapshot-Historie um diesen
        # Betrag zu tief (Prod ~CHF 52'500 = 13 % des Portfolios), und der
        # naechste Daily-Snapshot sprang zurueck — beim >10%-Guard in
        # _record_user_snapshot als Phantom-Cashflow verbucht, was Dietz und
        # XIRR verfaelscht. Beide Pfade zaehlen jetzt dieselbe Menge.
        for pid in static_pids:
            pos = positions[pid]
            sh = float(pos.shares or 0)
            yf_ticker, currency = price_ticker[pid]
            # Manuell gepflegter Kurs: es bleibt beim heutigen Wert (sval).
            price = None if pid in manual_pids else get_close(yf_ticker, current_date)
            sval = static_fallback_chf.get(pid, 0.0)
            if price is not None:
                if yf_ticker in gbx_tickers:
                    price /= 100
                if currency == "CHF":
                    sval = sh * price
                else:
                    fx_price = get_close(f"{currency}CHF=X", current_date)
                    if fx_price:
                        sval = sh * price * fx_price
            total_value_chf += sval
            if _counts_as_cash(pos):
                cash_securities_today += sval
            if pos.bucket_id in eligible_set:
                bucket_value_today[pos.bucket_id] += sval
                if _counts_as_cash(pos):
                    bucket_cash_today[pos.bucket_id] += sval

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
            if cpos is not None and cpos.bucket_id in eligible_set:
                bucket_value_today[cpos.bucket_id] += val
                bucket_cash_today[cpos.bucket_id] += val
        total_value_chf += cash_chf_today
        # count_as_cash-ETFs sind schon in total_value_chf (Wertschriften-Loop) —
        # hier nur cash_chf erhoehen, nicht total.
        cash_chf_today += cash_securities_today

        # Collect snapshot for weekdays (batch insert later)
        pending_cf += cashflows_by_date.get(current_date, 0)
        if current_date.weekday() < 5 and current_date >= first_date:
            net_cf = pending_cf
            pending_cf = 0.0
            batch_values.append({
                "user_id": user_id,
                "date": current_date,
                "total_value_chf": round(total_value_chf, 2),
                "cash_chf": round(cash_chf_today, 2),
                "net_cash_flow_chf": round(net_cf, 2),
            })

        # Bucket-Snapshots: jeden Tag (inkl. Wochenende, wie der Daily-Recorder).
        # Transaktionslose Positionen (Gold) stecken bereits in
        # bucket_value_today — taeglich bewertet, nicht mehr als Konstante.
        for bid in eligible_bucket_ids:
            tv = bucket_value_today.get(bid, 0.0)
            bucket_rows[bid].append({
                "date": current_date,
                "total_value_chf": round(tv, 2),
                "cash_chf": round(bucket_cash_today.get(bid, 0.0), 2),
                "net_cash_flow_chf": round(bucket_cf_by_date[bid].get(current_date, 0.0), 2),
            })

        current_date += timedelta(days=1)

    # Bucket-Reihe mit cash-flow-bereinigtem Wealth-Index-Chain (ret>0-Guard wie
    # der Daily-Recorder). Damit erfassen TWR/Drawdown rueckdatierte Verkaeufe
    # korrekt als Outflow statt als Verlust.
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

    return batch_values, bucket_batch


async def _missing_price_series(
    db: AsyncSession,
    series_by_ticker: dict[str, tuple[list[date], list[float]]],
    required: set[str],
    today: date,
) -> list[str]:
    """Ticker, deren fehlende Kursreihe auf einen gestörten Download hinweist (K079).

    yf_download wirft bei einem Rate-Limit nicht, es liefert leere Reihen. Der
    Replay bewertet dann mit dem Einstandswert, und der Regen überschriebe die
    ganze Historie damit. Als Beleg dient price_cache: führt die Tabelle für
    einen Ticker einen Yahoo-Kurs, muss Yahoo auch eine Reihe liefern.

    - ``required`` (aktuell gehaltene Ticker und FX-Paare) mit Yahoo-Kurs der
      letzten ``_PRICE_EVIDENCE_DAYS`` Tage, aber ohne Reihe.
    - Alle Reihen leer, obwohl price_cache mindestens einen der Ticker kennt.

    Ticker, die Yahoo nie geführt hat, lösen nichts aus: für sie bleibt der
    Einstandswert die richtige Bewertung. Positionen mit manuell gepflegtem
    Kurs zählen nicht zu ``required``: der Replay liest ihre Reihe nicht.
    """
    from models.price_cache import PriceCache

    tickers = list(series_by_ticker)
    if not tickers:
        return []
    rows = (await db.execute(
        select(PriceCache.ticker, func.max(PriceCache.date))
        .where(PriceCache.ticker.in_(tickers), PriceCache.source == "yahoo")
        .group_by(PriceCache.ticker)
    )).all()
    last_yahoo_price = {ticker: last for ticker, last in rows}

    empty = [t for t in tickers if not series_by_ticker[t][0]]
    if len(empty) == len(tickers) and last_yahoo_price:
        return sorted(last_yahoo_price)

    fresh_from = today - timedelta(days=_PRICE_EVIDENCE_DAYS)
    return sorted(
        t for t in empty
        if t in required and t in last_yahoo_price and last_yahoo_price[t] >= fresh_from
    )


async def regenerate_snapshots(
    db: AsyncSession, user_id: uuid.UUID, *, wait_for_lock: bool = True
) -> dict:
    """Regenerate all portfolio snapshots from transaction history + historical prices.

    Läuft je Nutzer nie parallel (K076): die Sperre wird vor dem Lesen des
    Ledgers genommen und gilt bis zum Commit. ``wait_for_lock=False`` wirft
    ``SnapshotLockBusy``, statt auf einen laufenden Regen zu warten.
    """
    await _lock_user_snapshots(db, user_id, wait=wait_for_lock)

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

    # Deckel (K006): der Replay rechnet jeden Kalendertag seit der ersten
    # Transaktion und schreibt je Tag und Bucket eine Zeile. Ein Datum weit in
    # der Vergangenheit (Tippfehler, Altbestand von vor der Datumsprüfung)
    # ergäbe Millionen Zeilen.
    if (today - first_date).days > MAX_REGEN_SPAN_DAYS:
        logger.warning(
            f"Snapshot regen refused for user {user_id}: span since {first_date} "
            f"exceeds {MAX_REGEN_SPAN_DAYS} days"
        )
        return {
            "snapshots_created": 0,
            "error": (
                f"Die erste Transaktion ({first_date.isoformat()}) liegt mehr als "
                f"{MAX_REGEN_SPAN_DAYS} Tage zurück. Snapshots wurden nicht neu berechnet."
            ),
        }

    # 3. Collect yfinance tickers and FX pairs needed
    tickers_needed = set()
    fx_pairs_needed = set()
    # Aktuell gehaltene Kurs-Ticker: für sie muss eine Kursreihe vorliegen (K079).
    held_tickers = set()
    for pos in positions.values():
        if pos.type in (AssetType.cash, AssetType.pension, AssetType.real_estate, AssetType.private_equity):
            # Cash/Pension brauchen keinen Kurs, aber bei Fremdwährung den
            # FX-Kurs für die Saldo-Konvertierung (H8).
            if pos.type in (AssetType.cash, AssetType.pension) and pos.currency != "CHF":
                fx_pairs_needed.add(f"{pos.currency}CHF=X")
            continue
        yf_ticker, currency = _resolve_price_ticker(pos)
        tickers_needed.add(yf_ticker)
        if (
            pos.is_active and float(pos.shares or 0) > 0
            and not _replays_at_manual_price(pos)
        ):
            held_tickers.add(yf_ticker)
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

    series_by_ticker = await asyncio.to_thread(_build_close_series, price_data, all_download)
    if series_by_ticker is None:
        return {"snapshots_created": 0, "error": "No price data returned"}

    # Vor jedem Löschen: fehlen Kursreihen, die Yahoo liefern müsste, bleiben
    # die alten Snapshots stehen (K079).
    missing = await _missing_price_series(
        db, series_by_ticker, held_tickers | fx_pairs_needed, today
    )
    if missing:
        logger.warning(
            f"Snapshot regen aborted for user {user_id}: no price series for "
            f"{len(missing)} ticker(s) known to price_cache: {missing[:10]}"
        )
        return {
            "snapshots_created": 0,
            "error": (
                "Kursdaten unvollständig (Datenquelle nicht erreichbar). "
                "Die bestehenden Snapshots bleiben unverändert."
            ),
            "missing_price_series": missing,
        }

    # 5. Detect GBX (pence) tickers — .L ETFs where yfinance returns pence instead of pounds
    gbx_tickers = set()
    quote_currency_checks: list[str] = []
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
            yf_price = _close_on(series_by_ticker, yf_ticker, first_buy.date)
            buy_price = float(first_buy.price_per_share)
            if yf_price and buy_price > 0:
                ratio = yf_price / buy_price
                if 50 < ratio < 200:
                    gbx_tickers.add(yf_ticker)
                    logger.info(f"Detected GBX pricing for {yf_ticker} (ratio={ratio:.1f})")
            elif series_by_ticker.get(yf_ticker, _NO_SERIES)[0]:
                # Kein Yahoo-Kurs am oder vor dem Kauftag (die Reihe beginnt
                # später): dem Ratio-Vergleich fehlt der Referenzpreis. Ohne
                # Prüfung stünde ein Pence-Titel 100-fach zu hoch in der
                # Historie. Deshalb die Notierungswährung fragen wie im Zweig
                # darunter. Ohne Reihe gibt es nichts zu bewerten.
                quote_currency_checks.append(yf_ticker)
        else:
            # Ohne Kauf-Transaktion gibt es keinen Referenzpreis fuer den
            # Ratio-Vergleich — transaktionslose Positionen (Bestandserfassung)
            # haben strukturell keinen. Seit ihre Bewertung taeglich ueber den
            # Kurs laeuft, wuerde eine Pence-notierte .L-Position sonst 100x zu
            # hoch bewertet. Deshalb hier die Notierungswaehrung direkt fragen
            # (7d gecacht, spiegelt die GBX-Regel: nie aus dem Suffix raten).
            quote_currency_checks.append(yf_ticker)

    if quote_currency_checks:
        # Gebündelt im Thread: bei kaltem Cache ist _quote_currency ein
        # blockierender yfinance-Abruf (K131).
        from services.cache_service import _quote_currency

        def _quote_currencies() -> dict[str, str | None]:
            found: dict[str, str | None] = {}
            for yf_ticker in dict.fromkeys(quote_currency_checks):
                try:
                    found[yf_ticker] = _quote_currency(yf_ticker)
                except Exception as e:
                    logger.warning(f"GBX-Pruefung fuer {yf_ticker} fehlgeschlagen: {e}")
                    found[yf_ticker] = None
            return found

        quote_currencies = await asyncio.to_thread(_quote_currencies)
        for yf_ticker in sorted(quote_currencies):
            quote_ccy = quote_currencies[yf_ticker]
            if quote_ccy == "GBp":
                gbx_tickers.add(yf_ticker)
                logger.info(f"Detected GBX pricing for {yf_ticker} (quote currency)")
            elif quote_ccy is None and yf_ticker not in gbx_tickers:
                # Notierungswährung unbekannt (Yahoo-Fehler, Lock-Frist): ob die
                # Reihe in Pence oder Pfund steht, ist offen. Mit Divisor 1.0
                # stünde ein Pence-Titel 100-fach zu hoch in der ganzen Historie.
                # Ohne Reihe greift im Replay der Rückfall wie bei fehlendem Kurs.
                series_by_ticker[yf_ticker] = _NO_SERIES
                logger.warning(
                    f"Quote currency unknown for {yf_ticker}: price series ignored in snapshot regen"
                )

    buckets_q = await db.execute(
        select(Bucket).where(Bucket.user_id == user_id, Bucket.deleted_at.is_(None))
    )
    eligible_bucket_ids = [
        b.id for b in buckets_q.scalars().all()
        if b.system_role not in _EXCLUDED_FROM_BUCKET_SUMS
    ]

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
    # Positionen ohne jede Transaktion (typisch: physisches Edelmetall, per
    # Bestandserfassung angelegt). Sie tauchen nie in current_holdings auf, ihre
    # Stueckzahl ist ueber die ganze Historie konstant — bewertet werden sie
    # trotzdem taeglich zum historischen Kurs. Vorher lag ihr HEUTIGER Wert als
    # Konstante ueber der gesamten Reihe: der Bucket stand still, jeder
    # TWR-Faktor war exakt 1.0, und compare_to_benchmark meldete null statt
    # einer Rendite (Prod: Hard Money, 213 Tage konstant 52'523.19).
    static_pids: list[str] = []
    static_fallback_chf: dict[str, float] = {}
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
        if pid not in positions_with_txns:
            static_pids.append(pid)
            static_fallback_chf[pid] = cur_total

    # 6./7. Tages-Replay im Thread (K007): Tage × Positionen ohne await blockierten
    # sonst den Event-Loop für alle Requests dieses Prozesses.
    batch_values, bucket_batch = await asyncio.to_thread(
        _replay_ledger,
        user_id=user_id,
        all_txns=[_plain(t, _REPLAY_TXN_FIELDS) for t in all_txns],
        positions={pid: _plain(p, _REPLAY_POSITION_FIELDS) for pid, p in positions.items()},
        first_date=first_date,
        today=today,
        series_by_ticker=series_by_ticker,
        gbx_tickers=gbx_tickers,
        eligible_bucket_ids=eligible_bucket_ids,
        current_per_share_chf=current_per_share_chf,
        static_pids=static_pids,
        static_fallback_chf=static_fallback_chf,
        manual_pids=frozenset(
            pid for pid, pos in positions.items() if _replays_at_manual_price(pos)
        ),
    )
    snapshots_created = len(batch_values)

    # 8. Alte Snapshots löschen und die Reihe neu schreiben. Die Zeilen gehen
    # als executemany an den Treiber (K056): ein Statement, einmal kompiliert,
    # statt je 500 Zeilen ein eigenes VALUES-Statement.
    await db.execute(
        delete(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
    )
    if batch_values:
        stmt = pg_insert(PortfolioSnapshot)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_snapshot_user_date",
            set_={
                "total_value_chf": stmt.excluded.total_value_chf,
                "cash_chf": stmt.excluded.cash_chf,
                "net_cash_flow_chf": stmt.excluded.net_cash_flow_chf,
            },
        )
        await db.execute(stmt, batch_values)

    # Bucket-Snapshots neu aufbauen: alte (stale) Rows loeschen, Reihe aus dem
    # Replay neu schreiben. ON CONFLICT wie beim Tages-Snapshot: schreibt ein
    # anderer Pfad dieselbe Zeile, gewinnt der Regen statt abzubrechen (K076).
    bucket_count = 0
    if eligible_bucket_ids:
        await db.execute(
            delete(BucketSnapshot).where(BucketSnapshot.user_id == user_id)
        )
        if bucket_batch:
            stmt = pg_insert(BucketSnapshot)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_bucket_snapshot",
                set_={
                    "total_value_chf": stmt.excluded.total_value_chf,
                    "cash_chf": stmt.excluded.cash_chf,
                    "net_cash_flow_chf": stmt.excluded.net_cash_flow_chf,
                    "running_peak_chf": stmt.excluded.running_peak_chf,
                    "wealth_index": stmt.excluded.wealth_index,
                    "running_peak_wealth_index": stmt.excluded.running_peak_wealth_index,
                },
            )
            await db.execute(stmt, bucket_batch)
        bucket_count = len(bucket_batch)

    await db.commit()
    # Monatsrenditen, Total-Return und Historie lesen die Snapshots: ihre
    # Cache-Einträge gelten ab jetzt nicht mehr (K039).
    from services.portfolio_service import bump_portfolio_cache_version
    bump_portfolio_cache_version(user_id)
    logger.info(
        f"Regenerated {snapshots_created} portfolio + {bucket_count} bucket snapshots "
        f"for user {user_id} ({first_date} to {today})"
    )

    return {
        "snapshots_created": snapshots_created,
        "bucket_snapshots_created": bucket_count,
        "date_range": {"from": first_date.isoformat(), "to": today.isoformat()},
    }


async def refresh_today_snapshot(user_id: uuid.UUID) -> None:
    """Schreibt den heutigen Snapshot eines Nutzers neu (Portfolio und Buckets).

    Für Buchungen mit Datum heute (K001): der Tageslauf von 07:00 hat den
    Snapshot meist schon geschrieben, und der Lauf des Folgetags summiert nur
    die Cashflows nach dem heutigen Snapshot. Ohne Neuschreiben fehlt der
    Cashflow dauerhaft in net_cash_flow_chf. Gleicher Weg wie der Tageslauf: gecachte Kurse, kein
    Yahoo-Abruf, Upsert.
    """
    async with async_session() as db:
        await _record_user_snapshot(db, user_id, date.today())
        await db.commit()
    from services.portfolio_service import bump_portfolio_cache_version
    bump_portfolio_cache_version(user_id)
