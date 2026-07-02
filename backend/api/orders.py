"""Internal API fuer manuell gepflegte Pending-Orders.

Endpoints:
    GET    /api/orders/pending                Liste mit counts/items
    POST   /api/orders/pending                Anlegen
    PATCH  /api/orders/pending/{order_id}     Update (filled-Schreibschutz)
    DELETE /api/orders/pending/{order_id}     Hartes Loeschen
    POST   /api/orders/pending/{order_id}/fill   Atomar Transaction + Status

JWT-Auth via ``get_current_user``. Externe Variante mit X-API-Key liegt in
``api/external_v1.py``.

Status-Wechsel auf ``filled`` ist im PATCH-Schema bereits durch das Literal
ausgeschlossen — der einzige Weg dorthin fuehrt ueber ``/fill``, das eine
Transaction anlegt und ``linked_transaction_id`` setzt. Damit ist die
Pending-Liste nicht von der Buchhaltung entkoppelbar.

Schreibschutz fuer gefillte Orders: nach erfolgtem Fill darf nur noch
``notes`` geaendert werden — alle anderen Felder im Body fuehren zu 400.
"""

import datetime
import logging
import uuid
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from api.portfolio import invalidate_portfolio_cache
from auth import get_current_user
from constants.limits import (
    MAX_PENDING_ORDERS_PER_USER,
    MAX_POSITIONS_PER_USER,
    MAX_TRANSACTIONS_PER_USER,
)
from db import get_db
from models.pending_order import PendingOrder
from models.position import AssetType, Position, PriceSource
from models.transaction import Transaction, TransactionType
from models.user import User
from services.encryption_helpers import encrypt_field
from services.pending_order_service import get_pending_orders
from services.snapshot_trigger import trigger_snapshot_regen
from services.transaction_service import apply_transaction_to_position

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["orders"])


# --- Schemas ---


class PendingOrderCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=30)
    side: Literal["buy", "sell"]
    shares: Decimal = Field(gt=0)
    limit_price: Decimal = Field(gt=0)
    stop_price: Optional[Decimal] = Field(default=None, gt=0)
    currency: str = Field(default="USD", min_length=1, max_length=10)
    expiry_type: Literal["gtc", "day", "gtd"] = "gtc"
    expiry_date: Optional[datetime.date] = None
    broker: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=2000)
    bucket_id_target: Optional[uuid.UUID] = None

    @model_validator(mode="after")
    def _gtd_requires_date(self):
        if self.expiry_type == "gtd" and self.expiry_date is None:
            raise ValueError("expiry_date ist bei expiry_type='gtd' Pflicht")
        if self.expiry_type != "gtd" and self.expiry_date is not None:
            raise ValueError("expiry_date nur bei expiry_type='gtd' erlaubt")
        return self


class PendingOrderUpdate(BaseModel):
    """PATCH-Body. Status-Wechsel auf ``filled`` laeuft AUSSCHLIESSLICH ueber /fill."""

    side: Optional[Literal["buy", "sell"]] = None
    shares: Optional[Decimal] = Field(default=None, gt=0)
    limit_price: Optional[Decimal] = Field(default=None, gt=0)
    stop_price: Optional[Decimal] = Field(default=None, gt=0)
    currency: Optional[str] = Field(default=None, min_length=1, max_length=10)
    expiry_type: Optional[Literal["gtc", "day", "gtd"]] = None
    expiry_date: Optional[datetime.date] = None
    broker: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=2000)
    bucket_id_target: Optional[uuid.UUID] = None
    status: Optional[Literal["open", "cancelled"]] = None


class PendingOrderFill(BaseModel):
    price_per_share: Decimal = Field(gt=0)
    fill_date: datetime.date
    fees_chf: Decimal = Field(default=Decimal("0"), ge=0)
    taxes_chf: Decimal = Field(default=Decimal("0"), ge=0)
    fx_rate_to_chf: Decimal = Field(default=Decimal("1.0"), gt=0)
    currency: Optional[str] = Field(default=None, min_length=1, max_length=10)
    notes: Optional[str] = Field(default=None, max_length=2000)


