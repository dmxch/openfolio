"""add real estate tables

Revision ID: 004
Revises: 003
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def _create_enum_if_not_exists(name, values):
    """Create enum type only if it doesn't already exist."""
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = :name"), {"name": name})
    if not result.scalar():
        vals = ", ".join(f"'{v}'" for v in values)
        conn.execute(sa.text(f"CREATE TYPE {name} AS ENUM ({vals})"))


def upgrade() -> None:
    _create_enum_if_not_exists("propertytype", ["efh", "mfh", "stockwerk", "grundstueck"])
    _create_enum_if_not_exists("mortgagetype", ["fixed", "saron", "variable"])
    _create_enum_if_not_exists("expensecategory", ["insurance", "utilities", "maintenance", "repair", "tax", "other"])
    _create_enum_if_not_exists("frequency", ["monthly", "quarterly", "yearly", "once"])

    # Check if tables already exist (created by seed.py's create_all)
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'properties'"))
    if result.scalar():
        return

    op.create_table(
        "properties",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(300), nullable=True),
        sa.Column("property_type", sa.Enum("efh", "mfh", "stockwerk", "grundstueck", name="propertytype", create_type=False), nullable=False),
        sa.Column("purchase_date", sa.Date, nullable=True),
        sa.Column("purchase_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("estimated_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("estimated_value_date", sa.Date, nullable=True),
        sa.Column("land_area_m2", sa.Numeric(10, 2), nullable=True),
        sa.Column("living_area_m2", sa.Numeric(10, 2), nullable=True),
        sa.Column("rooms", sa.Numeric(3, 1), nullable=True),
        sa.Column("year_built", sa.Integer, nullable=True),
        sa.Column("canton", sa.String(2), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "mortgages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("property_id", UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.Enum("fixed", "saron", "variable", name="mortgagetype", create_type=False), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("interest_rate", sa.Numeric(5, 3), nullable=False),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("monthly_payment", sa.Numeric(12, 2), nullable=True),
        sa.Column("annual_payment", sa.Numeric(12, 2), nullable=True),
        sa.Column("amortization_monthly", sa.Numeric(12, 2), nullable=True),
        sa.Column("amortization_annual", sa.Numeric(12, 2), nullable=True),
        sa.Column("bank", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "property_expenses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("property_id", UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("category", sa.Enum("insurance", "utilities", "maintenance", "repair", "tax", "other", name="expensecategory", create_type=False), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("recurring", sa.Boolean, server_default="false"),
        sa.Column("frequency", sa.Enum("monthly", "quarterly", "yearly", "once", name="frequency", create_type=False), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "property_income",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("property_id", UUID(as_uuid=True), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("tenant", sa.String(200), nullable=True),
        sa.Column("recurring", sa.Boolean, server_default="false"),
        sa.Column("frequency", sa.Enum("monthly", "quarterly", "yearly", "once", name="frequency", create_type=False), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("property_income")
    op.drop_table("property_expenses")
    op.drop_table("mortgages")
    op.drop_table("properties")
    op.execute("DROP TYPE frequency")
    op.execute("DROP TYPE expensecategory")
    op.execute("DROP TYPE mortgagetype")
    op.execute("DROP TYPE propertytype")
