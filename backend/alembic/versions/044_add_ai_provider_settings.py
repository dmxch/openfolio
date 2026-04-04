"""add AI provider settings to user_settings

Revision ID: 044
Revises: 043
Create Date: 2026-04-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "044"
down_revision: Union[str, None] = "043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_settings", sa.Column("ai_provider", sa.String(20), nullable=True))
    op.add_column("user_settings", sa.Column("ai_model", sa.String(50), nullable=True))
    op.add_column("user_settings", sa.Column("ai_api_key_encrypted", sa.Text, nullable=True))
    op.add_column("user_settings", sa.Column("ai_ollama_url", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("user_settings", "ai_ollama_url")
    op.drop_column("user_settings", "ai_api_key_encrypted")
    op.drop_column("user_settings", "ai_model")
    op.drop_column("user_settings", "ai_provider")
