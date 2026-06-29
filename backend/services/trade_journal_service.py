"""Trade-Journal: Plan (Vault-Report) -> Ist (Transaktion) -> Adhaerenz.

Die PLAN-Seite sind 'trade'-Reports aus dem claude-finance-Vault (Trade-Plan /
Sell-Check), die IST-Seite ist die verknuepfte Transaktion (``linked_transaction_id``,
beim Buchen von claude-finance gesetzt). Dieser Service joint beide read-only und
leitet den Status ab: ``executed`` (Plan umgesetzt) vs. ``open`` (geplant/erwogen,
nicht ausgefuehrt). Beruehrt KEINE Rendite-/Snapshot-Pfade (reine Sicht).

Zusaetzlich: ``try_auto_link_trade_report`` verknuepft beim Buchen einer Buy/Sell-
Transaktion den juengsten offenen Plan-Report automatisch (fuer asynchrone Fills/
Imports, wo kein Skill den Link taggen kann).
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import Position
from models.report import Report
from models.transaction import Transaction, TransactionType

logger = logging.getLogger(__name__)

# Plan->Ist-Auto-Link: gleiches +/-Fenster wie die Pending-Order-Reconciliation.
_LINK_WINDOW_DAYS = 35


def _excerpt(body: str | None, max_len: int = 180) -> str | None:
    """Kurze Rationale-Vorschau aus dem Markdown-Body: die erste substanzielle
    Prosa-Zeile (Headings, Listen-/Tabellen-/Zitat-/Code-/Trenner-Marker und
    sehr kurze Label-Fragmente uebersprungen), grob von Inline-Markdown befreit
    und auf ``max_len`` gekuerzt. None, wenn nichts Brauchbares vorhanden ist."""
    if not body:
        return None
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "---", "===", "|", ">", "```", "<!--")):
            continue
        line = line.lstrip("-*•").lstrip("0123456789.").strip()
        clean = line.replace("**", "").replace("`", "").replace("__", "").strip()
        if len(clean) < 15:  # zu kurze Fragmente (Labels/Marker) ueberspringen
            continue
        return (clean[:max_len].rstrip() + "…") if len(clean) > max_len else clean
    return None


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
            "rationale": _excerpt(r.body),
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


async def try_auto_link_trade_report(db: AsyncSession, txn: Transaction, user_id: uuid.UUID):
    """Best-effort: verknuepft den juengsten OFFENEN 'trade'-Report (Plan) mit
    gleichem Ticker+Seite im Fenster mit dieser frisch gebuchten Buy/Sell-Transaktion.

    Deckt asynchrone Fills ab (Auto-Fill-Reconciliation / CSV-Import), wo kein Skill
    den ``--linked-txn``-Tag setzen kann. Setzt NUR ``report.linked_transaction_id``
    (Journal-Feld) — beruehrt keine Rendite-/Snapshot-/cost_basis-Invariante.

    Idempotent + konservativ: ist die Txn bereits an einen Report gehaengt -> no-op;
    bereits verlinkte Reports werden NIE ueberschrieben. Spiegelt
    ``try_auto_fill_order`` (Pending-Orders), aber matcht ueber ``report_date`` und
    nimmt den JUENGSTEN Plan zuerst (der frischeste Plan ist der umgesetzte), statt FIFO.
    Gibt den verlinkten Report zurueck, sonst None.
    """
    if txn.type not in (TransactionType.buy, TransactionType.sell):
        return None
    # Diese Transaktion ist bereits an einen Report verlinkt -> nicht erneut.
    already = await db.execute(
        select(Report.id).where(Report.linked_transaction_id == txn.id).limit(1)
    )
    if already.first() is not None:
        return None
    pos = await db.get(Position, txn.position_id)
    if pos is None or not pos.ticker:
        return None

    side = txn.type.value
    window_start = txn.date - timedelta(days=_LINK_WINDOW_DAYS)
    # Plan liegt typisch VOR der Ausfuehrung; +3d Toleranz fuer am selben/folgenden
    # Tag erfasste Stop-Out-/Reconciliation-Reports.
    window_end = txn.date + timedelta(days=3)

    result = await db.execute(
        select(Report)
        .where(
            Report.user_id == user_id,
            Report.category == "trade",
            Report.archived_at.is_(None),
            Report.linked_transaction_id.is_(None),
            Report.side == side,
            func.upper(Report.ticker) == pos.ticker.upper(),
            Report.report_date >= window_start,
            Report.report_date <= window_end,
        )
        .order_by(Report.report_date.desc(), Report.created_at.desc())
        .limit(1)
    )
    rep = result.scalars().first()
    if rep is None:
        return None

    rep.linked_transaction_id = txn.id
    await db.commit()
    logger.info(
        "trade_report_auto_link user=%s report=%s ticker=%s side=%s txn=%s txn_date=%s",
        user_id, rep.id, pos.ticker, side, txn.id, txn.date,
    )
    return rep


async def try_auto_link_trade_reports_bulk(
    db: AsyncSession, txns, user_id: uuid.UUID
) -> int:
    """Bulk-Variante fuer den CSV-Import-Hook. Liefert die Anzahl verlinkter Plaene."""
    linked = 0
    for txn in txns:
        try:
            if await try_auto_link_trade_report(db, txn, user_id) is not None:
                linked += 1
        except Exception as e:  # best-effort, darf den Import nie kippen
            logger.warning("trade_report_link_bulk_failed txn=%s error=%s", getattr(txn, "id", None), e)
    return linked
