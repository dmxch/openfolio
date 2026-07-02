"""Dividenden-Tracker API.

Endpunkte:
- ``GET  /api/dividends/pending`` — Liste mit ``?status``- und ``?limit``-Filter.
  Liefert ``expected_gross_chf_recomputed`` mit (R5: historische FX am
  Ex-Date neu berechnet, fallback ``expected_gross_chf``).
- ``POST /api/dividends/{id}/confirm`` — legt Transaktion an, matched Pending,
  invalidiert Cache + triggert Snapshot-Regen, persistiert Sticky-Withholding
  bei Abweichung vom Default.
- ``POST /api/dividends/{id}/dismiss`` — markiert dauerhaft als ignoriert.
- ``GET  /api/dividends/count`` — schneller Badge-Counter.

Alle Endpunkte sind ``user_id``-gescoped via ``Depends(get_current_user)``.
"""

import logging
import uuid
from datetime import date as date_type, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from api.portfolio import invalidate_portfolio_cache
from auth import get_current_user
from db import get_db
from models.api_write_log import ApiWriteLog
from models.pending_dividend import (
    PendingDividend,
    STATUS_CONFIRMED,
    STATUS_DISMISSED,
    STATUS_PENDING,
    ALLOWED_STATUSES,
)
from models.position import Position
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.encryption_helpers import encrypt_field
from services.pending_dividend_service import resolve_withholding
from services.snapshot_trigger import trigger_snapshot_regen
from services.utils import get_historical_fx_rate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dividends", tags=["dividends"])


# --- Schemas ---------------------------------------------------------------


class PendingDividendItem(BaseModel):
    id: uuid.UUID
    position_id: uuid.UUID
    ticker: str
    position_name: str
    ex_date: date_type
    dividend_per_share: float
    currency: str
    shares_at_ex_date: float
    expected_gross_chf: float
    # R5: am Ex-Date neu berechnete Brutto-CHF (historische FX). Falls Lookup
    # fehlschlaegt, gleich expected_gross_chf.
    expected_gross_chf_recomputed: float
    expected_net_chf: float
    withholding_pct: float
    status: str
    matched_transaction_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    created_at: datetime


class PendingDividendsResponse(BaseModel):
    items: list[PendingDividendItem]
    total: int
    withholding_default_pct: float  # 0.0..1.0


class ConfirmDividendRequest(BaseModel):
    date: date_type
    total_chf: float = Field(ge=0)
    gross_amount: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=10)
    fx_rate_to_chf: float = Field(default=1.0, gt=0)
    withholding_pct: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    notes: Optional[str] = Field(default=None, max_length=2000)


class DismissDividendRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class DividendCountResponse(BaseModel):
    pending_count: int


# --- Endpoints -------------------------------------------------------------


