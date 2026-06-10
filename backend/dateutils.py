"""Timezone-aware UTC datetime helper.

Replaces deprecated datetime.utcnow() with datetime.now(timezone.utc),
stripped to naive for backward compatibility with existing DB columns.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return current UTC time as naive datetime (for DB compatibility)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """Return current UTC time as AWARE datetime.

    Für Tabellen mit TIMESTAMPTZ-Spalten (z.B. ntfy_config): asyncpg liefert
    dort aware datetimes zurück — naive Defaults würden naive/aware mischen
    und jeden Python-Vergleich mit utcnow() zum TypeError machen.
    """
    return datetime.now(timezone.utc)
