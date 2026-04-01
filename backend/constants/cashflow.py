"""Cashflow type constants shared across services."""

from models.transaction import TransactionType

INFLOW_TYPES = {TransactionType.buy, TransactionType.deposit, TransactionType.delivery_in}
OUTFLOW_TYPES = {TransactionType.sell, TransactionType.withdrawal, TransactionType.delivery_out}
