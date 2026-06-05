"""Backfill: geschlossene (0-Share) Positionen deaktivieren.

Hintergrund
-----------
`transaction_service._sync_active_state` setzt seit laengerem `is_active=False`,
sobald `shares <= 0` faellt (und leert den Stop-Loss-State, damit
rule_alert_service keine stop_proximity-Mails fuer geschlossene Positionen mehr
schickt). Legacy-Positionen, die VOR diesem Mechanismus auf 0 fielen — oder ueber
einen Nicht-Transaktions-Pfad (manueller Edit/Import) auf 0 gesetzt wurden —
blieben aber `is_active=True` haengen. Das ist kosmetische Daten-Hygiene (der
Price-Staleness-Guard ignoriert sie korrekt via shares>0), aber sie verwaessern
aktive-Positions-Listen und koennten Alert-Logik triggern.

WICHTIG: Cash / Vorsorge / Immobilien / Private-Equity haben per Design
`shares != 0` (sie nutzen `shares` als Betrag bzw. werden ueber cost_basis_chf
bewertet). `_sync_active_state` greift nur bei `shares <= 0`, also bleiben diese
Typen unberuehrt. Der Backfill wendet exakt dieselbe Regel an — keine eigene
Heuristik, damit Code und Daten konsistent bleiben.

Idempotent: ein zweiter Lauf findet 0 Kandidaten.

Aufruf (via docker compose, auf dem Ziel-Host):
  docker compose exec backend python scripts/deactivate_zero_share_positions.py          # Dry-Run (Default)
  docker compose exec backend python scripts/deactivate_zero_share_positions.py --apply   # schreibt
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Skript laeuft aus /app im Container — Backend-Source liegt direkt da
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from db import async_session
from models.position import Position
from services.transaction_service import _sync_active_state


async def main(apply: bool) -> None:
    async with async_session() as db:
        rows = (
            await db.execute(
                select(Position).where(
                    Position.is_active.is_(True),
                    (Position.shares.is_(None)) | (Position.shares <= 0),
                )
            )
        ).scalars().all()

        if not rows:
            print("Keine Kandidaten — DB ist sauber. (0 Positionen mit shares<=0 & is_active=True)")
            return

        print(f"{len(rows)} Position(en) mit shares<=0 & is_active=True gefunden:\n")
        for pos in rows:
            print(
                f"  {pos.ticker:<10} {str(pos.type):<28} shares={float(pos.shares or 0):>10.4f}  "
                f"user={pos.user_id}"
            )

        if not apply:
            print("\n[DRY-RUN] Nichts geschrieben. Mit --apply ausfuehren, um zu deaktivieren.")
            return

        for pos in rows:
            if pos.shares is None:
                pos.shares = 0  # _sync_active_state ruft float(pos.shares) — None waere ein Crash
            _sync_active_state(pos)  # is_active=False + Stop-Loss-State leeren
        await db.commit()
        print(f"\n[APPLIED] {len(rows)} Position(en) deaktiviert + Stop-Loss-State geleert.")


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    asyncio.run(main(apply))