@router.get("/pending", response_model=PendingDividendsResponse)
async def list_pending_dividends(
    status: str = Query(STATUS_PENDING),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Liste der Pending-Dividenden des eingeloggten Users.

    Default ``status='pending'``; ``confirmed`` und ``dismissed`` sind fuer
    Admin-Debugging erlaubt. Recomputes ``expected_gross_chf`` mit historischer
    FX am Ex-Date (R5).
    """
    if status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="Ungültiger Status-Filter")

    # User-Settings (fuer withholding_default + Anzeige)
    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    user_settings = settings_result.scalars().first()
    withholding_default = (
        float(user_settings.dividend_withholding_default)
        if user_settings and user_settings.dividend_withholding_default is not None
        else 0.35
    )

    # Total fuer status==pending — separat fuer den Badge-Sync (nicht limitiert).
    total = await db.scalar(
        select(func.count())
        .select_from(PendingDividend)
        .where(
            PendingDividend.user_id == user.id,
            PendingDividend.status == status,
        )
    ) or 0

    rows_result = await db.execute(
        select(PendingDividend, Position)
        .join(Position, Position.id == PendingDividend.position_id)
        .where(
            PendingDividend.user_id == user.id,
            PendingDividend.status == status,
        )
        .order_by(PendingDividend.ex_date.desc())
        .limit(limit)
    )
    rows = rows_result.all()

    items: list[PendingDividendItem] = []
    # Pro Request nach (currency, ex_date) memoisieren — sonst löst jede
    # Zeile denselben FX-Lookup aus, inkl. wiederholter yf-Fehlversuche
    # (Review 2026-07-02, H9; Cross-Request-Cache liegt in utils).
    fx_memo: dict[tuple[str, object], float | None] = {}
    for pending, position in rows:
        # R5: FX am Ex-Date neu berechnen (best-effort)
        recomputed = float(pending.expected_gross_chf)
        try:
            memo_key = (pending.currency, pending.ex_date)
            if memo_key in fx_memo:
                historical_fx = fx_memo[memo_key]
            else:
                historical_fx = await get_historical_fx_rate(
                    pending.currency, pending.ex_date
                )
                fx_memo[memo_key] = historical_fx
            if historical_fx is not None and historical_fx > 0:
                recomputed = round(
                    float(pending.shares_at_ex_date)
                    * float(pending.dividend_per_share)
                    * historical_fx,
                    2,
                )
        except Exception as e:
            logger.debug(
                "fx_recompute_failed pending=%s currency=%s ex_date=%s error=%s",
                pending.id, pending.currency, pending.ex_date, e,
            )

        wht = resolve_withholding(position, user_settings) if user_settings else withholding_default
        net_chf = round(recomputed * (1.0 - wht), 2)

        items.append(PendingDividendItem(
            id=pending.id,
            position_id=position.id,
            ticker=position.ticker,
            position_name=position.name,
            ex_date=pending.ex_date,
            dividend_per_share=float(pending.dividend_per_share),
            currency=pending.currency,
            shares_at_ex_date=float(pending.shares_at_ex_date),
            expected_gross_chf=float(pending.expected_gross_chf),
            expected_gross_chf_recomputed=recomputed,
            expected_net_chf=net_chf,
            withholding_pct=wht,
            status=pending.status,
            matched_transaction_id=pending.matched_transaction_id,
            notes=pending.notes,
            created_at=pending.created_at,
        ))

    return PendingDividendsResponse(
        items=items,
        total=int(total),
        withholding_default_pct=withholding_default,
    )


@router.get("/count", response_model=DividendCountResponse)
async def count_pending_dividends(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Schneller COUNT(*) fuer den Sidebar-Badge."""
    count = await db.scalar(
        select(func.count())
        .select_from(PendingDividend)
        .where(
            PendingDividend.user_id == user.id,
            PendingDividend.status == STATUS_PENDING,
        )
    )
    return DividendCountResponse(pending_count=int(count or 0))


async def confirm_pending_dividend_core(
    db: AsyncSession,
    user: User,
    pending_id: uuid.UUID,
    data: ConfirmDividendRequest,
    *,
    audit_log: ApiWriteLog | None = None,
) -> dict:
    """Kernlogik fuer das Bestaetigen einer Pending-Dividende — geteilt zwischen
    internem UI-Endpoint und externer API. Legt eine ``dividend``-Transaktion an
    und markiert den Pending-Eintrag als ``confirmed``. Persistiert
    Sticky-Withholding bei Abweichung vom aufgeloesten Default-Wert (R1).

    Bei gesetztem ``audit_log`` wird dieser atomar mit der Transaktion
    committet (target_id = Transaktions-ID, ticker = Position-Ticker).
    """
    pending = await db.get(PendingDividend, pending_id)
    if not pending or pending.user_id != user.id:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    if pending.status != STATUS_PENDING:
        raise HTTPException(status_code=409, detail="Bereits erfasst oder ignoriert")

    position = await db.get(Position, pending.position_id)
    if not position or position.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")

    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    user_settings = settings_result.scalars().first()

    resolved_wht = resolve_withholding(position, user_settings) if user_settings else 0.35

    # Sticky-Withholding (R1): wenn User abweichenden Wert mitgegeben hat,
    # auf Position persistieren — naechstes Mal kommt er wieder.
    submitted_wht = data.withholding_pct
    if submitted_wht is not None and abs(submitted_wht - resolved_wht) > 1e-6:
        position.dividend_withholding_pct = Decimal(str(round(submitted_wht, 4)))

    # Currency: Default = Pending-Currency
    currency = (data.currency or pending.currency or "USD").upper()

    # Transaktion anlegen — shares=0, price_per_share=0 (Dividenden aendern
    # den Bestand nicht). gross_amount/tax_amount fuer spaetere Steuerwerte.
    gross_amount = data.gross_amount
    tax_amount = None
    if gross_amount is not None and data.total_chf is not None:
        tax_amount = round(float(gross_amount) - float(data.total_chf), 2)

    txn = Transaction(
        user_id=user.id,
        position_id=position.id,
        type=TransactionType.dividend,
        date=data.date,
        shares=0,
        price_per_share=0,
        currency=currency,
        fx_rate_to_chf=data.fx_rate_to_chf,
        fees_chf=0,
        taxes_chf=0,
        total_chf=data.total_chf,
        notes=encrypt_field(data.notes),
        gross_amount=gross_amount,
        tax_amount=tax_amount,
    )
    db.add(txn)
    await db.flush()

    pending.status = STATUS_CONFIRMED
    pending.matched_transaction_id = txn.id
    pending.updated_at = datetime.utcnow()

    # Audit-Log atomar mit der Transaktion committen (gleiche DB-Transaktion).
    if audit_log is not None:
        audit_log.target_id = txn.id
        audit_log.ticker = (position.ticker or "")[:30]
        db.add(audit_log)

    await db.commit()
    await db.refresh(txn)

    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user.id, txn.date)

    return {
        "transaction_id": str(txn.id),
        "pending_id": str(pending.id),
        "status": pending.status,
    }


