"""remove news, newsletter and ai-provider features

Entfernt das News-, Newsletter- und KI-Zusammenfassungs-Feature komplett:
- `news_articles` Tabelle wird gedroppt (Content wird taeglich neu gefetcht
  solange das Feature aktiv war — kein Datenverlust von historischem Wert)
- 6 Spalten aus `user_settings`:
  * newsletter_frequency, newsletter_scope
  * ai_provider, ai_model, ai_api_key_encrypted, ai_ollama_url
- `last_email_digest_at` BLEIBT: wird von `price_alert_service` fuer das
  15-Minuten-Batching der Alert-E-Mails genutzt, nicht nur vom Newsletter.

Revision ID: 046
Revises: 045
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "046"
down_revision: Union[str, None] = "045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # news_articles Tabelle entfernen (inkl. aller Indizes und Constraints).
    op.drop_table("news_articles")

    # Newsletter- und AI-Provider-Spalten aus user_settings entfernen.
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("newsletter_frequency")
        batch.drop_column("newsletter_scope")
        batch.drop_column("ai_provider")
        batch.drop_column("ai_model")
        batch.drop_column("ai_api_key_encrypted")
        batch.drop_column("ai_ollama_url")


def downgrade() -> None:
    # Rekreiere die Spalten mit denselben Typen/Defaults wie in den
    # Original-Migrationen 043 + 044. Daten sind natuerlich verloren.
    with op.batch_alter_table("user_settings") as batch:
        batch.add_column(
            sa.Column(
                "newsletter_frequency",
                sa.String(length=10),
                nullable=False,
                server_default="off",
            )
        )
        batch.add_column(
            sa.Column(
                "newsletter_scope",
                sa.String(length=20),
                nullable=False,
                server_default="all",
            )
        )
        batch.add_column(
            sa.Column("ai_provider", sa.String(length=20), nullable=True)
        )
        batch.add_column(
            sa.Column("ai_model", sa.String(length=50), nullable=True)
        )
        batch.add_column(
            sa.Column("ai_api_key_encrypted", sa.Text(), nullable=True)
        )
        batch.add_column(
            sa.Column("ai_ollama_url", sa.String(length=255), nullable=True)
        )

    # news_articles Tabelle wiederherstellen (Schema aus Migration 043).
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_sentiment", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "url", name="uq_news_articles_ticker_url"),
    )
    op.create_index(
        "ix_news_articles_ticker", "news_articles", ["ticker"], unique=False
    )
    op.create_index(
        "ix_news_articles_published_at",
        "news_articles",
        ["published_at"],
        unique=False,
    )
