"""Umschlüsselung: Felder, die nur der öffentliche Null-Schlüssel öffnet.

Hintergrund
-----------
Der Entschlüsselungsring leitet einen Legacy-Schlüssel aus
``LEGACY_ENCRYPTION_KEY`` ab. War die Variable leer, ergab das 32 Nullen: einen
öffentlich bekannten Schlüssel. Wer in eine verschlüsselte Spalte schreiben
kann, erzeugt damit gültige Chiffrate (Vollreview vom 13.11.2026, K152). Der
Schlüssel bleibt zum Lesen im Ring, bis ``LEGACY_NULL_KEY_ENABLED=false`` gesetzt
ist. Vorher darf kein Wert mehr an ihm hängen, sonst ist er danach nicht mehr
lesbar. Ob eine Instanz solche Werte hat, zeigt der Dry-Run.

Was das Skript tut
------------------
1. Es liest alle verschlüsselten Spalten (Liste ``ENCRYPTED_COLUMNS``).
2. Es zählt je Tabelle und Spalte die Werte, die nur der Null-Schlüssel öffnet.
   Zur Information zählt es auch die Werte an einem anderen Legacy-Schlüssel.
3. Mit ``--apply`` verschlüsselt es die Werte am Null-Schlüssel mit dem
   aktuellen ``ENCRYPTION_KEY`` neu. Werte am aktuellen Schlüssel, an einem
   anderen Legacy-Schlüssel und Klartext-Altwerte bleiben unverändert.

Das Skript gibt weder Klartext noch Chiffrat aus. Es ist idempotent: ein
zweiter Lauf findet keine Werte am Null-Schlüssel mehr. Es arbeitet auch, wenn
``LEGACY_NULL_KEY_ENABLED`` schon auf false steht.

Ablauf für den Betreiber
------------------------
1. Dry-Run ausführen und die Zahlen lesen.
2. Mit ``--apply`` umschlüsseln.
3. Dry-Run wiederholen. Er muss 0 Werte am Null-Schlüssel melden.
4. ``LEGACY_NULL_KEY_ENABLED=false`` in ``.env`` setzen.
5. Backend und Worker neu starten.

Aufruf (via docker compose, auf dem Ziel-Host):
  docker compose exec backend python scripts/vr11_reencrypt_legacy_fields.py          # Dry-Run (Default)
  docker compose exec backend python scripts/vr11_reencrypt_legacy_fields.py --apply  # verschlüsselt neu
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Skript laeuft aus /app im Container — Backend-Source liegt direkt da
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect as sa_inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.ntfy_config import NtfyConfig
from models.pending_order import PendingOrder
from models.position import Position
from models.precious_metal_item import PreciousMetalItem
from models.private_equity import (
    PrivateEquityDividend,
    PrivateEquityHolding,
    PrivateEquityValuation,
)
from models.property import Mortgage, Property, PropertyIncome
from models.smtp_config import SmtpConfig
from models.transaction import Transaction
from models.user import User, UserSettings
from models.watchlist import WatchlistItem
from services.auth_service import KEY_LEGACY, KEY_NULL, decrypt_with_key_kind, encrypt_value

# Jede Spalte, die encrypt_field, encrypt_value oder encrypt_totp_secret
# beschreibt (Stand 13.11.2026, aus den Aufrufstellen erhoben). Wer eine
# verschlüsselte Spalte ergänzt, trägt sie hier nach.
ENCRYPTED_COLUMNS: list[tuple[type, tuple[str, ...]]] = [
    (User, ("totp_secret",)),
    (UserSettings, ("fred_api_key", "fmp_api_key", "finnhub_api_key")),
    (SmtpConfig, ("password_encrypted",)),
    (NtfyConfig, ("access_token_encrypted",)),
    (Position, ("notes", "bank_name", "iban")),
    (Transaction, ("notes",)),
    (WatchlistItem, ("notes",)),
    (PendingOrder, ("notes",)),
    (PreciousMetalItem, ("serial_number", "storage_location", "notes")),
    (PrivateEquityHolding, ("company_name", "uid_number", "register_nr", "notes")),
    (PrivateEquityValuation, ("notes",)),
    (PrivateEquityDividend, ("notes",)),
    (Property, ("name", "address", "notes")),
    (Mortgage, ("bank",)),
    (PropertyIncome, ("tenant",)),
]

_READ_CHUNK_ROWS = 1000


async def _scan_column(db: AsyncSession, model: type, column_name: str) -> tuple[dict, list[tuple]]:
    """Zählt die Werte einer Spalte je Schlüssel.

    Returns (Zähler, Liste aus (Primärschlüssel, altes Chiffrat, Klartext) für
    die Werte am Null-Schlüssel). Der Klartext verlässt den Prozess nicht.
    """
    column = getattr(model, column_name)
    pk_columns = list(sa_inspect(model).primary_key)
    counts = {"checked": 0, "null_key": 0, "legacy_key": 0}
    null_rows: list[tuple] = []

    stmt = (
        select(*pk_columns, column)
        .where(column.isnot(None), column != "")
        .execution_options(yield_per=_READ_CHUNK_ROWS)
    )
    result = await db.stream(stmt)
    async for row in result:
        value = row[-1]
        counts["checked"] += 1
        try:
            plain, kind = decrypt_with_key_kind(value, include_null_key=True)
        except ValueError:
            continue  # Klartext-Altwert oder fremder Schlüssel: nicht Sache dieses Skripts
        if kind == KEY_NULL:
            counts["null_key"] += 1
            null_rows.append((tuple(row[:-1]), value, plain))
        elif kind == KEY_LEGACY:
            counts["legacy_key"] += 1
    return counts, null_rows


async def reencrypt(db: AsyncSession, *, apply: bool) -> dict:
    """Zählt die Werte am Null-Schlüssel und verschlüsselt sie mit ``apply`` neu.

    Returns:
        {"applied": bool, "null_key_total": int, "columns": [
            {"table", "column", "checked", "null_key", "legacy_key", "reencrypted"}, ...]}
    """
    report: dict = {"applied": apply, "null_key_total": 0, "columns": []}

    for model, column_names in ENCRYPTED_COLUMNS:
        pk_columns = list(sa_inspect(model).primary_key)
        for column_name in column_names:
            column = getattr(model, column_name)
            counts, null_rows = await _scan_column(db, model, column_name)
            reencrypted = 0
            if apply:
                for pk_values, old_value, plain in null_rows:
                    # Nur ersetzen, wenn der Wert noch der gelesene ist: die
                    # Anwendung läuft weiter und kann ihn inzwischen geändert haben.
                    conditions = [pk == v for pk, v in zip(pk_columns, pk_values)]
                    res = await db.execute(
                        update(model)
                        .where(*conditions, column == old_value)
                        .values({column_name: encrypt_value(plain)})
                        .execution_options(synchronize_session=False)
                    )
                    reencrypted += res.rowcount or 0
            report["columns"].append({
                "table": model.__tablename__,
                "column": column_name,
                **counts,
                "reencrypted": reencrypted,
            })
            report["null_key_total"] += counts["null_key"]
        if apply:
            await db.commit()
    return report


def _print_report(report: dict) -> None:
    applied = report["applied"]
    print(f"{'Tabelle.Spalte':<46} {'geprüft':>9} {'Null-Schlüssel':>15} {'Legacy':>8} {'neu':>6}")
    for c in report["columns"]:
        name = f"{c['table']}.{c['column']}"
        print(f"{name:<46} {c['checked']:>9} {c['null_key']:>15} {c['legacy_key']:>8} {c['reencrypted']:>6}")

    total = report["null_key_total"]
    done = sum(c["reencrypted"] for c in report["columns"])
    legacy = sum(c["legacy_key"] for c in report["columns"])
    print()
    if total == 0:
        print("Kein Wert hängt am Null-Schlüssel.")
        print("LEGACY_NULL_KEY_ENABLED=false setzen, dann Backend und Worker neu starten.")
    elif applied:
        print(f"{done} von {total} Werten neu verschlüsselt.")
        if done < total:
            print("Der Rest hat sich während des Laufs geändert. Skript erneut ausführen.")
        else:
            print("Dry-Run wiederholen. Meldet er 0, LEGACY_NULL_KEY_ENABLED=false setzen.")
    else:
        print(f"{total} Werte öffnet nur der Null-Schlüssel.")
        print("Dry-Run — nichts geschrieben. Mit --apply ausführen.")
        print("LEGACY_NULL_KEY_ENABLED bis dahin NICHT auf false setzen.")
    if legacy:
        print(f"\nHinweis: {legacy} Werte hängen an einem anderen Legacy-Schlüssel. Das Skript ändert sie nicht.")


async def main(apply: bool) -> None:
    from db import async_session

    async with async_session() as db:
        report = await reencrypt(db, apply=apply)
    _print_report(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="schreibt (Default: Dry-Run)")
    args = parser.parse_args()
    asyncio.run(main(args.apply))
