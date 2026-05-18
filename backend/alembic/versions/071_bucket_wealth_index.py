"""Bucket-Snapshot Wealth-Index + Wealth-Index-basierter Peak.

Ersetzt die bisherige nominale running_peak_chf-Logik (max(prev_peak,
total_value)) durch einen TWR-Wealth-Index-Chain. Konsequenz: Cashflows
(Sells, Re-Labeling-Outflows) zaehlen nicht mehr als Drawdown vs Peak.

Schema:
  - bucket_snapshots.wealth_index (Numeric(20,6), default 1.0) — cumulative
    TWR factor seit Bucket-Start.
  - bucket_snapshots.running_peak_wealth_index (Numeric(20,6), default 1.0)
    — All-Time-High des wealth_index bis zu diesem Snapshot.
  - bucket_snapshots.running_peak_chf bleibt vorhanden, wird aber neu
    befuellt als total_value_chf am Tag des Wealth-Index-Peaks.

Backfill pro (user_id, bucket_id) chronologisch:
  - Day 0: wealth=1.0, peak_wealth=1.0, peak_chf=total_value_chf
  - Day t: ret_factor = (V_t - cf_t) / V_{t-1}; nur wenn ret_factor > 0
      angewendet (analog drawdown_service._build_wealth_index).
    wealth_t = wealth_{t-1} * ret_factor
    if wealth_t > peak_wealth_{t-1}:
       peak_wealth_t = wealth_t, peak_chf_t = V_t
    else: uebernehmen.

Revision ID: 071
Revises: 070
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "071"
down_revision: Union[str, None] = "070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("bucket_snapshots")}

    if "wealth_index" not in existing_cols:
        op.add_column(
            "bucket_snapshots",
            sa.Column(
                "wealth_index",
                sa.Numeric(20, 6),
                nullable=False,
                server_default="1.0",
            ),
        )
    if "running_peak_wealth_index" not in existing_cols:
        op.add_column(
            "bucket_snapshots",
            sa.Column(
                "running_peak_wealth_index",
                sa.Numeric(20, 6),
                nullable=False,
                server_default="1.0",
            ),
        )

    # Backfill pro (user_id, bucket_id) chronologisch
    pairs = bind.execute(sa.text(
        "SELECT DISTINCT user_id, bucket_id FROM bucket_snapshots"
    )).fetchall()

    for user_id, bucket_id in pairs:
        rows = bind.execute(sa.text(
            "SELECT id, date, total_value_chf, net_cash_flow_chf "
            "FROM bucket_snapshots "
            "WHERE user_id = :uid AND bucket_id = :bid "
            "ORDER BY date ASC"
        ), {"uid": user_id, "bid": bucket_id}).fetchall()

        if not rows:
            continue

        prev_value = float(rows[0].total_value_chf or 0)
        wealth = 1.0
        peak_wealth = 1.0
        peak_chf = prev_value

        # Erster Eintrag: alles Initialwerte
        bind.execute(sa.text(
            "UPDATE bucket_snapshots SET wealth_index = :w, "
            "running_peak_wealth_index = :pw, running_peak_chf = :pc "
            "WHERE id = :id"
        ), {"w": wealth, "pw": peak_wealth, "pc": peak_chf, "id": rows[0].id})

        for snap in rows[1:]:
            value = float(snap.total_value_chf or 0)
            cf = float(snap.net_cash_flow_chf or 0)
            if prev_value > 0:
                ret_factor = (value - cf) / prev_value
                if ret_factor > 0:
                    wealth *= ret_factor
            if wealth > peak_wealth:
                peak_wealth = wealth
                peak_chf = value
            bind.execute(sa.text(
                "UPDATE bucket_snapshots SET wealth_index = :w, "
                "running_peak_wealth_index = :pw, running_peak_chf = :pc "
                "WHERE id = :id"
            ), {"w": wealth, "pw": peak_wealth, "pc": peak_chf, "id": snap.id})
            prev_value = value

    # Server-Default 1.0 bleibt erhalten — schuetzt raw-SQL-Inserts (Tests,
    # Loadtest-Seed) vor NOT-NULL-Violations. App-Code in snapshot_service
    # setzt die Werte ohnehin immer explizit.


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("bucket_snapshots")}
    if "running_peak_wealth_index" in cols:
        op.drop_column("bucket_snapshots", "running_peak_wealth_index")
    if "wealth_index" in cols:
        op.drop_column("bucket_snapshots", "wealth_index")
    # running_peak_chf bleibt — nominal-basierte Werte vor 071 sind nicht
    # rekonstruierbar, aber die Spalte ist semantisch unveraendert.
