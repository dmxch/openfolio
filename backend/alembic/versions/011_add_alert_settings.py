"""Add alert settings to user_settings."""

from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def _col_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    insp = inspect(bind)
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade():
    bool_cols = [
        "alert_stop_missing", "alert_stop_unconfirmed", "alert_stop_proximity",
        "alert_stop_review", "alert_ma_critical", "alert_ma_warning",
        "alert_position_limit", "alert_sector_limit", "alert_loss",
        "alert_market_climate", "alert_vix", "alert_earnings",
        "alert_allocation", "alert_position_type_missing",
    ]
    for col in bool_cols:
        if not _col_exists("user_settings", col):
            op.add_column("user_settings", sa.Column(col, sa.Boolean(), server_default="true"))

    float_cols = [
        ("alert_satellite_loss_pct", "-15.0"),
        ("alert_core_loss_pct", "-25.0"),
        ("alert_stop_proximity_pct", "3.0"),
    ]
    for col, default in float_cols:
        if not _col_exists("user_settings", col):
            op.add_column("user_settings", sa.Column(col, sa.Float(), server_default=default))


def downgrade():
    cols = [
        "alert_stop_missing", "alert_stop_unconfirmed", "alert_stop_proximity",
        "alert_stop_review", "alert_ma_critical", "alert_ma_warning",
        "alert_position_limit", "alert_sector_limit", "alert_loss",
        "alert_market_climate", "alert_vix", "alert_earnings",
        "alert_allocation", "alert_position_type_missing",
        "alert_satellite_loss_pct", "alert_core_loss_pct", "alert_stop_proximity_pct",
    ]
    for col in cols:
        if _col_exists("user_settings", col):
            op.drop_column("user_settings", col)
