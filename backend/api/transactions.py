import asyncio
import datetime
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from auth import get_current_user
from db import get_db
from models.api_write_log import ApiWriteLog
from models.position import Position
from models.transaction import Transaction, TransactionType
from services.snapshot_trigger import trigger_snapshot_regen
from models.user import User
from services.auth_service import escape_like
from services.encryption_helpers import encrypt_field, decrypt_field
from services.transaction_service import apply_transaction_to_position, reverse_transaction_on_position
from api.portfolio import invalidate_portfolio_cache
from api.schemas import TransactionListResponse
from constants.limits import MAX_POSITIONS_PER_USER, MAX_TRANSACTIONS_PER_USER

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class TransactionCreate(BaseModel):
    position_id: Optional[uuid.UUID] = None
    ticker: Optional[str] = Field(default=None, max_length=60)
    asset_type: Optional[str] = Field(default=None, max_length=30)
    bucket_id: Optional[uuid.UUID] = None
    type: TransactionType
    date: datetime.date
    shares: float = Field(default=0, ge=0)
    price_per_share: float = Field(default=0, ge=0)
    currency: str = Field(default="CHF", min_length=3, max_length=3)
    fx_rate_to_chf: float = Field(default=1.0, gt=0)
    fees_chf: float = Field(default=0, ge=0)
    taxes_chf: float = Field(default=0, ge=0)
    total_chf: float = Field(default=0, ge=0)
    notes: Optional[str] = Field(default=None, max_length=2000)
    stop_loss_price: Optional[float] = Field(default=None, ge=0)
    stop_loss_method: Optional[str] = Field(default=None, max_length=50)
    stop_loss_confirmed_at_broker: Optional[bool] = None


class TransactionUpdate(BaseModel):
    date: Optional[datetime.date] = None
    shares: Optional[float] = Field(default=None, ge=0)
    price_per_share: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    fx_rate_to_chf: Optional[float] = Field(default=None, gt=0)
    fees_chf: Optional[float] = Field(default=None, ge=0)
    taxes_chf: Optional[float] = Field(default=None, ge=0)
    total_chf: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = Field(default=None, max_length=2000)


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    type: Optional[TransactionType] = None,
    ticker: Optional[str] = None,
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
    search: Optional[str] = None,
):
    query = (
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
    )
    count_query = (
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.user_id == user.id)
    )

    if type:
        query = query.where(Transaction.type == type)
        count_query = count_query.where(Transaction.type == type)

    if ticker:
        pos_result = await db.execute(
            select(Position.id).where(
                Position.ticker.ilike(f"%{escape_like(ticker)}%"),
                Position.user_id == user.id,
            )
        )
        pos_ids = [row[0] for row in pos_result]
        if pos_ids:
            query = query.where(Transaction.position_id.in_(pos_ids))
            count_query = count_query.where(Transaction.position_id.in_(pos_ids))
        else:
            return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

    # Search across ticker and position name (notes are encrypted, not searchable at DB level)
    if search:
        from sqlalchemy import or_
        search_term = f"%{escape_like(search)}%"
        pos_result = await db.execute(
            select(Position.id).where(
                Position.user_id == user.id,
                or_(
                    Position.ticker.ilike(search_term),
                    Position.name.ilike(search_term),
                ),
            )
        )
        matching_pos_ids = [row[0] for row in pos_result]
        if matching_pos_ids:
            search_filter = Transaction.position_id.in_(matching_pos_ids)
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)
        else:
            return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

    if date_from:
        query = query.where(Transaction.date >= date_from)
        count_query = count_query.where(Transaction.date >= date_from)
    if date_to:
        query = query.where(Transaction.date <= date_to)
        count_query = count_query.where(Transaction.date <= date_to)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    txns = result.scalars().all()

    pos_ids_needed = {t.position_id for t in txns}
    positions_map = {}
    if pos_ids_needed:
        pos_result = await db.execute(
            select(Position).where(Position.id.in_(pos_ids_needed))
        )
        for p in pos_result.scalars():
            positions_map[p.id] = {"ticker": p.ticker, "name": p.name}

    items = []
    for t in txns:
        d = _txn_to_dict(t)
        pos_info = positions_map.get(t.position_id, {})
        d["ticker"] = pos_info.get("ticker", "–")
        d["position_name"] = pos_info.get("name", "–")
        items.append(d)

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total else 0,
    }



