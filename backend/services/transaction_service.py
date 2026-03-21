"""Service layer for applying transaction effects to positions."""

from dateutils import utcnow

from models.position import Position
from models.transaction import TransactionType


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
