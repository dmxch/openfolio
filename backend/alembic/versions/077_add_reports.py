"""Add reports table (Report-Vault).

Speichert die vom Claude-Finance-Workspace hochgeladenen Markdown-Briefe
(daily_brief, weekly_check, trade, earnings, institutional_flow, macro,
review, …). User-scoped (Multi-User). `source_path` ist der natuerliche
Upsert-Key pro Quelldatei, `content_hash` kurzschliesst unveraenderte
Re-Pushes. `tags` ist user-editierbar.

Revision ID: 077
Revises: 076
Create Date: 2026-05-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "077"
down_revision: Union[str, None] = "076"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False, server_default="other"),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("source_path", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_path", name="uq_report_user_source_path"),
    )
    op.create_index("ix_reports_user_id", "reports", ["user_id"])
    op.create_index("ix_reports_user_date", "reports", ["user_id", "report_date"])
    op.create_index("ix_reports_user_category", "reports", ["user_id", "category"])


def downgrade() -> None:
    op.drop_index("ix_reports_user_category", table_name="reports")
    op.drop_index("ix_reports_user_date", table_name="reports")
    op.drop_index("ix_reports_user_id", table_name="reports")
    op.drop_table("reports")
