"""Private Equity service — CRUD, summary, position sync."""

import logging
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.private_equity import PrivateEquityHolding, PrivateEquityValuation, PrivateEquityDividend
from models.position import Position, AssetType, PricingMode, PriceSource
from services.encryption_helpers import encrypt_field, decrypt_field

logger = logging.getLogger(__name__)


def _holding_to_dict(h: PrivateEquityHolding, include_children: bool = False) -> dict:
    """Convert holding to dict with decrypted PII fields."""
    latest_valuation = None
    if h.valuations:
        v = h.valuations[0]  # Already ordered desc by date
        latest_valuation = {
            "id": str(v.id),
            "valuation_date": v.valuation_date.isoformat(),
            "gross_value_per_share": float(v.gross_value_per_share),
            "discount_pct": float(v.discount_pct),
            "net_value_per_share": float(v.net_value_per_share),
            "source": v.source,
        }

    gross_value_per_share = float(h.valuations[0].gross_value_per_share) if h.valuations else None
    net_value_per_share = float(h.valuations[0].net_value_per_share) if h.valuations else None
    total_gross = h.num_shares * gross_value_per_share if gross_value_per_share else None
    total_net = h.num_shares * net_value_per_share if net_value_per_share else None

    total_dividends_net = sum(float(d.net_amount) for d in h.dividends) if h.dividends else 0

    # Dividend yield: last dividend / current gross value per share
    dividend_yield = None
    if h.dividends and gross_value_per_share and gross_value_per_share > 0:
        last_dps = float(h.dividends[0].dividend_per_share)
        dividend_yield = round(last_dps / gross_value_per_share * 100, 2)

    result = {
        "id": str(h.id),
        "company_name": decrypt_field(h.company_name),
        "num_shares": h.num_shares,
        "nominal_value": float(h.nominal_value),
        "purchase_price_per_share": float(h.purchase_price_per_share) if h.purchase_price_per_share else None,
        "purchase_date": h.purchase_date.isoformat() if h.purchase_date else None,
        "currency": h.currency,
        "uid_number": decrypt_field(h.uid_number),
        "register_nr": decrypt_field(h.register_nr),
        "notes": decrypt_field(h.notes),
        "is_active": h.is_active,
        "latest_valuation": latest_valuation,
        "gross_value_per_share": gross_value_per_share,
        "net_value_per_share": net_value_per_share,
        "total_gross_value": round(total_gross, 2) if total_gross else None,
        "total_net_value": round(total_net, 2) if total_net else None,
        "total_dividends_net": round(total_dividends_net, 2),
        "dividend_yield_pct": dividend_yield,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }

    if include_children:
        result["valuations"] = [
            {
                "id": str(v.id),
                "valuation_date": v.valuation_date.isoformat(),
                "gross_value_per_share": float(v.gross_value_per_share),
                "discount_pct": float(v.discount_pct),
                "net_value_per_share": float(v.net_value_per_share),
                "source": v.source,
                "notes": decrypt_field(v.notes),
            }
            for v in h.valuations
        ]
        result["dividends"] = [
            {
                "id": str(d.id),
                "payment_date": d.payment_date.isoformat(),
                "dividend_per_share": float(d.dividend_per_share),
                "gross_amount": float(d.gross_amount),
                "withholding_tax_pct": float(d.withholding_tax_pct),
                "withholding_tax_amount": float(d.withholding_tax_amount),
                "net_amount": float(d.net_amount),
                "fiscal_year": d.fiscal_year,
                "notes": decrypt_field(d.notes),
            }
            for d in h.dividends
        ]

    return result


async def get_holdings_summary(db: AsyncSession, user_id: UUID) -> list[dict]:
    """Return all active PE holdings with latest valuation and dividend totals."""
    result = await db.execute(
        select(PrivateEquityHolding)
        .options(selectinload(PrivateEquityHolding.valuations), selectinload(PrivateEquityHolding.dividends))
        .where(PrivateEquityHolding.user_id == user_id, PrivateEquityHolding.is_active == True)
        .order_by(PrivateEquityHolding.created_at)
    )
    holdings = result.scalars().all()

    total_gross = 0
    items = []
    for h in holdings:
        d = _holding_to_dict(h)
        items.append(d)
        if d["total_gross_value"]:
            total_gross += d["total_gross_value"]

    return {
        "holdings": items,
        "total_gross_value": round(total_gross, 2),
        "count": len(items),
    }


async def get_holding_detail(db: AsyncSession, user_id: UUID, holding_id: UUID) -> dict | None:
    """Return single holding with full valuation and dividend history."""
    result = await db.execute(
        select(PrivateEquityHolding)
        .options(selectinload(PrivateEquityHolding.valuations), selectinload(PrivateEquityHolding.dividends))
        .where(PrivateEquityHolding.id == holding_id, PrivateEquityHolding.user_id == user_id)
    )
    h = result.scalars().first()
    if not h:
        return None
    return _holding_to_dict(h, include_children=True)


async def sync_position(db: AsyncSession, user_id: UUID, holding: PrivateEquityHolding) -> None:
    """Sync a synthetic Position for this PE holding (for Gesamtvermögen tracking)."""
    ticker = f"PE_{str(holding.id)[:8].upper()}"

    # Query latest valuation explicitly (avoid lazy-load in async context)
    val_result = await db.execute(
        select(PrivateEquityValuation)
        .where(PrivateEquityValuation.holding_id == holding.id)
        .order_by(PrivateEquityValuation.valuation_date.desc())
        .limit(1)
    )
    latest_val = val_result.scalars().first()

    gross_price = float(latest_val.gross_value_per_share) if latest_val else None
    company_name = decrypt_field(holding.company_name)

    # Find existing position
    pos_result = await db.execute(
        select(Position).where(Position.user_id == user_id, Position.ticker == ticker)
    )
    pos = pos_result.scalars().first()

    if not holding.is_active:
        if pos:
            pos.shares = 0
            pos.is_active = False
        return

    cost_basis = float(holding.purchase_price_per_share or holding.nominal_value) * holding.num_shares

    if pos:
        pos.name = company_name
        pos.shares = holding.num_shares
        pos.current_price = gross_price  # None if no valuation
        pos.cost_basis_chf = round(cost_basis, 2) if gross_price is not None else 0
        pos.is_active = True
    else:
        pos = Position(
            user_id=user_id,
            ticker=ticker,
            name=company_name,
            type=AssetType.private_equity,
            sector="Private Equity",
            industry="Private Equity",
            currency=holding.currency,
            pricing_mode=PricingMode.manual,
            price_source=PriceSource.manual,
            shares=holding.num_shares,
            current_price=gross_price,  # None if no valuation
            cost_basis_chf=round(cost_basis, 2) if gross_price is not None else 0,
            risk_class=4,
        )
        db.add(pos)

    await db.flush()
