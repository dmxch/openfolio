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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.pending_order import PendingOrder
from models.price_cache import PriceCache
from services import cache as app_cache

logger = logging.getLogger(__name__)


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
