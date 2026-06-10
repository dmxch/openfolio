"""Verbreitere Fernet-verschluesselte Felder von VARCHAR(500) auf TEXT.

Projektregel: verschluesselte Felder immer Text, nie String(N) — Fernet
blaeht den Klartext ~x1.4 auf, ein langes SMTP-Passwort oder ntfy-Token
fuehrte zu StringDataRightTruncation und damit 500ern beim Speichern
(Review 2026-06-10, M7). Betroffen: smtp_config.password_encrypted (017)
und ntfy_config.access_token_encrypted (060).

Revision ID: 082
Revises: 081
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "082"
down_revision: Union[str, None] = "081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "smtp_config",
        "password_encrypted",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "ntfy_config",
        "access_token_encrypted",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "ntfy_config",
        "access_token_encrypted",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
    op.alter_column(
        "smtp_config",
        "password_encrypted",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=False,
    )
