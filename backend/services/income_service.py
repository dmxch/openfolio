"""Income-Metriken: Dividenden Yield-on-Cost (rueckwaerts, effektiv erhalten).

YoC = in den letzten 12 Monaten EFFEKTIV erhaltene Dividenden (netto, total_chf nach
Quellensteuer) / cost_basis_chf. Rueckwaerts — KEIN Forecast/Raten (vorwaerts-
gerichteter Forecast bewusst deferred). Nur liquide Wertschriften (stock/etf,
shares>0, kein count_as_cash); Vorsorge/RE/PE sind durch den type-Filter ohnehin
draussen (Invariante #2). Dividenden-total_chf ist bereits CHF -> kein FX.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType


async def get_dividend_yield_on_cost(
    db: AsyncSession, user_id: uuid.UUID, today: date | None = None
) -> dict:
    today = today or date.today()
    cutoff = today - timedelta(days=365)

    pos_rows = (await db.execute(
        select(Position.id, Position.ticker, Position.name, Position.cost_basis_chf).where(
            Position.user_id == user_id,
            Position.is_active.is_(True),
            Position.type.in_([AssetType.stock, AssetType.etf]),
            Position.shares > 0,
            Position.cost_basis_chf > 0,
            Position.count_as_cash.is_(False),
        )
    )).all()
    base = {
        "has_data": False, "portfolio_yoc_pct": None, "trailing_dividends_chf": 0.0,
        "eligible_cost_basis_chf": 0.0, "window_days": 365, "positions": [],
    }
    if not pos_rows:
        return base

    div_rows = (await db.execute(
        select(
            Transaction.position_id,
            func.coalesce(func.sum(Transaction.total_chf), 0),
        ).where(
            Transaction.user_id == user_id,
            Transaction.type == TransactionType.dividend,
            Transaction.date >= cutoff,
        ).group_by(Transaction.position_id)
    )).all()
    div_by_pos = {pid: float(s) for pid, s in div_rows}

    positions: list[dict] = []
    total_div = 0.0
    total_cost = 0.0
    for pid, ticker, name, cost in pos_rows:
        cost = float(cost)
        total_cost += cost
        d = div_by_pos.get(pid, 0.0)
        if d <= 0:
            continue
        total_div += d
        positions.append({
            "ticker": ticker,
            "name": name,
            "dividends_12m_chf": round(d, 2),
            "cost_basis_chf": round(cost, 2),
            "yoc_pct": round(d / cost * 100.0, 2),
        })

    positions.sort(key=lambda p: p["yoc_pct"], reverse=True)
    return {
        "has_data": len(positions) > 0,
        # Portfolio-YoC = Einkommens-Rendite auf den GESAMTEN liquiden Wertschriften-
        # Sleeve (inkl. Nicht-Zahler im Nenner -> ehrliche Gesamt-Einkommensrendite).
        "portfolio_yoc_pct": round(total_div / total_cost * 100.0, 2) if total_cost > 0 else None,
        "trailing_dividends_chf": round(total_div, 2),
        "eligible_cost_basis_chf": round(total_cost, 2),
        "window_days": 365,
        "positions": positions,
    }
