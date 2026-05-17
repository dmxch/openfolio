"""Phase 3 (v0.40): position_type endgültig entfernen.

Klassifizierung Core/Satellite kommt seit v0.39 vollständig aus
bucket.risk_rules (active-risk-Bucket = stop_loss_method_default oder
stop_loss_default_pct gesetzt). position_type ist nur noch toter Ballast.

Diese Migration entfernt:
  - positions.position_type (String(10), nullable)
  - user_settings.alert_position_type_missing (Boolean default True)

Backward-Compat: Externe API-Konsumenten, die das Feld bisher gelesen
haben, sehen es seit v0.39.x bereits nicht mehr in der Response — die
Migration ist damit additiv-konform.

Revision ID: 069
Revises: 068
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "069"
down_revision: Union[str, None] = "068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    positions_cols = {col["name"] for col in inspector.get_columns("positions")}
    if "position_type" in positions_cols:
        op.drop_column("positions", "position_type")

    user_settings_cols = {col["name"] for col in inspector.get_columns("user_settings")}
    if "alert_position_type_missing" in user_settings_cols:
        op.drop_column("user_settings", "alert_position_type_missing")


def downgrade() -> None:
    op.add_column(
        "positions",
        sa.Column("position_type", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "alert_position_type_missing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
