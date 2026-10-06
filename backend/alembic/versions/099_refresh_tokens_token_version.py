"""refresh_tokens.token_version: parallel erneuerte Refresh-Tokens nach Revoke entwerten.

Ein Refresh-Token merkt sich die ``users.token_version`` bei Ausstellung. Jede
Revoke-all-Aktion erhöht diese Version; ein Token, das parallel zu einer solchen
Aktion entstand (unsichtbar für deren UPDATE unter READ COMMITTED), trägt die alte
Version und wird beim Refresh abgelehnt.

Kein Backfill: bestehende Tokens starten mit 0. Sessions von Usern mit
token_version > 0 enden einmal (Re-Login). Idempotent (inspect-Check).

Revision ID: 099
Revises: 098
Create Date: 2026-10-06
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "099"
down_revision: Union[str, None] = "098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("refresh_tokens")}
    if "token_version" not in cols:
        op.add_column(
            "refresh_tokens",
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        )
    # Bewusst KEIN Backfill aus users.token_version: er wuerde einen Token, der vor
    # diesem Deploy durch die Revoke-Race gerutscht ist, nachtraeglich legitimieren.
    # Folge: User mit token_version > 0 melden sich einmal neu an.


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("refresh_tokens")}
    if "token_version" in cols:
        op.drop_column("refresh_tokens", "token_version")
