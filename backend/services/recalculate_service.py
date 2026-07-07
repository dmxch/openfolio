"""Recalculate position shares and cost_basis_chf from transaction history.

Uses weighted-average cost for position cost_basis (existing behaviour) and
additionally computes realized P&L per sell transaction using the same
weighted-average method (consistent with the Swiss tax standard of using
the average purchase price per lot).
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position, PricingMode
from models.transaction import Transaction, TransactionType

logger = logging.getLogger(__name__)

ADDITIVE_TYPES = {TransactionType.buy, TransactionType.delivery_in}
REDUCTIVE_TYPES = {TransactionType.sell, TransactionType.delivery_out}


def _calculate_position_values(txns: list) -> tuple[float, float, float]:
    """Calculate shares, cost_basis_chf, and realized P&L from transactions.

    Also updates realized P&L fields on each sell/delivery_out transaction.
    Returns (shares, cost_basis_chf, total_realized_pnl_chf).
    """
    shares = 0.0
    cost_basis_chf = 0.0
    total_realized_pnl_chf = 0.0

    for txn in txns:
        if txn.type in ADDITIVE_TYPES:
            shares += float(txn.shares)
            cost_basis_chf += float(txn.total_chf)

        elif txn.type in REDUCTIVE_TYPES:
            sell_shares = float(txn.shares)
            sell_proceeds_chf = float(txn.total_chf)
            sell_fees_chf = float(txn.fees_chf)

            if shares > 0 and sell_shares > 0:
                # Oversell-Guard: mehr verkaufte als vorhandene Shares (Import-
                # Lücke) darf die Cost-Basis nie negativ machen — auf den
                # Bestand klemmen, der Rest ist nicht zuordenbar.
                if sell_shares > shares:
                    logger.warning(
                        "Oversell detected on txn %s: selling %s of %s shares — clamping",
                        getattr(txn, "id", "?"), sell_shares, shares,
                    )
                    sell_shares = shares

                # Weighted-average cost per share at time of sale
                avg_cost_per_share = cost_basis_chf / shares
                allocated_cost = avg_cost_per_share * sell_shares

                # Realized P&L = proceeds - allocated cost basis - fees
                realized = sell_proceeds_chf - allocated_cost - sell_fees_chf

                # Store on the transaction
                txn.cost_basis_at_sale = round(allocated_cost, 2)
                txn.realized_pnl_chf = round(realized, 2)
                # Also store in transaction currency (using fx_rate)
                fx = float(txn.fx_rate_to_chf) if float(txn.fx_rate_to_chf) > 0 else 1.0
                txn.realized_pnl = round(realized / fx, 2)

                total_realized_pnl_chf += realized

                # Reduce cost basis proportionally (unchanged logic)
                sell_ratio = sell_shares / shares
                cost_basis_chf *= (1 - sell_ratio)
            else:
                txn.cost_basis_at_sale = 0
                txn.realized_pnl_chf = 0
                txn.realized_pnl = 0

            shares = max(0, shares - sell_shares)

    return shares, cost_basis_chf, total_realized_pnl_chf


def _calculate_cost_basis_fx(txns: list) -> tuple[float, float]:
    """EX-Gebuehren-Kostenbasis in Nativwaehrung und in CHF zum Kaufzeit-FX.

    Reine Zusatz-Attribution fuer die FX-vs-Lokal-Renditezerlegung (additiv,
    display-only): beruehrt WEDER ``cost_basis_chf`` NOCH realized P&L. Nutzt
    bewusst dieselbe Iteration, dieselben ADDITIVE/REDUCTIVE-Typen, denselben
    Oversell-Clamp und denselben Weighted-Average-``sell_ratio`` wie
    ``_calculate_position_values``, damit die Identitaet
    ``(1 + R_lokal) * (1 + R_fx) == value_chf / cost_basis_chf_at_fx`` gilt
    (Golden-Master gepinnt, siehe tests/test_golden_master_calculations.py).
    Gebuehren bleiben absichtlich DRAUSSEN (CHF-Residuum) — sonst wuerde die
    Gebuehren-Last faelschlich dem Waehrungseffekt zugerechnet.

    Als separate Funktion gehalten (nicht in ``_calculate_position_values``
    integriert), um dessen 3-Tupel-Rueckgabe und alle bestehenden Aufrufer/Tests
    unveraendert zu lassen.

    Returns (cost_basis_native, cost_basis_chf_at_fx).
    """
    shares = 0.0
    cost_basis_native = 0.0
    cost_basis_chf_at_fx = 0.0

    for txn in txns:
        if txn.type in ADDITIVE_TYPES:
            qty = float(txn.shares)
            native = float(txn.price_per_share) * qty
            fx = float(txn.fx_rate_to_chf) if float(txn.fx_rate_to_chf) > 0 else 1.0
            shares += qty
            cost_basis_native += native
            cost_basis_chf_at_fx += native * fx

        elif txn.type in REDUCTIVE_TYPES:
            sell_shares = float(txn.shares)
            if shares > 0 and sell_shares > 0:
                if sell_shares > shares:
                    sell_shares = shares
                sell_ratio = sell_shares / shares
                cost_basis_native *= (1 - sell_ratio)
                cost_basis_chf_at_fx *= (1 - sell_ratio)
            shares = max(0, shares - sell_shares)

    return cost_basis_native, cost_basis_chf_at_fx


async def recalculate_position(db: AsyncSession, position_id: uuid.UUID) -> dict:
    pos = await db.get(Position, position_id)
    if not pos:
        raise ValueError(f"Position {position_id} not found")

    result = await db.execute(
        select(Transaction)
        .where(
            Transaction.position_id == position_id,
            # Defense in Depth: nur Transaktionen des Positions-Eigentümers —
            # fremde Txns dürfen die Cost-Basis nie beeinflussen.
            Transaction.user_id == pos.user_id,
        )
        .order_by(Transaction.date.asc(), Transaction.created_at.asc())
    )
    txns = result.scalars().all()

    old_shares = float(pos.shares)
    old_cost = float(pos.cost_basis_chf)

    # Skip positions with no transactions (cash, pension, commodities managed via precious_metal_items)
    if not txns and (pos.pricing_mode == PricingMode.manual or pos.type == AssetType.commodity):
        return {
            "position_id": str(position_id),
            "ticker": pos.ticker,
            "name": pos.name,
            "old_shares": old_shares,
            "old_cost_basis_chf": old_cost,
            "new_shares": old_shares,
            "new_cost_basis_chf": old_cost,
            "shares_match": True,
            "cost_match": True,
            "transaction_count": 0,
            "skipped": "manual position with no transactions",
        }

    shares, cost_basis_chf, total_realized_pnl_chf = _calculate_position_values(txns)

    pos.shares = round(shares, 8)
    pos.cost_basis_chf = round(cost_basis_chf, 2)
    cost_basis_native, cost_basis_chf_at_fx = _calculate_cost_basis_fx(txns)
    pos.cost_basis_native = round(cost_basis_native, 4)
    pos.cost_basis_chf_at_fx = round(cost_basis_chf_at_fx, 2)

    return {
        "position_id": str(position_id),
        "ticker": pos.ticker,
        "name": pos.name,
        "old_shares": old_shares,
        "old_cost_basis_chf": old_cost,
        "new_shares": float(pos.shares),
        "new_cost_basis_chf": float(pos.cost_basis_chf),
        "realized_pnl_chf": round(total_realized_pnl_chf, 2),
        "shares_match": abs(old_shares - float(pos.shares)) < 0.001,
        "cost_match": abs(old_cost - float(pos.cost_basis_chf)) < 0.01,
        "transaction_count": len(txns),
    }


async def recalculate_all_positions(db: AsyncSession, user_id: uuid.UUID | None = None) -> list[dict]:
    # Batch-load all positions
    query = select(Position).order_by(Position.ticker)
    if user_id is not None:
        query = query.where(Position.user_id == user_id)
    result = await db.execute(query)
    positions = result.scalars().all()

    if not positions:
        return []

    # Batch-load all transactions for these positions (eliminates N+1)
    pos_ids = [p.id for p in positions]
    txn_result = await db.execute(
        select(Transaction)
        .where(Transaction.position_id.in_(pos_ids))
        .order_by(Transaction.date.asc(), Transaction.created_at.asc())
    )
    all_txns = txn_result.scalars().all()

    # Group transactions by position_id
    from collections import defaultdict
    # Defense in Depth: Txn nur der Position zuordnen, wenn der Eigentümer
    # übereinstimmt — fremde Txns dürfen die Cost-Basis nie beeinflussen.
    pos_owner = {str(p.id): p.user_id for p in positions}
    txns_by_pos: dict[str, list] = defaultdict(list)
    for txn in all_txns:
        key = str(txn.position_id)
        if txn.user_id == pos_owner.get(key):
            txns_by_pos[key].append(txn)

    results = []
    for pos in positions:
        try:
            r = _recalculate_position_with_txns(pos, txns_by_pos.get(str(pos.id), []))
            results.append(r)
        except Exception as e:
            logger.warning("Recalculate failed for %s: %s", pos.ticker, e, exc_info=True)
            results.append({
                "position_id": str(pos.id),
                "ticker": pos.ticker,
                "error": str(e),
            })

    await db.commit()
    return results


def _recalculate_position_with_txns(pos: Position, txns: list) -> dict:
    """Recalculate a single position using pre-loaded transactions.
    Calculation logic is IDENTICAL to recalculate_position."""
    old_shares = float(pos.shares)
    old_cost = float(pos.cost_basis_chf)

    # Skip positions with no transactions (cash, pension, commodities managed via precious_metal_items)
    if not txns and (pos.pricing_mode == PricingMode.manual or pos.type == AssetType.commodity):
        return {
            "position_id": str(pos.id),
            "ticker": pos.ticker,
            "name": pos.name,
            "old_shares": old_shares,
            "old_cost_basis_chf": old_cost,
            "new_shares": old_shares,
            "new_cost_basis_chf": old_cost,
            "shares_match": True,
            "cost_match": True,
            "transaction_count": 0,
            "skipped": "position with no transactions (manual or commodity)",
        }

    shares, cost_basis_chf, total_realized_pnl_chf = _calculate_position_values(txns)

    pos.shares = round(shares, 8)
    pos.cost_basis_chf = round(cost_basis_chf, 2)
    cost_basis_native, cost_basis_chf_at_fx = _calculate_cost_basis_fx(txns)
    pos.cost_basis_native = round(cost_basis_native, 4)
    pos.cost_basis_chf_at_fx = round(cost_basis_chf_at_fx, 2)

    return {
        "position_id": str(pos.id),
        "ticker": pos.ticker,
        "name": pos.name,
        "old_shares": old_shares,
        "old_cost_basis_chf": old_cost,
        "new_shares": float(pos.shares),
        "new_cost_basis_chf": float(pos.cost_basis_chf),
        "realized_pnl_chf": round(total_realized_pnl_chf, 2),
        "shares_match": abs(old_shares - float(pos.shares)) < 0.001,
        "cost_match": abs(old_cost - float(pos.cost_basis_chf)) < 0.01,
        "transaction_count": len(txns),
    }


async def debug_position(db: AsyncSession, position_id: uuid.UUID) -> dict:
    pos = await db.get(Position, position_id)
    if not pos:
        raise ValueError(f"Position {position_id} not found")

    result = await db.execute(
        select(Transaction)
        .where(
            Transaction.position_id == position_id,
            # Defense in Depth: nur Transaktionen des Positions-Eigentümers —
            # fremde Txns dürfen die Cost-Basis nie beeinflussen.
            Transaction.user_id == pos.user_id,
        )
        .order_by(Transaction.date.asc(), Transaction.created_at.asc())
    )
    txns = result.scalars().all()

    shares = 0.0
    cost_basis_chf = 0.0
    steps = []

    for txn in txns:
        before_shares = shares
        before_cost = cost_basis_chf

        if txn.type in ADDITIVE_TYPES:
            shares += float(txn.shares)
            cost_basis_chf += float(txn.total_chf)
        elif txn.type in REDUCTIVE_TYPES:
            if shares > 0:
                sell_ratio = float(txn.shares) / shares
                cost_basis_chf *= (1 - sell_ratio)
            shares = max(0, shares - float(txn.shares))

        steps.append({
            "date": txn.date.isoformat(),
            "type": txn.type.value,
            "txn_shares": float(txn.shares),
            "txn_total_chf": float(txn.total_chf),
            "running_shares": round(shares, 8),
            "running_cost_basis": round(cost_basis_chf, 2),
            "realized_pnl_chf": float(txn.realized_pnl_chf) if txn.realized_pnl_chf is not None else None,
        })

    stored_shares = float(pos.shares)
    stored_cost = float(pos.cost_basis_chf)

    return {
        "position_id": str(position_id),
        "ticker": pos.ticker,
        "name": pos.name,
        "stored_shares": stored_shares,
        "stored_cost_basis_chf": stored_cost,
        "recalculated_shares": round(shares, 8),
        "recalculated_cost_basis_chf": round(cost_basis_chf, 2),
        "shares_match": abs(stored_shares - shares) < 0.001,
        "cost_match": abs(stored_cost - cost_basis_chf) < 0.01,
        "transactions": steps,
    }
