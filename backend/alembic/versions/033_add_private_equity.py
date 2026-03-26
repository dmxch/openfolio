"""add private equity tables and asset type enum

Revision ID: 033
Revises: 68c381537c96
Create Date: 2026-03-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = '033'
down_revision: Union[str, None] = '68c381537c96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'private_equity' to AssetType enum
    op.execute("ALTER TYPE assettype ADD VALUE IF NOT EXISTS 'private_equity'")

    # Create private_equity_holdings table
    op.create_table(
        'private_equity_holdings',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('company_name', sa.Text(), nullable=False),
        sa.Column('num_shares', sa.Integer(), nullable=False),
        sa.Column('nominal_value', sa.Numeric(10, 2), nullable=False),
        sa.Column('purchase_price_per_share', sa.Numeric(10, 2), nullable=True),
        sa.Column('purchase_date', sa.Date(), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='CHF'),
        sa.Column('uid_number', sa.Text(), nullable=True),
        sa.Column('register_nr', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Create private_equity_valuations table
    op.create_table(
        'private_equity_valuations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('holding_id', UUID(as_uuid=True), sa.ForeignKey('private_equity_holdings.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('valuation_date', sa.Date(), nullable=False),
        sa.Column('gross_value_per_share', sa.Numeric(10, 2), nullable=False),
        sa.Column('discount_pct', sa.Numeric(5, 2), nullable=False, server_default=sa.text('30.0')),
        sa.Column('net_value_per_share', sa.Numeric(10, 2), nullable=False),
        sa.Column('source', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('holding_id', 'valuation_date', name='uq_pe_valuation_date'),
    )

    # Create private_equity_dividends table
    op.create_table(
        'private_equity_dividends',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('holding_id', UUID(as_uuid=True), sa.ForeignKey('private_equity_holdings.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('payment_date', sa.Date(), nullable=False),
        sa.Column('dividend_per_share', sa.Numeric(10, 2), nullable=False),
        sa.Column('gross_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('withholding_tax_pct', sa.Numeric(5, 2), nullable=False, server_default=sa.text('35.0')),
        sa.Column('withholding_tax_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('net_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('private_equity_dividends')
    op.drop_table('private_equity_valuations')
    op.drop_table('private_equity_holdings')
    # Note: Cannot remove enum value in PostgreSQL
