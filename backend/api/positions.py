import asyncio
import logging
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from dateutils import utcnow
from db import get_db
from models.position import Position, AssetType, PricingMode, PriceSource, Style
from models.user import User
from models.transaction import Transaction
from api.schemas import PositionResponse
from services.snapshot_trigger import trigger_snapshot_regen
from services.dividend_service import fetch_dividends
from services.price_service import get_stock_price
from services.recalculate_service import recalculate_position, recalculate_all_positions, debug_position
from services.sector_mapping import INDUSTRY_TO_SECTOR
from api.auth import limiter
from api.portfolio import invalidate_portfolio_cache
from models.api_write_log import ApiWriteLog
from services.encryption_helpers import encrypt_field, decrypt_field, decrypt_and_mask_iban
from constants.limits import MAX_POSITIONS_PER_USER

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["positions"])


# Cash/Pension sind manuell gepflegte Salden — sie tragen NIE ein handelbares
# Wertpapier. Ein Geldmarkt-/T-Bill-ETF, der "als Cash" gefuehrt werden soll,
# gehoert als type="etf" + count_as_cash=true angelegt: so wird er korrekt ueber
# shares*price*fx bewertet UND in der Cash-Quote gezaehlt. Ein handelbarer Ticker
# auf type="cash" faellt sonst durch _NON_YAHOO_TYPES (wird nie bepreist) und der
# cash-Bewertungszweig rechnet cost_basis_chf * fx — die genau dann falsch ist,
# wenn cost_basis_chf einen echten CHF-Einstand statt eines Fremdwaehrungs-Saldos
# haelt (der IB01.L "-19% an einem Tag"-Phantom-Bug).
_MARKET_SYMBOL_RE = re.compile(r"[A-Z][A-Z0-9.\-]{1,11}")


def _looks_like_market_symbol(ticker: str | None) -> bool:
    """Heuristik: sieht der Ticker wie ein Boersen-Symbol aus (z.B. IB01.L, AAPL)?

    Echte Cash-/Pension-Salden tragen Platzhalter (``CASH_*``/``PENSION_*`` bzw.
    unterstrich-haltige Labels) oder gar keinen Ticker; das UI-Cash-Formular hat
    kein Ticker-Feld. Reine Waehrungscodes (USD/CHF/EUR) als Cash-Label werden
    bewusst nicht als handelbar gewertet.
    """
    if not ticker:
        return False
    t = ticker.strip().upper()
    # Cash-/Pension-Platzhalter: UI generiert CASH_<name>, Tests/Seed nutzen auch
    # CASH-CHF/CASH-USD und VIAC_*; jeder unterstrich-haltige oder CASH/PENSION/
    # VIAC-praefixierte Ticker ist ein Konto-Label, kein Boersen-Symbol.
    if "_" in t or t.startswith(("CASH", "PENSION", "VIAC", "VORSORGE")):
        return False
    if len(t) == 3 and t.isalpha():  # Waehrungscode als Cash-Label, kein Symbol
        return False
    return bool(_MARKET_SYMBOL_RE.fullmatch(t))


def _guard_cash_not_tradable(
    eff_type_val: str,
    *,
    ticker: str | None,
    yfinance_ticker: str | None,
    coingecko_id: str | None,
    gold_org: bool | None,
) -> None:
    """Wirft 422, wenn ein handelbares Wertpapier als type='cash'/'pension'
    angelegt/gespeichert werden soll. Signale: coingecko_id/gold_org (echtes Cash
    traegt das NIE) sowie eine Symbol-Heuristik auf ticker UND yfinance_ticker.
    Der yfinance_ticker wird nur als handelbar gewertet, wenn er wie ein Symbol
    aussieht — Import/Txn-Auto-Anlage koennen dort einen CASH-*-Platzhalter setzen."""
    if eff_type_val not in ("cash", "pension"):
        return
    if (
        coingecko_id
        or gold_org
        or _looks_like_market_symbol(ticker)
        or _looks_like_market_symbol(yfinance_ticker)
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Geldmarkt-/T-Bill-ETFs bitte als Typ 'ETF' mit der Option "
                "'Als Cash zählen' führen, nicht als Cash-Konto — sonst wird die "
                "Position nicht live bepreist und im CHF-Wert falsch umgerechnet. "
                "Cash-Konten tragen keinen handelbaren Ticker."
            ),
        )


class PositionCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    type: AssetType
    sector: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    currency: str = Field(default="CHF", min_length=3, max_length=3)
    pricing_mode: PricingMode = PricingMode.auto
    style: Optional[Style] = None
    bucket_id: Optional[uuid.UUID] = None
    yfinance_ticker: Optional[str] = Field(default=None, max_length=60)
    coingecko_id: Optional[str] = Field(default=None, max_length=100)
    gold_org: bool = False
    price_source: PriceSource = PriceSource.yahoo
    isin: Optional[str] = Field(default=None, max_length=20)
    shares: float = Field(default=0, ge=0)
    cost_basis_chf: float = Field(default=0, ge=0)
    current_price: Optional[float] = Field(default=None, ge=0)
    count_as_cash: bool = False
    notes: Optional[str] = Field(default=None, max_length=2000)
    bank_name: Optional[str] = Field(default=None, max_length=200)
    iban: Optional[str] = Field(default=None, max_length=34)


class PositionUpdate(BaseModel):
    ticker: Optional[str] = Field(default=None, min_length=1, max_length=60)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    type: Optional[AssetType] = None
    sector: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    pricing_mode: Optional[PricingMode] = None
    style: Optional[Style] = None
    yfinance_ticker: Optional[str] = Field(default=None, max_length=60)
    coingecko_id: Optional[str] = Field(default=None, max_length=100)
    gold_org: Optional[bool] = None
    price_source: Optional[PriceSource] = None
    isin: Optional[str] = Field(default=None, max_length=20)
    shares: Optional[float] = Field(default=None, ge=0)
    cost_basis_chf: Optional[float] = Field(default=None, ge=0)
    current_price: Optional[float] = Field(default=None, ge=0)
    count_as_cash: Optional[bool] = None
    manual_resistance: Optional[float] = Field(default=None, ge=0)
    stop_loss_price: Optional[float] = Field(default=None, ge=0)
    stop_loss_confirmed_at_broker: Optional[bool] = None
    stop_loss_method: Optional[str] = Field(default=None, max_length=50)
    is_active: Optional[bool] = None
    bank_name: Optional[str] = Field(default=None, max_length=200)
    iban: Optional[str] = Field(default=None, max_length=34)
    notes: Optional[str] = Field(default=None, max_length=2000)


def _pos_to_dict(pos: Position) -> dict:
    return {
        "id": str(pos.id),
        "ticker": pos.ticker,
        "name": pos.name,
        "type": pos.type.value,
        "sector": pos.sector,
        "industry": pos.industry,
        "currency": pos.currency,
        "pricing_mode": pos.pricing_mode.value,
        "style": pos.style.value if pos.style else None,
        "bucket_id": str(pos.bucket_id) if pos.bucket_id else None,
        "risk_rules": pos.risk_rules,
        "yfinance_ticker": pos.yfinance_ticker,
        "coingecko_id": pos.coingecko_id,
        "gold_org": pos.gold_org,
        "price_source": pos.price_source.value,
        "isin": pos.isin,
        "shares": float(pos.shares),
        "cost_basis_chf": float(pos.cost_basis_chf),
        "current_price": float(pos.current_price) if pos.current_price else None,
        "manual_resistance": float(pos.manual_resistance) if pos.manual_resistance is not None else None,
        "stop_loss_price": float(pos.stop_loss_price) if pos.stop_loss_price is not None else None,
        "stop_loss_confirmed_at_broker": pos.stop_loss_confirmed_at_broker,
        "stop_loss_updated_at": pos.stop_loss_updated_at.isoformat() if pos.stop_loss_updated_at else None,
        "stop_loss_method": pos.stop_loss_method,
        "next_earnings_date": pos.next_earnings_date.isoformat() if pos.next_earnings_date else None,
        "is_etf": pos.is_etf,
        "count_as_cash": pos.count_as_cash,
        "is_active": pos.is_active,
        "notes": decrypt_field(pos.notes),
        "bank_name": decrypt_field(pos.bank_name),
        "iban": decrypt_and_mask_iban(pos.iban),
        "created_at": pos.created_at.isoformat() if pos.created_at else None,
        "updated_at": pos.updated_at.isoformat() if pos.updated_at else None,
    }


