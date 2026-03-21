"""widen encrypted fields to text for Fernet storage

Revision ID: 030
Revises: 029
Create Date: 2026-03-21

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # precious_metal_items: serial_number, storage_location
    op.alter_column(
        "precious_metal_items",
        "serial_number",
        type_=sa.Text(),
        existing_type=sa.String(50),
    )
    op.alter_column(
        "precious_metal_items",
        "storage_location",
        type_=sa.Text(),
        existing_type=sa.String(200),
    )
    # positions: bank_name
    op.alter_column(
        "positions",
        "bank_name",
        type_=sa.Text(),
        existing_type=sa.String(100),
    )
    # properties: name, address
    op.alter_column(
        "properties",
        "name",
        type_=sa.Text(),
        existing_type=sa.String(200),
        existing_nullable=False,
    )
    op.alter_column(
        "properties",
        "address",
        type_=sa.Text(),
        existing_type=sa.String(300),
    )


def downgrade() -> None:
    op.alter_column(
        "properties",
        "address",
        type_=sa.String(300),
        existing_type=sa.Text(),
    )
    op.alter_column(
        "properties",
        "name",
        type_=sa.String(200),
        existing_type=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "positions",
        "bank_name",
        type_=sa.String(100),
        existing_type=sa.Text(),
    )
    op.alter_column(
        "precious_metal_items",
        "storage_location",
        type_=sa.String(200),
        existing_type=sa.Text(),
    )
    op.alter_column(
        "precious_metal_items",
        "serial_number",
        type_=sa.String(50),
        existing_type=sa.Text(),
    )