@router.post("/{pending_id}/confirm", status_code=201)
@limiter.limit("30/minute")
async def confirm_pending_dividend(
    request: Request,
    pending_id: uuid.UUID,
    data: ConfirmDividendRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lege eine `dividend`-Transaktion an und markiere den Pending-Eintrag
    als ``confirmed``. Delegiert an ``confirm_pending_dividend_core``.
    """
    return await confirm_pending_dividend_core(db, user, pending_id, data)


async def dismiss_pending_dividend_core(
    db: AsyncSession,
    user: User,
    pending_id: uuid.UUID,
    data: DismissDividendRequest,
    *,
    audit_log: ApiWriteLog | None = None,
) -> dict:
    """Kernlogik fuer das Verwerfen einer Pending-Dividende — geteilt zwischen
    internem UI-Endpoint und externer API. Markiert den Eintrag dauerhaft als
    ignoriert. Reason optional, plain TEXT (R9, max 500 Zeichen).

    Bei gesetztem ``audit_log`` wird dieser atomar committet
    (target_id = Pending-ID).
    """
    pending = await db.get(PendingDividend, pending_id)
    if not pending or pending.user_id != user.id:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    if pending.status != STATUS_PENDING:
        raise HTTPException(status_code=409, detail="Bereits erfasst oder ignoriert")

    pending.status = STATUS_DISMISSED
    if data.reason:
        # max_length wird bereits von Pydantic erzwungen; defensiv truncate.
        pending.notes = data.reason[:500]
    pending.updated_at = datetime.utcnow()

    # Audit-Log atomar mit dem Status-Update committen (gleiche DB-Transaktion).
    if audit_log is not None:
        audit_log.target_id = pending.id
        db.add(audit_log)

    await db.commit()

    return {"id": str(pending.id), "status": pending.status}


@router.post("/{pending_id}/dismiss")
@limiter.limit("30/minute")
async def dismiss_pending_dividend(
    request: Request,
    pending_id: uuid.UUID,
    data: DismissDividendRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Pending-Eintrag dauerhaft als ignoriert markieren. Delegiert an
    ``dismiss_pending_dividend_core``.
    """
    return await dismiss_pending_dividend_core(db, user, pending_id, data)
