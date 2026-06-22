"""EPS-Scanner: Tabelle eps_quarterly + User-Schwellenwerte in user_settings.

Additives Feature (EPS-Scanner). Neue universe-globale Zeitreihen-Tabelle fuer
Quartals-Reported-EPS plus drei nullable Filter-Schwellenwert-Spalten in
user_settings (NULL = Service-Defaults 25.0 / 5.0 / 5.0).

Revision ID: 084
Revises: 083
Create Date: 2026-06-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "084"
down_revision: Union[str, None] = "083"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eps_quarterly",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(length=30), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("eps", sa.Numeric(14, 4), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker", "period_end", name="uq_eps_quarterly_ticker_period"
        ),
    )
    op.create_index(
        "ix_eps_quarterly_ticker_period",
        "eps_quarterly",
        ["ticker", "period_end"],
    )
    op.create_index(
        "ix_eps_quarterly_fetched",
        "eps_quarterly",
        ["ticker", "fetched_at"],
    )

    op.add_column(
        "user_settings",
        sa.Column("eps_scanner_yoy_threshold", sa.Numeric(6, 2), nullable=True),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "eps_scanner_acceleration_margin", sa.Numeric(6, 2), nullable=True
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "eps_scanner_outlier_multiplier", sa.Numeric(6, 2), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "eps_scanner_outlier_multiplier")
    op.drop_column("user_settings", "eps_scanner_acceleration_margin")
    op.drop_column("user_settings", "eps_scanner_yoy_threshold")
    op.drop_index("ix_eps_quarterly_fetched", table_name="eps_quarterly")
    op.drop_index("ix_eps_quarterly_ticker_period", table_name="eps_quarterly")
    op.drop_table("eps_quarterly")
