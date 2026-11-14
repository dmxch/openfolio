"""One-off-Wartung: ``bucket_id_at_sale`` historischer Verkäufe EINES Nutzers auf
den AKTUELLEN Bucket der Position nachziehen.

Hintergrund: Der realisierte Gewinn eines Verkaufs wird dem Bucket zugeordnet,
in dem die Position ZUM VERKAUFSZEITPUNKT lag (``bucket_id_at_sale``, Snapshot).
Wurden Positionen erst NACH ihren Verkäufen in Buckets (Core/Satellite/…)
organisiert — oder lagen sie beim Verkauf im Default-Bucket „Alle Positionen" —,
landet der Realized-Gewinn im Default statt im gewünschten Bucket. Dieses Skript
setzt ``bucket_id_at_sale = position.bucket_id`` für alle abweichenden Verkäufe
des Nutzers, sodass die per-Bucket-Realized-Rendite der HEUTIGEN Bucket-Zuordnung
folgt.

SICHERHEIT:
  - ``--user <email|id>`` ist Pflicht. Das Skript liest und schreibt nur Daten
    dieses Nutzers. Ohne die Angabe überschrieb es früher den Verkaufs-Snapshot
    aller Nutzer der Instanz.
  - DRY-RUN ist Default: ohne ``--apply`` wird NICHTS geschrieben, nur angezeigt.
  - Die alten Werte stehen vor dem Schreiben als CSV in der Ausgabe. Ausgabe
    aufbewahren: damit lässt sich jede Zeile einzeln zurücksetzen
    (``UPDATE transactions SET bucket_id_at_sale = <alt> WHERE id = <transaction_id>``).
  - Vorher trotzdem ein Backup ziehen (siehe Befehle unten).

Ausführen (auf der VM, im Projekt-Root /opt/openfolio):
  # 0) Backup:
  docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
      | sudo tee /var/backups/openfolio/pre-reattr-$(date +%Y%m%d-%H%M).sql >/dev/null
  # 1) Vorschau (dry-run):
  docker compose exec -T backend python - --user <email> < scripts/reattribute_bucket_at_sale.py
  # 2) Anwenden, Ausgabe mit den alten Werten sichern:
  docker compose exec -T backend python - --user <email> --apply \
      < scripts/reattribute_bucket_at_sale.py | tee reattr-$(date +%Y%m%d-%H%M).log
"""
import argparse
import asyncio
import csv
import sys
import uuid
from collections import defaultdict

from sqlalchemy import func, select

from db import async_session
from models.bucket import Bucket
from models.position import Position
from models.transaction import Transaction
from models.user import User

CSV_HEADER = [
    "transaction_id",
    "user_id",
    "position_id",
    "ticker",
    "date",
    "realized_pnl_chf",
    "bucket_id_at_sale_old",
    "bucket_id_at_sale_new",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Zieht bucket_id_at_sale der Verkäufe EINES Nutzers auf den heutigen Bucket nach."
    )
    parser.add_argument(
        "--user",
        required=True,
        metavar="EMAIL|ID",
        help="E-Mail oder ID des Nutzers. Nur seine Verkäufe werden gelesen und geändert.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Änderungen schreiben. Ohne diesen Schalter läuft nur die Vorschau.",
    )
    return parser.parse_args(argv)


async def resolve_user(db, ident: str) -> User | None:
    """Sucht den Nutzer über seine ID oder seine E-Mail (ohne Gross-/Kleinschreibung)."""
    ident = ident.strip()
    try:
        user_id = uuid.UUID(ident)
    except ValueError:
        result = await db.execute(select(User).where(func.lower(User.email) == ident.lower()))
    else:
        result = await db.execute(select(User).where(User.id == user_id))
    return result.scalars().first()


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    async with async_session() as db:
        user = await resolve_user(db, args.user)
        if user is None:
            print(f"Kein Nutzer {args.user!r} gefunden. Nichts geändert.", file=sys.stderr)
            return 1

        bnames = {
            b.id: b.name
            for b in (await db.execute(select(Bucket).where(Bucket.user_id == user.id))).scalars().all()
        }
        # Alle Transaktionen mit Verkaufs-Bucket-Snapshot = die Realized-
        # attribuierenden Sells (bucket_id_at_sale wird nur bei Verkäufen gesetzt).
        txns = (await db.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.bucket_id_at_sale.isnot(None),
            )
        )).scalars().all()
        positions = {
            p.id: p
            for p in (await db.execute(select(Position).where(Position.user_id == user.id))).scalars().all()
        }

        changes = []
        realized_before: dict = defaultdict(float)
        realized_after: dict = defaultdict(float)
        for t in txns:
            p = positions.get(t.position_id)
            r = float(t.realized_pnl_chf or 0)
            realized_before[t.bucket_id_at_sale] += r
            target = p.bucket_id if p else t.bucket_id_at_sale
            realized_after[target] += r
            if p and t.bucket_id_at_sale != p.bucket_id:
                changes.append((t, p, r))

        changes.sort(key=lambda x: x[0].date)
        print(f"Nutzer: {user.email} ({user.id})\n")
        print(f"{'Ticker':10s} {'Datum':12s} {'realized':>11s}  von -> nach")
        for t, p, r in changes:
            old = bnames.get(t.bucket_id_at_sale, str(t.bucket_id_at_sale))
            new = bnames.get(p.bucket_id, str(p.bucket_id))
            print(f"{p.ticker:10s} {t.date.isoformat():12s} {r:11.2f}  {old} -> {new}")

        print(f"\n{len(changes)} Verkäufe würden umgebucht.")
        print("\nRealized pro Bucket  (vorher -> nachher):")
        keys = sorted(set(realized_before) | set(realized_after),
                      key=lambda k: -realized_after.get(k, 0))
        for bid in keys:
            print(f"  {bnames.get(bid, str(bid)):18s} "
                  f"{realized_before.get(bid, 0):11.2f}  ->  {realized_after.get(bid, 0):11.2f}")

        # Alte Werte VOR dem Schreiben ausgeben: der Snapshot ist danach weg.
        print("\n--- CSV alte Werte: Anfang ---")
        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow(CSV_HEADER)
        for t, p, r in changes:
            writer.writerow([
                t.id, t.user_id, p.id, p.ticker, t.date.isoformat(), f"{r:.2f}",
                t.bucket_id_at_sale, p.bucket_id,
            ])
        print("--- CSV alte Werte: Ende ---")
        sys.stdout.flush()

        if not args.apply:
            print("\n[DRY-RUN] Nichts geändert. Zum Schreiben mit --apply erneut ausführen.")
            return 0

        for t, p, r in changes:
            t.bucket_id_at_sale = p.bucket_id
        await db.commit()
        print(f"\n[APPLY] {len(changes)} Transaktionen aktualisiert. Fertig.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