# --- Internal helpers ---


_FILLED_EDITABLE_FIELDS = {"notes"}


def _validate_filled_patch(order: PendingOrder, patch: dict) -> None:
    """Wenn die Order gefilled ist, darf nur ``notes`` mutiert werden.

    ``status`` als Wert ``open`` oder ``cancelled`` waere ein Drift-Risiko —
    eine gefillte Order soll auch nicht zurueck auf 'open' gesetzt werden.
    """
    if order.status != "filled":
        return
    illegal = set(patch.keys()) - _FILLED_EDITABLE_FIELDS
    if illegal:
        raise HTTPException(
            status_code=400,
            detail=(
                "Gefillte Order ist historisch — nur 'notes' editierbar. "
                f"Abgelehnte Felder: {sorted(illegal)}"
            ),
        )


async def _count_user_orders(db: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(PendingOrder)
            .where(PendingOrder.user_id == user_id)
        )
    ) or 0


def _serialize_minimal(order: PendingOrder) -> dict:
    """Compact response after mutation — full read goes through GET."""
    from services.pending_order_service import compute_effective_status

    today = datetime.date.today()
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
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


# --- Endpoints ---


@router.get("/pending")
@limiter.limit("30/minute")
async def list_pending_orders(
    request: Request,
    status: Literal["open", "closed", "all"] = Query(default="open"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Liste der Pending Orders. ``counts`` immer ungefiltert, ``items`` gefiltert."""
    return await get_pending_orders(db, user.id, status_filter=status)


@router.post("/pending", status_code=201)
@limiter.limit("30/minute")
async def create_pending_order(
    request: Request,
    data: PendingOrderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count = await _count_user_orders(db, user.id)
    if count >= MAX_PENDING_ORDERS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Pending-Order-Limit erreicht (max. {MAX_PENDING_ORDERS_PER_USER} Einträge)",
        )

    bucket_id_target = None
    if data.bucket_id_target is not None:
        from models.bucket import Bucket
        b_q = await db.execute(
            select(Bucket).where(
                Bucket.id == data.bucket_id_target,
                Bucket.user_id == user.id,
                Bucket.deleted_at.is_(None),
            )
        )
        if b_q.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Ungültiger Bucket")
        bucket_id_target = data.bucket_id_target

    order = PendingOrder(
        id=uuid.uuid4(),
        user_id=user.id,
        ticker=data.ticker.strip().upper(),
        side=data.side,
        shares=data.shares,
        limit_price=data.limit_price,
        stop_price=data.stop_price,
        currency=data.currency.upper(),
        expiry_type=data.expiry_type,
        expiry_date=data.expiry_date,
        broker=data.broker,
        notes=data.notes,
        bucket_id_target=bucket_id_target,
        status="open",
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return _serialize_minimal(order)


@router.patch("/pending/{order_id}")
@limiter.limit("30/minute")
async def update_pending_order(
    request: Request,
    order_id: uuid.UUID,
    data: PendingOrderUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = await db.get(PendingOrder, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pending Order nicht gefunden")

    patch = data.model_dump(exclude_unset=True)
    if not patch:
        return _serialize_minimal(order)

    _validate_filled_patch(order, patch)

    # GTD-Konsistenz auf das Endresultat pruefen (nicht nur das Patch).
    new_expiry_type = patch.get("expiry_type", order.expiry_type)
    new_expiry_date = patch.get("expiry_date", order.expiry_date)
    if new_expiry_type == "gtd" and new_expiry_date is None:
        raise HTTPException(
            status_code=422,
            detail="expiry_date ist bei expiry_type='gtd' Pflicht",
        )
    if new_expiry_type != "gtd" and new_expiry_date is not None:
        raise HTTPException(
            status_code=422,
            detail="expiry_date nur bei expiry_type='gtd' erlaubt",
        )

    if "ticker" in patch:
        patch["ticker"] = patch["ticker"].strip().upper()
    if "currency" in patch and patch["currency"]:
        patch["currency"] = patch["currency"].upper()
    if "bucket_id_target" in patch and patch["bucket_id_target"] is not None:
        from models.bucket import Bucket
        b_q = await db.execute(
            select(Bucket).where(
                Bucket.id == patch["bucket_id_target"],
                Bucket.user_id == user.id,
                Bucket.deleted_at.is_(None),
            )
        )
        if b_q.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Ungültiger Bucket")

    for key, val in patch.items():
        setattr(order, key, val)

    if "notes" in patch:
        order.notes_last_api_write_at = None
        order.notes_last_api_token_name = None

    await db.commit()
    await db.refresh(order)
    return _serialize_minimal(order)


@router.delete("/pending/{order_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_pending_order(
    request: Request,
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = await db.get(PendingOrder, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pending Order nicht gefunden")

    await db.delete(order)
    await db.commit()


# --- Fill: atomar Transaction anlegen + Status setzen ---


async def _resolve_or_create_position(
    db: AsyncSession,
    user: User,
    ticker: str,
    currency: str,
    bucket_id_hint: uuid.UUID | None = None,
) -> tuple[Position, bool]:
    """Position zum Ticker laden, sonst minimal anlegen (best-effort yfinance-Lookup).

    Spiegelt das Verhalten des bestehenden ``create_transaction``-Endpoints,
    ohne dessen ganzes Stop-Loss-Vorab-Validation-Geschaeft. Returns
    ``(position, created)``.
    """
    ticker_norm = ticker.strip().upper()
    result = await db.execute(
        select(Position).where(
            Position.user_id == user.id,
            Position.ticker == ticker_norm,
        )
    )
    pos = result.scalar_one_or_none()
    if pos is not None:
        return pos, False

    pos_count = await db.scalar(
        select(func.count()).select_from(Position).where(Position.user_id == user.id)
    )
    if (pos_count or 0) >= MAX_POSITIONS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximale Anzahl Positionen erreicht ({MAX_POSITIONS_PER_USER})",
        )

    name = ticker_norm
    pos_currency = currency.upper() if currency else "USD"
    try:
        # yf_patch-Wrapper + Redis-Cache statt rohem yf.Ticker().info
        # (429-anfaellig, kein Lock) — Review 2026-07-02, LOW-raw-yf-info.
        from api.transactions import get_ticker_info_cached

        info = await get_ticker_info_cached(ticker_norm)
        name = info.get("shortName") or info.get("longName") or ticker_norm
        if info.get("currency"):
            pos_currency = info["currency"]
    except Exception as e:
        logger.warning(f"yfinance lookup failed for {ticker_norm}: {e}")

    from services.bucket_service import get_liquid_default_bucket
    from models.bucket import Bucket
    target_bucket_id = None
    if bucket_id_hint is not None:
        b_q = await db.execute(
            select(Bucket).where(
                Bucket.id == bucket_id_hint,
                Bucket.user_id == user.id,
                Bucket.deleted_at.is_(None),
            )
        )
        if b_q.scalar_one_or_none() is not None:
            target_bucket_id = bucket_id_hint
    if target_bucket_id is None:
        liquid = await get_liquid_default_bucket(db, user.id)
        target_bucket_id = liquid.id

    pos = Position(
        user_id=user.id,
        bucket_id=target_bucket_id,
        ticker=ticker_norm,
        name=name,
        type=AssetType.stock,
        currency=pos_currency,
        yfinance_ticker=ticker_norm,
        price_source=PriceSource.yahoo,
        is_etf=False,
        shares=0,
        cost_basis_chf=0,
    )
    db.add(pos)
    await db.flush()
    return pos, True


async def _do_fill(
    db: AsyncSession,
    user: User,
    order: PendingOrder,
    data: PendingOrderFill,
) -> tuple[PendingOrder, Transaction, bool]:
    """Kerngeschaeft des Fill — wird von Internal- und External-Endpoint geteilt.

    Erwartet, dass der Caller das ``commit`` selbst macht (damit ApiWriteLog
    in der gleichen Transaktion gewrappt werden kann). Raises HTTPException
    fuer 4xx-Faelle, sonst gibt es keinen Rollback hier.
    """
    if order.status != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Pending Order ist nicht offen (status={order.status})",
        )

    today = datetime.date.today()
    if (
        order.expiry_type == "gtd"
        and order.expiry_date is not None
        and order.expiry_date < today
    ):
        raise HTTPException(
            status_code=409,
            detail="Pending Order ist effektiv abgelaufen (GTD)",
        )

    tx_count = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.user_id == user.id)
    )
    if (tx_count or 0) >= MAX_TRANSACTIONS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximale Anzahl Transaktionen erreicht ({MAX_TRANSACTIONS_PER_USER})",
        )

    pos, created_position = await _resolve_or_create_position(
        db, user, order.ticker, (data.currency or order.currency),
        bucket_id_hint=order.bucket_id_target,
    )

    txn_type = TransactionType.buy if order.side == "buy" else TransactionType.sell
    shares_f = float(order.shares)
    price_f = float(data.price_per_share)
    fees_f = float(data.fees_chf)
    taxes_f = float(data.taxes_chf)
    fx_f = float(data.fx_rate_to_chf)
    currency = (data.currency or order.currency).upper()

    # total_chf: Brutto inkl. Gebuehren in CHF (Konvention im Rest der App)
    total_chf = round(shares_f * price_f * fx_f + fees_f + taxes_f, 2)

    txn = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        position_id=pos.id,
        type=txn_type,
        date=data.fill_date,
        shares=shares_f,
        price_per_share=price_f,
        currency=currency,
        fx_rate_to_chf=fx_f,
        fees_chf=fees_f,
        taxes_chf=taxes_f,
        total_chf=total_chf,
        notes=encrypt_field(data.notes) if data.notes else None,
        bucket_id_at_sale=pos.bucket_id if txn_type == TransactionType.sell else None,
    )
    db.add(txn)

    apply_transaction_to_position(
        pos,
        txn_type=txn_type,
        shares=shares_f,
        total_chf=total_chf,
    )

    await db.flush()  # txn.id needs to exist before linking
    order.status = "filled"
    order.linked_transaction_id = txn.id

    # Recalc der Position: materialisiert realized_pnl_chf/cost_basis_at_sale auf
    # der erzeugten Sell-Txn, sonst erscheint die geschlossene Position erst nach
    # einem manuellen "neu berechnen" in der realized-gains-View. Autoritativ;
    # committet nicht selbst — geht in denselben Commit wie der Fill.
    from services.recalculate_service import recalculate_position
    await recalculate_position(db, pos.id)

    return order, txn, created_position


@router.post("/pending/{order_id}/fill")
@limiter.limit("30/minute")
async def fill_pending_order(
    request: Request,
    order_id: uuid.UUID,
    data: PendingOrderFill,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Row-Lock gegen Double-Fill-Race (TOCTOU, Review 2026-07-02, M3): ein
    # paralleler zweiter Fill wartet auf den Lock, sieht danach "filled" und
    # bekommt 409. Auf SQLite (Tests) ist with_for_update ein No-op.
    order_q = await db.execute(
        select(PendingOrder)
        .where(PendingOrder.id == order_id, PendingOrder.user_id == user.id)
        .with_for_update()
    )
    order = order_q.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pending Order nicht gefunden")

    order, txn, _ = await _do_fill(db, user, order, data)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    await db.refresh(order)
    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user.id, txn.date)

    return {
        "order": _serialize_minimal(order),
        "transaction_id": str(txn.id),
    }
