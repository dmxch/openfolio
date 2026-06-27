"""Trade-Journal: Plan (Vault-Report) -> Ist (Transaktion) -> Adhaerenz.

Die PLAN-Seite sind 'trade'-Reports aus dem claude-finance-Vault (Trade-Plan /
Sell-Check), die IST-Seite ist die verknuepfte Transaktion (``linked_transaction_id``,
beim Buchen von claude-finance gesetzt). Dieser Service joint beide read-only und
leitet den Status ab: ``executed`` (Plan umgesetzt) vs. ``open`` (geplant/erwogen,
nicht ausgefuehrt). Beruehrt KEINE Rendite-/Snapshot-Pfade (reine Sicht).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.report import Report
from models.transaction import Transaction


async def get_trade_journal(db: AsyncSession, user_id: uuid.UUID) -> dict:
    stmt = (
        select(Report)
        .where(
            Report.user_id == user_id,
            Report.category == "trade",
            Report.archived_at.is_(None),
        )
        .order_by(Report.report_date.desc(), Report.created_at.desc())
    )
    reports = (await db.execute(stmt)).scalars().all()

    txn_ids = [r.linked_transaction_id for r in reports if r.linked_transaction_id]
    txn_map: dict[uuid.UUID, Transaction] = {}
    if txn_ids:
        rows = (await db.execute(
            select(Transaction).where(
                Transaction.id.in_(txn_ids), Transaction.user_id == user_id
            )
        )).scalars().all()
        txn_map = {t.id: t for t in rows}

    entries = []
    executed = 0
    for r in reports:
        t = txn_map.get(r.linked_transaction_id) if r.linked_transaction_id else None
        ist = None
        if t is not None:
            executed += 1
            ist = {
                "transaction_id": str(t.id),
                "type": t.type.value if hasattr(t.type, "value") else t.type,
                "shares": float(t.shares),
                "price_per_share": float(t.price_per_share),
                "date": t.date.isoformat() if t.date else None,
                "currency": t.currency,
                "total_chf": float(t.total_chf),
            }
        entries.append({
            "report_id": str(r.id),
            "title": r.title,
            "report_date": r.report_date.isoformat() if r.report_date else None,
            "ticker": r.ticker,
            "side": r.side,
            "status": "executed" if t is not None else "open",
            "ist": ist,
        })

    return {
        "entries": entries,
        "summary": {
            "total": len(entries),
            "executed": executed,
            "open": len(entries) - executed,
        },
    }
