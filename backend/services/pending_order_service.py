"""Service-Layer fuer manuell gepflegte Limit-Orders.

Drei Verantwortlichkeiten:

* ``compute_effective_status`` — mappt den DB-Roh-Status auf den Business-
  Status. Insbesondere: GTD-Orders mit abgelaufenem ``expiry_date`` zaehlen
  effektiv als ``expired``, ohne dass der DB-Wert geaendert werden muss.
* ``compute_distance_pct`` — signed Abstand zum Trigger. Positiv = Order
  noch nicht erreicht, negativ = Spot hat Trigger durchbrochen, ``None`` bei
  Currency-Mismatch oder fehlendem Quote (kein FX-Convert in MVP, sonst
  Muell bei .L-Tickern in GBX vs. GBP).
* ``get_pending_orders`` / ``get_digest_buckets`` — Read-Endpoints fuer
  Internal/External API und fuer den Daily-Digest.

Counts sind IMMER ueber alle Records des Users (ungefiltert), damit das
Frontend Tab-Badges (``Offen 7 / Erledigt 24 / Alle 31``) konsistent zeigen
kann, egal welcher Filter aktiv ist.
"""

import logging
import uuid
from collections import defaultdict
from datetime import date as _date, timedelta as _td
from decimal import Decimal
from typing import Iterable, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dateutils import utcnow
from models.pending_order import PendingOrder
from models.position import Position
from models.price_cache import PriceCache
from models.transaction import Transaction, TransactionType
from services import cache as app_cache

logger = logging.getLogger(__name__)

# Auto-Fill-Reconciliation: eine offene Order gilt als gefuellt, wenn eine
# buy/sell-Transaktion mit exakt gleicher Stueckzahl, gleichem Ticker und gleicher
# Seite innerhalb dieses Fensters auftaucht (analog zum Dividenden-Matcher).
ORDER_FILL_MATCH_WINDOW_DAYS = 35


def compute_effective_status(order: PendingOrder, today: _date) -> str:
    """DB-Roh-Status auf Business-Status mappen (GTD-Expiry)."""
    if order.status != "open":
        return order.status
    if (
        order.expiry_type == "gtd"
        and order.expiry_date is not None
        and order.expiry_date < today
    ):
        return "expired"
    return "open"


def compute_distance_pct(
    side: str,
    limit_price: Decimal,
    current_price: Decimal | None,
    order_currency: str,
    quote_currency: str | None,
) -> Decimal | None:
    """Signed Abstand zum Trigger.

    Positiv:  Order noch nicht erreicht (Spot muss sich noch bewegen).
    Negativ:  Spot hat Trigger bereits durchbrochen.
    None:     kein Quote ODER Currency-Mismatch.

    BUY:  (current - limit) / current  — $90 BUY @ Spot $100 -> +0.10
    SELL: (limit - current) / current  — $120 SELL @ Spot $100 -> +0.20
    """
    if current_price is None:
        return None
    if current_price <= 0:
        return None
    if quote_currency is None or quote_currency.upper() != order_currency.upper():
        return None
    if side == "buy":
        return (current_price - limit_price) / current_price
    return (limit_price - current_price) / current_price