async def create_transaction_core(
    db: AsyncSession, user: User, data: TransactionCreate,
    *, audit_log: ApiWriteLog | None = None,
) -> dict:
    """Kernlogik der Transaktions-Anlage.

    Wird vom internen Endpoint und von der External-API (``/api/v1/external``)
    geteilt — analog zu ``api.orders._do_fill``. Committed selbst und triggert
    die Post-Commit-Hooks (Cache-Invalidierung, Snapshot-Regen, Dividend-Match,
    Industry-Assign). Braucht kein ``request``-Objekt.

    ``audit_log``: optionaler ``ApiWriteLog``-Eintrag (External-API). Wird
    **atomar** mit der Transaktion committet — Core flusht vorher, setzt
    ``target_id`` und ``ticker`` aus der erzeugten Buchung und gibt den Eintrag
    in denselben Commit. Schlaegt der Log-Insert fehl (z.B. ``action``-CHECK-
    Constraint), rollt der gemeinsame Commit die Buchung mit zurueck — kein
    Orphan, ein Caller-Retry bleibt duplikatfrei.
    """
    # Validate: either position_id or ticker must be provided
    if not data.position_id and not data.ticker:
        raise HTTPException(status_code=422, detail="Entweder Position oder Ticker muss angegeben werden")

    # Per-user limit
    tx_count = await db.scalar(select(func.count()).select_from(Transaction).where(Transaction.user_id == user.id))
    if tx_count >= MAX_TRANSACTIONS_PER_USER:
        raise HTTPException(400, f"Maximale Anzahl Transaktionen erreicht ({MAX_TRANSACTIONS_PER_USER})")

    pos = None
    created_position = False

    if data.position_id:
        # Existing flow: look up by position_id
        pos = await db.get(Position, data.position_id)
        if not pos or pos.user_id != user.id:
            raise HTTPException(status_code=404, detail="Position nicht gefunden")
    else:
        # New flow: look up or auto-create by ticker
        ticker = data.ticker.strip().upper()
        result = await db.execute(
            select(Position).where(
                Position.user_id == user.id,
                Position.ticker == ticker,
            )
        )
        pos = result.scalar_one_or_none()

        if not pos:
            # Auto-create position (same logic as CSV import confirm_import)
            pos_count = await db.scalar(
                select(func.count()).select_from(Position).where(Position.user_id == user.id)
            )
            if pos_count >= MAX_POSITIONS_PER_USER:
                raise HTTPException(400, f"Maximale Anzahl Positionen erreicht ({MAX_POSITIONS_PER_USER})")

            from models.position import AssetType, PriceSource

            # Determine asset type
            asset_type_str = data.asset_type or "stock"
            try:
                asset_type = AssetType(asset_type_str)
            except ValueError:
                asset_type = AssetType.stock

            # Determine price source and coingecko_id
            price_source = PriceSource.yahoo
            coingecko_id = None
            is_etf = False
            if asset_type == AssetType.crypto:
                price_source = PriceSource.coingecko
                crypto_map = {
                    "BTC-USD": "bitcoin", "ETH-USD": "ethereum", "SOL-USD": "solana",
                    "ADA-USD": "cardano", "DOT-USD": "polkadot", "AVAX-USD": "avalanche-2",
                    "MATIC-USD": "matic-network", "LINK-USD": "chainlink",
                    "UNI-USD": "uniswap", "DOGE-USD": "dogecoin", "XRP-USD": "ripple",
                    "LTC-USD": "litecoin",
                }
                coingecko_id = crypto_map.get(ticker)
            elif asset_type == AssetType.etf:
                is_etf = True

            # Fetch name from yfinance (best-effort)
            name = ticker
            currency = data.currency
            try:
                import yfinance as yf
                info = await asyncio.to_thread(lambda: yf.Ticker(ticker).info or {})
                name = info.get("shortName") or info.get("longName") or ticker
                if info.get("currency"):
                    currency = info["currency"]
            except Exception as e:
                logger.warning(f"yfinance lookup failed for {ticker}: {e}")

            from services.bucket_service import get_liquid_default_bucket
            from models.bucket import Bucket
            target_bucket_id = None
            if data.bucket_id is not None:
                b_q = await db.execute(
                    select(Bucket).where(
                        Bucket.id == data.bucket_id,
                        Bucket.user_id == user.id,
                        Bucket.deleted_at.is_(None),
                    )
                )
                if b_q.scalar_one_or_none() is None:
                    raise HTTPException(status_code=400, detail="Ungültiger Bucket")
                target_bucket_id = data.bucket_id
            else:
                liquid = await get_liquid_default_bucket(db, user.id)
                target_bucket_id = liquid.id

            pos = Position(
                user_id=user.id,
                bucket_id=target_bucket_id,
                ticker=ticker,
                name=name,
                type=asset_type,
                currency=currency,
                yfinance_ticker=ticker,
                coingecko_id=coingecko_id,
                price_source=price_source,
                is_etf=is_etf,
                shares=0,
                cost_basis_chf=0,
            )
            db.add(pos)
            await db.flush()
            created_position = True

    # Stop-loss validation for buy transactions.
    # Phase 3 (v0.40): Stop-Loss-Pflicht kommt aus bucket.risk_rules — wird vom
    # alert_service als Alert geprueft und nicht beim Kauf hart erzwungen.
    # Hier nur Plausibilitaetspruefung des angegebenen Werts.
    if data.type == TransactionType.buy and data.stop_loss_price is not None:
        if data.stop_loss_price <= 0:
            raise HTTPException(status_code=422, detail="Stop-Loss muss grösser als 0 sein")
        if data.stop_loss_price >= data.price_per_share:
            raise HTTPException(status_code=422, detail="Stop-Loss muss unter dem Kaufkurs liegen")

    txn_data = data.model_dump(exclude={"stop_loss_price", "stop_loss_method", "stop_loss_confirmed_at_broker", "ticker", "asset_type", "bucket_id"})
    txn_data["position_id"] = pos.id
    txn_data["notes"] = encrypt_field(txn_data.get("notes"))
    txn = Transaction(**txn_data, user_id=user.id)
    if txn.type == TransactionType.sell:
        txn.bucket_id_at_sale = pos.bucket_id
    db.add(txn)

    # Auto-update position for buy/sell/delivery
    apply_transaction_to_position(
        pos,
        txn_type=data.type,
        shares=data.shares,
        total_chf=data.total_chf,
        stop_loss_price=data.stop_loss_price,
        stop_loss_method=data.stop_loss_method,
        stop_loss_confirmed_at_broker=data.stop_loss_confirmed_at_broker,
    )

    # External-API: Audit-Log atomar mit der Buchung. Flush populiert txn.id;
    # der Log-Insert teilt sich den folgenden Commit, ist also kein zweiter
    # Commit (der nach erfolgreicher Buchung gefaehrlich waere — siehe Docstring).
    if audit_log is not None:
        await db.flush()
        audit_log.target_id = txn.id
        if not audit_log.ticker:
            audit_log.ticker = (pos.ticker or "")[:30]
        db.add(audit_log)

    await db.commit()
    await db.refresh(txn)
    invalidate_portfolio_cache(str(user.id))

    # Auto-assign industry/sector for new positions (non-blocking, best-effort)
    if created_position:
        try:
            from services.import_service import _auto_assign_industries
            await _auto_assign_industries(db, [pos])
        except Exception as e:
            logger.warning(f"Auto-assign industries failed for {pos.ticker}: {e}")

    trigger_snapshot_regen(user.id, txn.date)

    # Dividenden-Tracker Hook 1: best-effort Auto-Match einer offenen
    # Pending-Dividende derselben Position innerhalb +/-35d.
    if data.type == TransactionType.dividend:
        try:
            from services.pending_dividend_service import try_auto_match_transaction
            await try_auto_match_transaction(db, txn, user.id)
        except Exception as e:
            logger.warning(f"Dividend auto-match failed for txn {txn.id}: {e}")

    d = _txn_to_dict(txn)
    d["ticker"] = pos.ticker
    d["position_name"] = pos.name
    d["created_position"] = created_position
    return d


