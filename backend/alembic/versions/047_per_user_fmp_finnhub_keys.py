"""add per-user fmp and finnhub api key fields

Ergaenzt user_settings um zwei verschluesselte Spalten:
- fmp_api_key: Financial Modeling Prep (Fundamentals)
- finnhub_api_key: Finnhub (Earnings Calendar)

Beide werden Fernet-verschluesselt im Backend gespeichert. Mit dieser
Migration zusammen mit dem entsprechenden Code-Wechsel werden die
globalen Env-Var-Fallbacks (FMP_API_KEY, FINNHUB_API_KEY) entfernt —
jeder User muss seinen eigenen Key in den Settings eintragen. FRED-
Spalte existiert bereits und bleibt unveraendert.

Revision ID: 047
Revises: 046
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "047"
down_revision: Union[str, None] = "046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.add_column(sa.Column("fmp_api_key", sa.Text(), nullable=True))
        batch.add_column(sa.Column("finnhub_api_key", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("finnhub_api_key")
        batch.drop_column("fmp_api_key")