def _serialize(
    order: PendingOrder,
    today: _date,
    quote: dict | None,
) -> dict:
    """Convert a PendingOrder + (optional) quote into the API response shape."""
    current_price_dec: Decimal | None = None
    quote_currency: str | None = None
    if quote and quote.get("price") is not None:
        try:
            current_price_dec = Decimal(str(quote["price"]))
        except Exception:
            current_price_dec = None
        quote_currency = quote.get("currency")

    distance = compute_distance_pct(
        side=order.side,
        limit_price=Decimal(str(order.limit_price)),
        current_price=current_price_dec,
        order_currency=order.currency,
        quote_currency=quote_currency,
    )

    return {
        "id": str(order.id),
        "ticker": order.ticker,
        "side": order.side,
        "shares": float(order.shares),
        "limit_price": float(order.limit_price),
        "stop_price": float(order.stop_price) if order.stop_price is not None else None,
        "currency": order.currency,
        "expiry_type": order.expiry_type,
        "expiry_date": order.expiry_date.isoformat() if order.expiry_date else None,
        "broker": order.broker,
        "bucket_id_target": (
            str(order.bucket_id_target)
            if order.bucket_id_target is not None
            else None
        ),
        "status": order.status,
        "effective_status": compute_effective_status(order, today),
        "linked_transaction_id": (
            str(order.linked_transaction_id)
            if order.linked_transaction_id is not None
            else None
        ),
        "notes": order.notes,
        "notes_last_api_write_at": (
            order.notes_last_api_write_at.isoformat()
            if order.notes_last_api_write_at
            else None
        ),
        "notes_last_api_token_name": order.notes_last_api_token_name,
        "current_price": float(current_price_dec) if current_price_dec is not None else None,
        "quote_currency": quote_currency,
        "distance_pct": float(distance) if distance is not None else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


async def _fetch_quotes(db: AsyncSession, tickers: Iterable[str]) -> dict[str, dict]:
    """Memory-Cache zuerst, dann PriceCache (letzte 7 Tage) als Fallback.

    Liefert Dict ticker -> {"price": float, "currency": str}. Tickers ohne
    Quote fehlen im Result. Async-safe: kein Live-yfinance-Fetch hier.
    """
    tickers_set = {t for t in tickers if t}
    if not tickers_set:
        return {}

    quotes: dict[str, dict] = {}
    missing: list[str] = []
    for t in tickers_set:
        cached = app_cache.get(f"price:{t}")
        if cached and cached.get("price") is not None:
            quotes[t] = {"price": cached["price"], "currency": cached.get("currency", "USD")}
        else:
            missing.append(t)

    if missing:
        recent_cutoff = _date.today() - _td(days=7)
        result = await db.execute(
            select(PriceCache)
            .where(PriceCache.ticker.in_(missing), PriceCache.date >= recent_cutoff)
            .order_by(PriceCache.ticker, PriceCache.date.desc())
        )
        latest_per_ticker: dict[str, PriceCache] = {}
        for pc in result.scalars().all():
            if pc.ticker not in latest_per_ticker:
                latest_per_ticker[pc.ticker] = pc
        for ticker, pc in latest_per_ticker.items():
            quotes[ticker] = {"price": float(pc.close), "currency": pc.currency}

    return quotes


async def get_pending_orders(
    db: AsyncSession,
    user_id: uuid.UUID,
    status_filter: Literal["open", "closed", "all"] = "open",
) -> dict:
    """Liste der Pending Orders eines Users.

    Counts immer ueber alle 4 effective-Buckets (ungefiltert).
    Items gefiltert nach ``status_filter``:

    - ``open``   -> effective_status='open'
                    (DB-status='open' AND NOT effectively-expired)
    - ``closed`` -> effective_status in ('filled','cancelled','expired')
    - ``all``    -> alle
    """
    today = _date.today()

    # Lade alle Orders einmal — Counts und Filter werden in Memory berechnet.
    # Bei MAX_PENDING_ORDERS_PER_USER=100 ist das billiger als zwei Queries.
    result = await db.execute(
        select(PendingOrder)
        .where(PendingOrder.user_id == user_id)
        .order_by(PendingOrder.created_at.desc())
    )
    all_orders = list(result.scalars().all())

    counts: dict[str, int] = {"open": 0, "filled": 0, "cancelled": 0, "expired": 0}
    for o in all_orders:
        eff = compute_effective_status(o, today)
        counts[eff] = counts.get(eff, 0) + 1

    if status_filter == "open":
        filtered = [o for o in all_orders if compute_effective_status(o, today) == "open"]
    elif status_filter == "closed":
        filtered = [
            o for o in all_orders
            if compute_effective_status(o, today) in ("filled", "cancelled", "expired")
        ]
    else:
        filtered = all_orders

    quotes = await _fetch_quotes(db, [o.ticker for o in filtered])
    items = [_serialize(o, today, quotes.get(o.ticker)) for o in filtered]

    return {"items": items, "counts": counts}


async def get_digest_buckets(
    db: AsyncSession,
    user_id: uuid.UUID,
    near_threshold: Decimal = Decimal("0.02"),
) -> dict:
    """Buckets fuer den Daily-Digest.

    Beide Buckets nur ueber effective_status='open'. Currency-Mismatch / kein
    Quote (distance_pct=None) erscheint in keinem Bucket — kein verlaesslicher
    Vergleich, kein Alarm.

    Returns:
        {
            "near":     [orders mit 0 <= distance_pct <= near_threshold],
            "breached": [orders mit distance_pct < 0],
        }
        beide sortiert nach distance_pct aufsteigend (am dichtesten dran zuerst).
    """
    today = _date.today()
    result = await db.execute(
        select(PendingOrder).where(
            PendingOrder.user_id == user_id,
            PendingOrder.status == "open",
        )
    )
    open_orders = [
        o for o in result.scalars().all()
        if compute_effective_status(o, today) == "open"
    ]
    if not open_orders:
        return {"near": [], "breached": []}

    quotes = await _fetch_quotes(db, [o.ticker for o in open_orders])

    near: list[dict] = []
    breached: list[dict] = []
    for o in open_orders:
        serialized = _serialize(o, today, quotes.get(o.ticker))
        d = serialized.get("distance_pct")
        if d is None:
            continue
        d_dec = Decimal(str(d))
        if d_dec < 0:
            breached.append(serialized)
        elif d_dec <= near_threshold:
            near.append(serialized)

    near.sort(key=lambda x: x["distance_pct"])
    breached.sort(key=lambda x: x["distance_pct"])
    return {"near": near, "breached": breached}


# --- Auto-Fill-Reconciliation ----------------------------------------------


async def try_auto_fill_order(
    db: AsyncSession,
    txn: Transaction,
    user_id: uuid.UUID,
) -> PendingOrder | None:
    """Markiert eine offene Order als ``filled``, wenn eine passende buy/sell-
    Transaktion auftaucht — ohne eine neue Transaktion zu erzeugen (die existiert
    bereits; das unterscheidet diesen Pfad vom manuellen ``/fill``).

    Match-Kriterien (bewusst streng, ein Fehl-Match korrumpiert die Buchhaltung):
    gleicher User, gleicher Ticker (case-insensitiv), gleiche Seite, **exakt**
    gleiche Stueckzahl, Status ``open``, noch nicht verlinkt, und Order-Anlage
    innerhalb ±35d des Transaktionsdatums. Bei mehreren Treffern: aelteste offene
    Order zuerst (FIFO). Best-effort; Fehler werden vom aufrufenden Hook
    geschluckt. Auto-Cancel ist NICHT ableitbar (kein Signal in Transaktionen).
    """
    if txn.type not in (TransactionType.buy, TransactionType.sell):
        return None

    # Diese Transaktion ist bereits an eine Order verlinkt (z.B. via /fill) →
    # nicht erneut eine andere offene Order daran haengen.
    already = await db.execute(
        select(PendingOrder.id).where(PendingOrder.linked_transaction_id == txn.id).limit(1)
    )
    if already.first() is not None:
        return None

    pos = await db.get(Position, txn.position_id)
    if pos is None or not pos.ticker:
        return None

    window_start = txn.date - _td(days=ORDER_FILL_MATCH_WINDOW_DAYS)
    window_end_excl = txn.date + _td(days=ORDER_FILL_MATCH_WINDOW_DAYS + 1)

    result = await db.execute(
        select(PendingOrder)
        .where(
            PendingOrder.user_id == user_id,
            PendingOrder.status == "open",
            PendingOrder.linked_transaction_id.is_(None),
            func.upper(PendingOrder.ticker) == pos.ticker.upper(),
            PendingOrder.side == txn.type.value,
            PendingOrder.shares == txn.shares,
            PendingOrder.created_at >= window_start,
            PendingOrder.created_at < window_end_excl,
        )
        .order_by(PendingOrder.created_at.asc())
        .limit(1)
    )
    order = result.scalars().first()
    if order is None:
        return None

    order.status = "filled"
    order.linked_transaction_id = txn.id
    order.updated_at = utcnow()
    await db.commit()
    logger.info(
        "order_auto_fill user=%s order=%s ticker=%s side=%s shares=%s txn=%s txn_date=%s",
        user_id, order.id, pos.ticker, order.side, order.shares, txn.id, txn.date,
    )
    return order


async def try_auto_fill_orders_bulk(
    db: AsyncSession,
    txns: Iterable[Transaction],
    user_id: uuid.UUID,
) -> int:
    """Bulk-Variante fuer den CSV-Import-Hook. Liefert Anzahl Auto-Fills."""
    matches = 0
    for txn in txns:
        try:
            if await try_auto_fill_order(db, txn, user_id) is not None:
                matches += 1
        except Exception as e:
            logger.warning("order_bulk_fill_failed txn=%s error=%s", txn.id, e)
    return matches
