"""add news_articles table and newsletter settings

Revision ID: 043
Revises: 042
Create Date: 2026-04-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "043"
down_revision: Union[str, None] = "042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(30), nullable=False, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("snippet", sa.Text, nullable=True),
        sa.Column("published_at", sa.DateTime, nullable=True),
        sa.Column("fetched_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("ai_summary", sa.Text, nullable=True),
        sa.Column("ai_sentiment", sa.String(20), nullable=True),
        sa.UniqueConstraint("ticker", "url", name="uq_news_ticker_url"),
    )

    op.add_column("user_settings", sa.Column("newsletter_frequency", sa.String(10), server_default="off"))
    op.add_column("user_settings", sa.Column("newsletter_scope", sa.String(20), server_default="all"))


def downgrade() -> None:
    op.drop_column("user_settings", "newsletter_scope")
    op.drop_column("user_settings", "newsletter_frequency")
    op.drop_table("news_articles")
