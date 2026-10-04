"""users.token_version: Access-Tokens serverseitig entwertbar machen.

Der Access-Token trägt die Version als Claim ``tv``; Logout-all, Passwortwechsel,
Deaktivierung etc. erhöhen ``users.token_version`` und entwerten damit alle bereits
ausgestellten Access-Tokens (vorher lebten sie bis zum Ablauf der 15 Minuten weiter).

Idempotent: bei frischer DB legt ``Base.metadata.create_all()`` die Spalte schon aus
dem Model an (entrypoint.sh / tests), gewachsene DBs bekommen sie hier.

Revision ID: 098
Revises: 097
Create Date: 2026-10-04
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "098"
down_revision: Union[str, None] = "097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "token_version" not in cols:
        op.add_column(
            "users",
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "token_version" in cols:
        op.drop_column("users", "token_version")
