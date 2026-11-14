"""Vollreview 11/2026 — Stage-Anonymisierung (K106, K107, K120, X42).

Zwei Teile:

1. Die gepflegte Liste unten ordnet JEDE Text-Spalte des Schemas ein: geloescht,
   anonymisiert oder bewusst behalten. Eine neue Text-Spalte laesst
   ``test_every_text_column_is_classified`` scheitern, bis sie hier UND in
   ``scripts/anonymize_dump.sql`` eingeordnet ist. Dieser Teil braucht nur die
   Models und laeuft immer.
2. Die Pruefungen gegen ``scripts/anonymize_dump.sql`` selbst. Die Datei liegt
   ausserhalb von ``backend/``; im Test-Container sind sie nur sichtbar, wenn
   ``./scripts`` nach ``/scripts`` gemountet ist. Fehlt die Datei, werden diese
   Tests uebersprungen.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import ARRAY, JSON, Enum, LargeBinary, String, TypeDecorator

from models import Base

# Repo-Root: auf dem Host zwei Ebenen ueber tests/, im Container "/".
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SQL_PATH = _REPO_ROOT / "scripts" / "anonymize_dump.sql"

STAGE_PASSWORD = "stage123"

# ---------------------------------------------------------------------------
# Gepflegte Liste
# ---------------------------------------------------------------------------

# Tabellen, die das Skript vollstaendig leert (Sessions, Tokens, Audit, Codes).
DELETED_TABLES = {
    "refresh_tokens",
    "password_reset_tokens",
    "mfa_backup_codes",
    "api_tokens",
    "admin_audit_log",
    "api_write_log",
    "invite_codes",
}

# Spalten, die das Skript ueberschreibt (NULL oder Platzhalter).
ANONYMIZED: dict[str, set[str]] = {
    "users": {"email", "password_hash", "totp_secret"},
    "user_settings": {"fred_api_key", "fmp_api_key", "finnhub_api_key", "fire_assumptions"},
    "smtp_config": {"host", "username", "password_encrypted", "from_email", "provider"},
    "ntfy_config": {"server_url", "topic", "access_token_encrypted"},
    "properties": {"name", "address", "notes"},
    "mortgages": {"name", "bank", "notes"},
    "property_expenses": {"description"},
    "property_income": {"description", "tenant"},
    "private_equity_holdings": {"company_name", "uid_number", "register_nr", "notes"},
    "private_equity_valuations": {"notes", "source"},
    "private_equity_dividends": {"notes"},
    # positions.name: nur Cash, Vorsorge, Immobilien, Private Equity (frei gewaehlt).
    "positions": {"notes", "bank_name", "iban", "name"},
    "position_bucket_history": {"note"},
    # buckets.name: nur eigene Buckets (kind = 'user').
    "buckets": {"name", "description"},
    "transactions": {"notes", "order_id", "import_batch_id", "raw_symbol"},
    "fx_transactions": {"order_id", "import_batch_id"},
    "pending_dividends": {"notes"},
    "import_profiles": {"name"},
    "precious_metal_items": {"serial_number", "storage_location", "notes"},
    "precious_metal_expenses": {"description"},
    "watchlist": {"notes", "notes_last_api_token_name"},
    "watchlist_tags": {"name"},
    "pending_orders": {"notes", "notes_last_api_token_name"},
    "price_alerts": {"note"},
    "reports": {"title", "body", "tags", "source", "source_path", "content_hash"},
    "worker_job_health": {"last_error"},
    "screening_scans": {"error"},
}

_MARKET = "Markt- oder Stammdaten ohne Bezug zu einem Nutzer"
_CODE = "fester Wertevorrat, Waehrung oder technischer Code"
_TICKER = "Ticker oder Kennnummer eines Wertpapiers; daran haengen die Kursdaten"
_CONFIG = "Einstellung der Instanz oder der Oberflaeche, kein Freitext"

# Spalten, die bewusst bleiben. Der Wert nennt den Grund.
KEPT: dict[str, dict[str, str]] = {
    "alert_preferences": {"category": _CODE},
    "app_config": {"key": _CONFIG, "value": "SARON-Satz und Cache-Zustand"},
    "app_settings": {
        "key": _CONFIG,
        "value": "Instanz-Einstellungen; mfa_policy setzt das Skript auf off",
    },
    "bucket_alert_log": {"alert_type": _CODE},
    "buckets": {
        "color": _CONFIG,
        "benchmark": _TICKER,
        "risk_rules": "Zahlenregeln (Drawdown-Bremse), kein Freitext",
    },
    "eps_quarterly": {"ticker": _MARKET, "source": _MARKET},
    "estimate_revisions": {"ticker": _MARKET},
    "etf_holdings": {
        "etf_ticker": _MARKET,
        "holding_ticker": _MARKET,
        "holding_name": _MARKET,
        "holding_isin": _MARKET,
        "holding_country": _MARKET,
        "holding_sector": _MARKET,
    },
    "etf_sector_weights": {"ticker": _MARKET, "sector": _MARKET},
    "form4_transactions": {
        "ticker": _MARKET,
        "insider_name": "oeffentliche SEC-Meldung",
        "insider_role": "oeffentliche SEC-Meldung",
        "transaction_code": _MARKET,
    },
    "fund_holdings_snapshot": {"fund_cik": _MARKET, "fund_name": _MARKET, "ticker": _MARKET},
    "fx_transactions": {"currency_from": _CODE, "currency_to": _CODE},
    "import_bucket_rules": {"source": _CODE, "ticker_pattern": _TICKER},
    "import_profiles": {
        "delimiter": _CONFIG,
        "encoding": _CONFIG,
        "date_format": _CONFIG,
        "decimal_separator": _CONFIG,
        "column_mapping": "Spaltenkoepfe eines Broker-Exports",
        "type_mapping": "Spaltenkoepfe eines Broker-Exports",
    },
    "macro_cot_snapshots": {"instrument": _MARKET},
    "macro_indicator_cache": {"indicator": _MARKET, "status": _MARKET, "raw_data": _MARKET},
    "market_industries": {"slug": _MARKET, "name": _MARKET, "top1_ticker": _MARKET},
    "pending_dividends": {"currency": _CODE, "status": _CODE},
    "pending_orders": {
        "ticker": _TICKER,
        "side": _CODE,
        "currency": _CODE,
        "expiry_type": _CODE,
        "broker": "Name des Brokers aus einer Auswahlliste",
        "status": _CODE,
    },
    "position_bucket_history": {"changed_by": _CODE},
    "positions": {
        # Bei Cash und Vorsorge ist der Ticker ein frei gewaehlter Platzhalter. Er
        # bleibt trotzdem: die App erkennt Konten am Praefix CASH_, und der Ticker
        # ist Teil von uq_position_user_ticker_bucket_active.
        "ticker": _TICKER,
        "sector": _MARKET,
        "industry": _MARKET,
        "currency": _CODE,
        "yfinance_ticker": _TICKER,
        "coingecko_id": _TICKER,
        "isin": _TICKER,
        "stop_loss_method": _CODE,
        "risk_rules": "Zahlenregeln, kein Freitext",
    },
    "precious_metal_expenses": {"metal_type": _CODE},
    "precious_metal_items": {
        "metal_type": _CODE,
        "form": _CODE,
        "manufacturer": "Praegeanstalt, keine Angabe zur Person",
        "fineness": _CODE,
    },
    "price_alerts": {"ticker": _TICKER, "alert_type": _CODE, "currency": _CODE},
    "price_cache": {"ticker": _MARKET, "currency": _MARKET, "source": _MARKET},
    "private_equity_holdings": {"currency": _CODE},
    "properties": {"canton": "Kanton, zwei Buchstaben"},
    "reports": {"category": _CODE, "ticker": _TICKER, "side": _CODE},
    "screening_results": {
        "ticker": _MARKET,
        "name": _MARKET,
        "sector": _MARKET,
        "signals": _MARKET,
        "industry_name": _MARKET,
        "sector_momentum": _MARKET,
    },
    "screening_scans": {"status": _CODE, "steps": "technischer Fortschritt des Scans"},
    "signal_backtest_results": {"signal_key": _MARKET},
    "ticker_industries": {"ticker": _MARKET, "industry_name": _MARKET},
    "transactions": {"currency": _CODE, "isin": _TICKER, "import_source": _CODE},
    "user_settings": {
        "base_currency": _CODE,
        "broker": "Name des Brokers aus einer Auswahlliste",
        "default_stop_loss_method": _CODE,
        "number_format": _CONFIG,
        "date_format": _CONFIG,
        "onboarding_steps_json": "Stand der Einfuehrungstour",
    },
    "watchlist": {"ticker": _TICKER, "name": "Firmenname zum Ticker", "sector": _MARKET},
    "watchlist_tags": {"color": _CONFIG},
    "worker_job_health": {"job_id": _CODE, "last_status": _CODE},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_text_like(column) -> bool:
    """Spalten, die Freitext, Chiffrat oder JSON tragen koennen."""
    col_type = column.type
    if isinstance(col_type, TypeDecorator):
        col_type = col_type.impl_instance
    if isinstance(col_type, Enum):
        return False
    return isinstance(col_type, (String, JSON, ARRAY, LargeBinary))


def _schema_text_columns() -> set[tuple[str, str]]:
    return {
        (table.name, column.name)
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if _is_text_like(column)
    }


def _classified_columns() -> set[tuple[str, str]]:
    out = {(table, column) for table, columns in ANONYMIZED.items() for column in columns}
    out |= {(table, column) for table, columns in KEPT.items() for column in columns}
    return out


def _read_sql() -> str:
    if not _SQL_PATH.is_file():
        pytest.skip(f"{_SQL_PATH} nicht sichtbar (./scripts ist nicht in den Container gemountet)")
    return _SQL_PATH.read_text(encoding="utf-8")


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _sql_updates(sql: str) -> dict[str, set[str]]:
    """Tabelle -> Spalten, die ein UPDATE des Skripts setzt."""
    updates: dict[str, set[str]] = {}
    for statement in _strip_sql_comments(sql).split(";"):
        match = re.match(r"\s*UPDATE\s+(\w+)\s+SET\s+(.*)", statement, re.S | re.I)
        if not match:
            continue
        table, assignments = match.group(1), match.group(2)
        assignments = re.split(r"\bWHERE\b", assignments, maxsplit=1, flags=re.I)[0]
        columns = re.findall(r"(?:^|,)\s*(\w+)\s*=", assignments)
        updates.setdefault(table, set()).update(columns)
    return updates


# ---------------------------------------------------------------------------
# Teil 1 — gepflegte Liste gegen das Schema (K106)
# ---------------------------------------------------------------------------

def test_every_text_column_is_classified():
    schema = {(t, c) for t, c in _schema_text_columns() if t not in DELETED_TABLES}
    missing = sorted(schema - _classified_columns())
    assert not missing, (
        "Neue Text-Spalten ohne Einordnung fuer die Stage-Anonymisierung: "
        f"{missing}. Jede Spalte in ANONYMIZED (und in scripts/anonymize_dump.sql) "
        "oder mit Grund in KEPT eintragen."
    )


def test_classification_has_no_stale_entries():
    schema = _schema_text_columns()
    stale = sorted(_classified_columns() - schema)
    assert not stale, f"Eintraege ohne passende Text-Spalte im Schema: {stale}"

    tables = {table.name for table in Base.metadata.sorted_tables}
    assert DELETED_TABLES <= tables, sorted(DELETED_TABLES - tables)

    twice = sorted(
        (table, column)
        for table, columns in ANONYMIZED.items()
        for column in columns
        if column in KEPT.get(table, {})
    )
    assert not twice, f"Zugleich anonymisiert und behalten: {twice}"


def test_kept_columns_carry_a_reason():
    assert all(reason.strip() for columns in KEPT.values() for reason in columns.values())


# ---------------------------------------------------------------------------
# Teil 2 — das SQL-Skript selbst (K106, K107, K120, X42)
# ---------------------------------------------------------------------------

def test_sql_overwrites_every_anonymized_column():
    updates = _sql_updates(_read_sql())
    missing = sorted(
        (table, column)
        for table, columns in ANONYMIZED.items()
        for column in columns
        if column not in updates.get(table, set())
    )
    assert not missing, f"anonymize_dump.sql setzt diese Spalten nicht: {missing}"


def test_sql_empties_every_deleted_table():
    sql = _strip_sql_comments(_read_sql())
    missing = sorted(
        table for table in DELETED_TABLES
        if not re.search(rf"DELETE\s+FROM\s+{table}\s*;", sql, re.I)
    )
    assert not missing, f"anonymize_dump.sql leert diese Tabellen nicht: {missing}"


def test_sql_does_not_touch_unknown_columns():
    """Jede Spalte, die das Skript setzt, ist ein Feld des Schemas.

    Ein Tippfehler liesse die Transaktion scheitern; mit ON_ERROR_STOP bricht der
    Restore dann ab.
    """
    known = {
        (table.name, column.name)
        for table in Base.metadata.sorted_tables
        for column in table.columns
    }
    unknown = sorted(
        (table, column)
        for table, columns in _sql_updates(_read_sql()).items()
        for column in columns
        if (table, column) not in known
    )
    assert not unknown, f"anonymize_dump.sql setzt unbekannte Spalten: {unknown}"


def test_sql_password_hash_matches_documented_stage_password():
    from scripts.seed_loadtest import STAGE_PASSWORD_HASH
    from services.auth_service import verify_password

    hashes = set(re.findall(r"password_hash\s*=\s*'([^']+)'", _read_sql()))
    assert len(hashes) == 1, hashes
    sql_hash = hashes.pop()
    assert verify_password(STAGE_PASSWORD, sql_hash)
    # Lasttest-Konten und restaurierte Konten teilen dasselbe Stage-Passwort.
    assert sql_hash == STAGE_PASSWORD_HASH


def test_loadtest_password_hash_matches_stage_password():
    """Laeuft auch ohne gemountetes ./scripts (K120)."""
    from scripts.seed_loadtest import STAGE_PASSWORD_HASH
    from services.auth_service import verify_password

    assert verify_password(STAGE_PASSWORD, STAGE_PASSWORD_HASH)


def test_sql_gives_each_admin_a_unique_email():
    """K107: zwei Admins auf admin@example.test verletzten users_email_key."""
    sql = _strip_sql_comments(_read_sql())
    statements = [s.strip() for s in sql.split(";")]
    shared = [
        s for s in statements
        if re.search(r"SET\s+email\s*=\s*'admin@example\.test'", s, re.I)
        and re.search(r"WHERE\s+is_admin\s*=\s*true\s*$", s, re.I)
    ]
    assert not shared, "alle Admins erhalten dieselbe Adresse"
    assert re.search(r"'admin-'\s*\|\|\s*substring\(id::text", sql)
    # Genau ein Konto erhaelt die bekannte Adresse fuer den Smoke-Test.
    assert re.search(
        r"SET\s+email\s*=\s*'admin@example\.test'\s+WHERE\s+id\s*=\s*\(\s*SELECT\s+id\s+FROM\s+users"
        r".*?LIMIT\s+1\s*\)",
        sql,
        re.S | re.I,
    )


def test_sql_switches_mfa_enforcement_off():
    """X42: ohne das sperrt die Policy 'all' jedes Stage-Konto nach dem Login."""
    sql = _strip_sql_comments(_read_sql())
    assert re.search(r"mfa_required\s*=\s*false", sql, re.I)
    assert re.search(
        r"UPDATE\s+app_settings\s+SET\s+value\s*=\s*'off'\s+WHERE\s+key\s*=\s*'mfa_policy'", sql, re.I
    )


def test_sql_runs_in_one_transaction_and_documents_on_error_stop():
    raw = _read_sql()
    sql = _strip_sql_comments(raw)
    assert sql.count("BEGIN;") == 1 and sql.count("COMMIT;") == 1
    assert sql.index("BEGIN;") < sql.index("UPDATE users") < sql.index("COMMIT;")
    assert "ON_ERROR_STOP=1" in raw