@router.post("", status_code=201)
@limiter.limit("30/minute")
async def create_transaction(request: Request, data: TransactionCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await create_transaction_core(db, user, data)


@router.put("/{txn_id}")
@limiter.limit("30/minute")
async def update_transaction(request: Request, txn_id: uuid.UUID, data: TransactionUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    txn = await db.get(Transaction, txn_id)
    if not txn or txn.user_id != user.id:
        raise HTTPException(status_code=404, detail="Transaktion nicht gefunden")

    pos = await db.get(Position, txn.position_id)

    old_type = txn.type
    old_shares = float(txn.shares)
    old_total = float(txn.total_chf)

    for key, val in data.model_dump(exclude_unset=True).items():
        if key == "notes":
            val = encrypt_field(val)
        setattr(txn, key, val)
    if pos and old_type in (TransactionType.buy, TransactionType.sell):
        new_shares = float(txn.shares)
        new_total = float(txn.total_chf)
        if old_type == TransactionType.buy:
            pos.shares = float(pos.shares) - old_shares + new_shares
            pos.cost_basis_chf = float(pos.cost_basis_chf) - old_total + new_total
        elif old_type == TransactionType.sell:
            pos.shares = float(pos.shares) + old_shares - new_shares

    await db.commit()
    await db.refresh(txn)
    invalidate_portfolio_cache(str(user.id))

    trigger_snapshot_regen(user.id, txn.date)
    d = _txn_to_dict(txn)
    if pos:
        d["ticker"] = pos.ticker
        d["position_name"] = pos.name
    return d


@router.delete("/{txn_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_transaction(request: Request, txn_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    txn = await db.get(Transaction, txn_id)
    if not txn or txn.user_id != user.id:
        raise HTTPException(status_code=404, detail="Transaktion nicht gefunden")

    pos = await db.get(Position, txn.position_id)

    reverse_transaction_on_position(pos, txn.type, float(txn.shares), float(txn.total_chf))

    txn_date = txn.date
    txn_type = txn.type
    txn_id_for_unmatch = txn.id

    # Dividenden-Tracker Hook 3: vor dem Delete den Pending-Status zuruecksetzen
    # (DB-FK ON DELETE SET NULL setzt matched_transaction_id, wir setzen den
    # Status auf 'pending' zurueck, damit Eintrag wieder im Widget erscheint).
    if txn_type == TransactionType.dividend:
        try:
            from services.pending_dividend_service import unmatch_on_transaction_delete
            await unmatch_on_transaction_delete(db, txn_id_for_unmatch, user.id)
        except Exception as e:
            logger.warning(f"Dividend unmatch failed for txn {txn_id_for_unmatch}: {e}")

    await db.delete(txn)
    await db.commit()
    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user.id, txn_date)


def _txn_to_dict(txn: Transaction) -> dict:
    return {
        "id": str(txn.id),
        "position_id": str(txn.position_id),
        "type": txn.type.value,
        "date": txn.date.isoformat(),
        "shares": float(txn.shares),
        "price_per_share": float(txn.price_per_share),
        "currency": txn.currency,
        "fx_rate_to_chf": float(txn.fx_rate_to_chf),
        "fees_chf": float(txn.fees_chf),
        "taxes_chf": float(txn.taxes_chf),
        "total_chf": float(txn.total_chf),
        "notes": decrypt_field(txn.notes),
        "created_at": txn.created_at.isoformat() if txn.created_at else None,
    }