@router.get("/positions", response_model=list[PositionResponse])
async def list_positions(include_closed: bool = False, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(Position).where(Position.is_active == True, Position.user_id == user.id)
    if not include_closed:
        query = query.where(Position.shares > 0)
    result = await db.execute(query.order_by(func.lower(Position.name)))
    positions = result.scalars().all()
    return [_pos_to_dict(p) for p in positions]


# Phase 3 (v0.40): /positions-without-type entfernt. Alle Positionen sind
# einem Bucket zugeordnet (positions.bucket_id NOT NULL seit Migration 064).


@router.get("/positions/{position_id}", response_model=PositionResponse)
async def get_position(position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    return _pos_to_dict(pos)



async def create_position_core(
    db: AsyncSession,
    user: User,
    data: PositionCreate,
    *,
    audit_log: ApiWriteLog | None = None,
) -> dict:
    """Kernlogik fuer das Anlegen einer Position — geteilt zwischen internem UI-
    Endpoint und externer API. Bei gesetztem ``audit_log`` wird dieser atomar mit
    der Position committet (Ticker/target_id werden nach dem Flush gesetzt)."""
    # Per-user limit
    count = await db.scalar(select(func.count(Position.id)).where(Position.user_id == user.id))
    if count >= MAX_POSITIONS_PER_USER:
        raise HTTPException(400, f"Maximale Anzahl Positionen erreicht ({MAX_POSITIONS_PER_USER})")
    dump = data.model_dump()
    # Encrypt PII fields before saving
    if dump.get("iban"):
        dump["iban"] = encrypt_field(dump["iban"])
    if dump.get("notes"):
        dump["notes"] = encrypt_field(dump["notes"])
    if dump.get("bank_name"):
        dump["bank_name"] = encrypt_field(dump["bank_name"])
    # Auto-derive sector from industry
    if dump.get("industry"):
        if dump["industry"] not in INDUSTRY_TO_SECTOR:
            raise HTTPException(422, f"Ungültige Branche: {dump['industry']}")
        dump["sector"] = INDUSTRY_TO_SECTOR[dump["industry"]]
    elif "industry" in dump:
        dump["sector"] = None
    # Bucket-Zuordnung: PE/RE/Pension immer auf System-Bucket;
    # liquide Typen auf user-spezifizierten bucket_id oder liquid_default.
    from models.bucket import Bucket, BucketSystemRole, BucketKind
    asset_type = dump.get("type")
    type_value = asset_type.value if hasattr(asset_type, "value") else asset_type
    # count_as_cash ist nur fuer ETFs sinnvoll (Geldmarkt-/T-Bill-ETF). Fuer alle
    # anderen Typen hart auf False klemmen — verhindert sinnlose Cash-Reklassifikation
    # eines Stocks/Krypto via API.
    if type_value != "etf":
        dump["count_as_cash"] = False
    # Guard: ein handelbares Wertpapier darf nicht als cash/pension laufen.
    _guard_cash_not_tradable(
        type_value,
        ticker=dump.get("ticker"),
        yfinance_ticker=dump.get("yfinance_ticker"),
        coingecko_id=dump.get("coingecko_id"),
        gold_org=dump.get("gold_org"),
    )
    # Echtes Cash/Pension ist immer manuell bepreist (Saldo lebt in cost_basis_chf).
    # Den PositionCreate-Default pricing_mode=auto hier auf manual ziehen — schliesst
    # die Falle, dass ein per API ohne pricing_mode angelegtes Cash-Konto auf auto
    # landet (und damit beim Recalc null-gesetzt werden koennte).
    if type_value in ("cash", "pension"):
        dump["pricing_mode"] = PricingMode.manual
    role_map = {
        "real_estate": BucketSystemRole.real_estate,
        "private_equity": BucketSystemRole.private_equity,
        "pension": BucketSystemRole.pension,
    }
    if type_value in role_map:
        sys_q = await db.execute(
            select(Bucket).where(
                Bucket.user_id == user.id,
                Bucket.system_role == role_map[type_value],
                Bucket.deleted_at.is_(None),
            )
        )
        sys_bucket = sys_q.scalar_one_or_none()
        if sys_bucket is None:
            from services.bucket_service import create_system_buckets
            await create_system_buckets(db, user.id)
            await db.flush()
            sys_q = await db.execute(
                select(Bucket).where(
                    Bucket.user_id == user.id,
                    Bucket.system_role == role_map[type_value],
                    Bucket.deleted_at.is_(None),
                )
            )
            sys_bucket = sys_q.scalar_one()
        dump["bucket_id"] = sys_bucket.id
    else:
        # Liquide Typen — User wahlfrei oder Default
        if dump.get("bucket_id") is not None:
            # Validierung: muss aktiver Bucket des Users sein
            b_q = await db.execute(
                select(Bucket).where(
                    Bucket.id == dump["bucket_id"],
                    Bucket.user_id == user.id,
                    Bucket.deleted_at.is_(None),
                )
            )
            target = b_q.scalar_one_or_none()
            if target is None:
                raise HTTPException(400, "Ungültiger Bucket")
        else:
            from services.bucket_service import get_liquid_default_bucket
            liquid = await get_liquid_default_bucket(db, user.id)
            dump["bucket_id"] = liquid.id
    pos = Position(**dump, user_id=user.id)
    db.add(pos)
    try:
        await db.flush()
    except Exception as e:
        await db.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(409, "Eine Position mit diesem Namen existiert bereits.")
        raise HTTPException(500, "Position konnte nicht erstellt werden.")
    if audit_log is not None:
        audit_log.ticker = (pos.ticker or "")[:30]
        audit_log.target_id = pos.id
        db.add(audit_log)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(409, "Eine Position mit diesem Namen existiert bereits.")
        raise HTTPException(500, "Position konnte nicht erstellt werden.")
    await db.refresh(pos)
    # Sofort-Fetch: ausserhalb der Worker-Handelszeiten (is_extended_hours) angelegte
    # Positionen bleiben sonst bis zum naechsten Refresh-Fenster kurslos. Fire-and-forget
    # mit eigener Session — blockiert die Response nicht.
    from services.cache_service import trigger_position_price_seed
    trigger_position_price_seed(pos.id)
    invalidate_portfolio_cache(str(user.id))
    # Regenerate historical snapshots if position has cost basis (= historical data)
    if float(pos.cost_basis_chf or 0) > 0:
        trigger_snapshot_regen(user.id, pos.created_at.date() if pos.created_at else None)
    return _pos_to_dict(pos)


@router.post("/positions", status_code=201)
@limiter.limit("30/minute")
async def create_position(request: Request, data: PositionCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await create_position_core(db, user, data)


async def update_position_core(
    db: AsyncSession,
    user: User,
    position_id: uuid.UUID,
    data: PositionUpdate,
    *,
    audit_log: ApiWriteLog | None = None,
) -> dict:
    """Kernlogik fuer das Aendern einer Position — geteilt mit der externen API."""
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    updates = data.model_dump(exclude_unset=True)
    # Encrypt PII fields before saving
    if "iban" in updates:
        updates["iban"] = encrypt_field(updates["iban"]) if updates["iban"] else None
    if "notes" in updates:
        updates["notes"] = encrypt_field(updates["notes"]) if updates["notes"] else None
    if "bank_name" in updates:
        updates["bank_name"] = encrypt_field(updates["bank_name"]) if updates["bank_name"] else None
    # Auto-derive sector from industry
    if "industry" in updates:
        if updates["industry"]:
            if updates["industry"] not in INDUSTRY_TO_SECTOR:
                raise HTTPException(422, f"Ungültige Branche: {updates['industry']}")
            updates["sector"] = INDUSTRY_TO_SECTOR[updates["industry"]]
        else:
            # Industry cleared → clear sector too
            updates["sector"] = None
    # count_as_cash nur fuer ETFs — bei nicht-ETF (auch bei Typwechsel weg von
    # ETF) hart auf False klemmen, damit keine stale-true-Reklassifikation bleibt.
    if "count_as_cash" in updates or "type" in updates:
        eff_type = updates.get("type", pos.type)
        eff_type_val = eff_type.value if hasattr(eff_type, "value") else eff_type
        if eff_type_val != "etf":
            updates["count_as_cash"] = False
    # Guard: kein handelbares Wertpapier als cash/pension. Nur pruefen, wenn der
    # Edit ein relevantes Feld TATSAECHLICH AENDERT (Typwechsel oder ein neues
    # Handels-Signal). Das UI sendet bei jedem Save das ganze Formular inkl.
    # unveraendertem ticker — ein reiner Praesenz-Check wuerde sonst jeden Edit
    # (Saldo, notes) an einer Cash-Pos blocken und Alt-Daten un-editierbar machen.
    _tradable_fields = ("ticker", "yfinance_ticker", "coingecko_id", "gold_org")
    _type_changed = "type" in updates and updates["type"] != pos.type
    _tradable_changed = any(
        f in updates and updates[f] != getattr(pos, f) for f in _tradable_fields
    )
    if _type_changed or _tradable_changed:
        _eff_type = updates.get("type", pos.type)
        _eff_type_val = _eff_type.value if hasattr(_eff_type, "value") else _eff_type
        _guard_cash_not_tradable(
            _eff_type_val,
            ticker=updates.get("ticker", pos.ticker),
            yfinance_ticker=updates.get("yfinance_ticker", pos.yfinance_ticker),
            coingecko_id=updates.get("coingecko_id", pos.coingecko_id),
            gold_org=updates.get("gold_org", pos.gold_org),
        )
    for key, val in updates.items():
        setattr(pos, key, val)
    # Stop-Loss-Aenderungen muessen die Review-Uhr zuruecksetzen — sonst
    # bleibt der stop_loss_age-Alert trotz aktualisiertem Stop stehen.
    # Der dedizierte PATCH-Pfad (stoploss_service) macht das immer.
    if any(k in updates for k in ("stop_loss_price", "stop_loss_method", "stop_loss_confirmed_at_broker")):
        pos.stop_loss_updated_at = utcnow()
    if audit_log is not None:
        audit_log.ticker = (pos.ticker or "")[:30]
        audit_log.target_id = pos.id
        db.add(audit_log)
    await db.commit()
    await db.refresh(pos)
    invalidate_portfolio_cache(str(user.id))
    return _pos_to_dict(pos)


@router.put("/positions/{position_id}")
@limiter.limit("30/minute")
async def update_position(request: Request, position_id: uuid.UUID, data: PositionUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await update_position_core(db, user, position_id, data)


async def delete_position_core(
    db: AsyncSession,
    user: User,
    position_id: uuid.UUID,
    *,
    audit_log: ApiWriteLog | None = None,
) -> None:
    """Kernlogik fuer das Loeschen einer Position — geteilt mit der externen API."""
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    user_id = pos.user_id
    created = pos.created_at.date() if pos.created_at else None
    if audit_log is not None:
        audit_log.ticker = (pos.ticker or "")[:30]
        audit_log.target_id = pos.id
        db.add(audit_log)
    await db.delete(pos)
    await db.commit()
    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user_id, created)


@router.delete("/positions/{position_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_position(request: Request, position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await delete_position_core(db, user, position_id)


@router.get("/positions/{position_id}/dividends")
async def position_dividends(position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    # Find earliest buy date
    result = await db.execute(
        select(Transaction.date)
        .where(Transaction.position_id == position_id, Transaction.type == "buy")
        .order_by(Transaction.date.asc())
        .limit(1)
    )
    first_buy = result.scalar()
    if not first_buy:
        return []
    yf_ticker = pos.yfinance_ticker or pos.ticker
    return await asyncio.to_thread(fetch_dividends, yf_ticker, first_buy, float(pos.shares), pos.currency)


@router.get("/positions/{position_id}/test-price")
@limiter.limit("10/minute")
async def test_price(request: Request, position_id: uuid.UUID, yfinance_ticker: str = Query(...), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    result = await asyncio.to_thread(get_stock_price, yfinance_ticker)
    if not result:
        return {"ok": False, "error": f"Kein Kurs für '{yfinance_ticker}' gefunden"}
    return {"ok": True, "price": result["price"], "currency": result["currency"]}


@router.get("/positions/{position_id}/history")
async def position_history(position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    result = await db.execute(
        select(Transaction)
        .where(Transaction.position_id == position_id)
        .order_by(Transaction.date.desc())
    )
    txns = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "type": t.type.value,
            "date": t.date.isoformat(),
            "shares": float(t.shares),
            "price_per_share": float(t.price_per_share),
            "currency": t.currency,
            "fx_rate_to_chf": float(t.fx_rate_to_chf),
            "fees_chf": float(t.fees_chf),
            "taxes_chf": float(t.taxes_chf),
            "total_chf": float(t.total_chf),
            "notes": t.notes,
        }
        for t in txns
    ]


@router.get("/positions/{position_id}/debug")
@limiter.limit("10/minute")
async def debug_single(request: Request, position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    return await debug_position(db, position_id)


@router.post("/positions/recalculate")
@limiter.limit("5/minute")
async def recalculate_all(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    results = await recalculate_all_positions(db, user_id=user.id)
    return {"results": results}


@router.post("/positions/{position_id}/recalculate")
@limiter.limit("5/minute")
async def recalculate_single(request: Request, position_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    result = await recalculate_position(db, position_id)
    await db.commit()
    invalidate_portfolio_cache(str(user.id))
    return result


# Phase 3 (v0.40): /position-type/batch und /positions-without-type entfernt.
# Ersatz: POST /portfolio/positions/{id}/move-to-bucket (Bucket-Wechsel).
