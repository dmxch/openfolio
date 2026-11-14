"""price_cache: id auf BIGINT, ticker auf 60 Zeichen, Kurse auf NUMERIC(18,8).

Vollreview 2026-11-13, drei Befunde an derselben Tabelle:

- GS09: ``id`` war INTEGER. Jeder ``INSERT ... ON CONFLICT`` zieht einen
  Sequenzwert, auch ohne neue Zeile. Bei 2^31 schlagen alle Kurs-Inserts fehl.
- K017: ``ticker`` war VARCHAR(30), ``positions.ticker`` erlaubt 60. Ein
  längerer Krypto-Ticker liess den Sammel-UPSERT für alle Ticker scheitern.
- K049: NUMERIC(14,4) rundete FX-Kurse wie JPYCHF=X (~0.0052) auf zwei
  signifikante Stellen. NUMERIC(18,8) behält die 10 Vorkommastellen.

Alle Spalten in EINEM ALTER TABLE: Postgres schreibt die Tabelle dann einmal
neu statt je Spalte einmal. Die Tabelle ist dabei gesperrt (ACCESS EXCLUSIVE).

Downgrade: Zeilen mit einem Ticker über 30 Zeichen passen nicht ins alte Schema
und werden gelöscht (Kurs-Cache, der Worker schreibt neu). Kurse werden auf 4
Stellen gerundet. Scheitert, sobald eine ``id`` über 2^31-1 liegt.

Revision ID: 100
Revises: 099
Create Date: 2026-11-13
"""

from typing import Union

from alembic import op

revision: str = "100"
down_revision: Union[str, None] = "099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE price_cache "
        "ALTER COLUMN id TYPE bigint, "
        "ALTER COLUMN ticker TYPE varchar(60), "
        "ALTER COLUMN open TYPE numeric(18,8), "
        "ALTER COLUMN high TYPE numeric(18,8), "
        "ALTER COLUMN low TYPE numeric(18,8), "
        "ALTER COLUMN close TYPE numeric(18,8)"
    )
    # Die Spalte allein genügt nicht: die Sequenz hat ihren eigenen Typ und
    # endete sonst weiter bei 2^31-1.
    op.execute("ALTER SEQUENCE IF EXISTS price_cache_id_seq AS bigint")


def downgrade() -> None:
    op.execute("DELETE FROM price_cache WHERE length(ticker) > 30")
    op.execute("ALTER SEQUENCE IF EXISTS price_cache_id_seq AS integer")
    op.execute(
        "ALTER TABLE price_cache "
        "ALTER COLUMN id TYPE integer, "
        "ALTER COLUMN ticker TYPE varchar(30), "
        "ALTER COLUMN open TYPE numeric(14,4), "
        "ALTER COLUMN high TYPE numeric(14,4), "
        "ALTER COLUMN low TYPE numeric(14,4), "
        "ALTER COLUMN close TYPE numeric(14,4)"
    )
