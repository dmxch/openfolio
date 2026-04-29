"""Service layer for applying transaction effects to positions."""

import logging
from uuid import UUID

from dateutils import utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import Position
from models.transaction import Transaction, TransactionType

logger = logging.getLogger(__name__)


def apply_transaction_to_position(
    pos: Position,
    txn_type: TransactionType,
    shares: float,
    total_chf: float,
    stop_loss_price: float | None = None,
    stop_loss_method: str | None = None,
    stop_loss_confirmed_at_broker: bool | None = None,
) -> None:
    """Mutate position shares and cost_basis_chf based on transaction type.

    This centralizes the logic that was previously duplicated in the
    transactions router (create, update, delete endpoints).
    """
    if txn_type == TransactionType.buy:
        pos.shares = float(pos.shares) + shares
        pos.cost_basis_chf = float(pos.cost_basis_chf) + total_chf
        if stop_loss_price is not None:
            pos.stop_loss_price = stop_loss_price
            pos.stop_loss_method = stop_loss_method
            pos.stop_loss_confirmed_at_broker = stop_loss_confirmed_at_broker or False
            pos.stop_loss_updated_at = utcnow()
    elif txn_type == TransactionType.sell:
        old_shares = float(pos.shares)
        pos.shares = max(0, old_shares - shares)
        if old_shares > 0:
            sell_ratio = shares / old_shares
            pos.cost_basis_chf = float(pos.cost_basis_chf) * (1 - sell_ratio)
    elif txn_type == TransactionType.delivery_in:
        pos.shares = float(pos.shares) + shares
        pos.cost_basis_chf = float(pos.cost_basis_chf) + total_chf
    elif txn_type == TransactionType.delivery_out:
        old_shares = float(pos.shares)
        pos.shares = max(0, old_shares - shares)
        if old_shares > 0:
            sell_ratio = shares / old_shares
            pos.cost_basis_chf = float(pos.cost_basis_chf) * (1 - sell_ratio)

    _sync_active_state(pos)


def _sync_active_state(pos: Position) -> None:
    """Keep is_active and stop-loss state in sync with shares.

    A 0-share position must not stay is_active=True: portfolio_service still
    returns it, the position keeps its stop-loss, and rule_alert_service emits
    stop_proximity emails for a closed position.
    """
    if float(pos.shares) <= 0:
        pos.is_active = False
        pos.stop_loss_price = None
        pos.stop_loss_method = None
        pos.stop_loss_confirmed_at_broker = False
        pos.stop_loss_updated_at = None
    elif not pos.is_active:
        pos.is_active = True


def reverse_transaction_on_position(
    pos: Position,
    txn_type: TransactionType,
    shares: float,
    total_chf: float,
) -> None:
    """Reverse the effect of a transaction on a position (for delete/update)."""
    if txn_type in (TransactionType.buy, TransactionType.delivery_in):
        pos.shares = max(0, float(pos.shares) - shares)
        pos.cost_basis_chf = max(0, float(pos.cost_basis_chf) - total_chf)
    elif txn_type in (TransactionType.sell, TransactionType.delivery_out):
        pos.shares = float(pos.shares) + shares

    _sync_active_state(pos)


async def fix_foreign_total_chf(db: AsyncSession, user_id: UUID) -> dict:
    """Recalculate total_chf from fx_rate_to_chf for all foreign currency transactions.

    Args:
        db: Async database session.
        user_id: The current user's ID.

    Returns:
        Dict with count of fixed transactions and their details.
    """
    result = await db.execute(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.currency != "CHF",
            Transaction.shares > 0,
            Transaction.price_per_share > 0,
            Transaction.fx_rate_to_chf > 0,
        )
    )
    txns = result.scalars().all()

    fixed = []
    for txn in txns:
        old_total = float(txn.total_chf)
        new_total = round(
            abs(float(txn.shares) * float(txn.price_per_share)) * float(txn.fx_rate_to_chf)
            + float(txn.fees_chf),
            2,
        )
        if abs(old_total - new_total) >= 0.01:
            txn.total_chf = new_total
            fixed.append({
                "ticker": txn.isin or str(txn.position_id)[:8],
                "date": txn.date.isoformat(),
                "old_total_chf": old_total,
                "new_total_chf": new_total,
                "delta": round(new_total - old_total, 2),
            })

    if fixed:
        await db.commit()

    return {"fixed": len(fixed), "transactions": fixed}
