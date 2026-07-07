"""MFA policy enforcement: per-user mfa_required flag + global mfa_policy setting.

Revision ID: 094
Revises: 093
Create Date: 2026-07-07
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "094"
down_revision: Union[str, None] = "093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-user "MFA required" flag — enforced when mfa_policy = 'selected'.
    op.add_column(
        "users",
        sa.Column(
            "mfa_required",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # Global MFA enforcement policy (off | admins_only | selected | all).
    # Default 'all': MFA ist fuer alle User verpflichtend. Aenderbar im Admin-Panel
    # (PATCH /api/admin/settings). ON CONFLICT DO NOTHING -> ueberschreibt einen
    # bereits gesetzten Wert nicht (idempotent bei Re-Runs).
    op.execute(
        "INSERT INTO app_settings (key, value) VALUES ('mfa_policy', 'all') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'mfa_policy'")
    op.drop_column("users", "mfa_required")
