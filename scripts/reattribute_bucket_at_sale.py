"""One-off-Wartung: ``bucket_id_at_sale`` historischer Verkäufe auf den
AKTUELLEN Bucket der Position nachziehen.

Hintergrund: Der realisierte Gewinn eines Verkaufs wird dem Bucket zugeordnet,
in dem die Position ZUM VERKAUFSZEITPUNKT lag (``bucket_id_at_sale``, Snapshot).
Wurden Positionen erst NACH ihren Verkäufen in Buckets (Core/Satellite/…)
organisiert — oder lagen sie beim Verkauf im Default-Bucket „Alle Positionen" —,
landet der Realized-Gewinn im Default statt im gewünschten Bucket. Dieses Skript
setzt ``bucket_id_at_sale = position.bucket_id`` für alle abweichenden Verkäufe,
sodass die per-Bucket-Realized-Rendite der HEUTIGEN Bucket-Zuordnung folgt.

SICHERHEIT:
  - DRY-RUN ist Default: ohne ``--apply`` wird NICHTS geschrieben, nur angezeigt.
  - Vorher IMMER ein Backup ziehen (siehe Befehle unten).
  - Reversibel über das Backup.

Ausführen (auf der VM, im Projekt-Root /opt/openfolio):
  # 0) Backup:
  docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
      | sudo tee /var/backups/openfolio/pre-reattr-$(date +%Y%m%d-%H%M).sql >/dev/null
  # 1) Vorschau (dry-run):
  docker compose exec -T backend python - < scripts/reattribute_bucket_at_sale.py
  # 2) Anwenden:
  docker compose exec -T backend python - --apply < scripts/reattribute_bucket_at_sale.py
"""
import asyncio
import sys
from collections import defaultdict

from sqlalchemy import select

from db import async_session
from models.bucket import Bucket
from models.position import Position
from models.transaction import Transaction

APPLY = "--apply" in sys.argv


async def main() -> None:
    async with async_session() as db:
        bnames = {b.id: b.name for b in (await db.execute(select(Bucket))).scalars().all()}
        # Alle Transaktionen mit Verkaufs-Bucket-Snapshot = die Realized-
        # attribuierenden Sells (bucket_id_at_sale wird nur bei Verkäufen gesetzt).
        txns = (await db.execute(
            select(Transaction).where(Transaction.bucket_id_at_sale.isnot(None))
        )).scalars().all()
        positions = {p.id: p for p in (await db.execute(select(Position))).scalars().all()}

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

        if not APPLY:
            print("\n[DRY-RUN] Nichts geändert. Zum Schreiben mit --apply erneut ausführen.")
            return

        for t, p, r in changes:
            t.bucket_id_at_sale = p.bucket_id
        await db.commit()
        print(f"\n[APPLY] {len(changes)} Transaktionen aktualisiert. Fertig.")


asyncio.run(main())
