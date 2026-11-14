"""Bereinigung: alte CoinGecko-Zeilen unter Anzeige-Tickern in price_cache.

Hintergrund
-----------
Bis zum Vollreview vom 13.11.2026 schrieb der Kurs-Refresh CoinGecko-Kurse unter
dem frei wählbaren Anzeige-Ticker der Position in ``price_cache`` (Quelle
``coingecko``, Währung CHF). Eine Position «AAPL» mit coingecko_id «bitcoin»
überschrieb so die AAPL-Zeile aller Nutzer. Seit dem Fix liegen Krypto-Kurse
unter ``CG:<coingecko_id>``. Die alten Zeilen bleiben bis zu 400 Tage liegen
und verfälschen bis dahin jeden Leser, der die Historie eines Tickers aus
``price_cache`` liest (gleitende Durchschnitte, Tagesveränderung).

Was das Skript tut
------------------
1. Es sucht Zeilen mit ``source = 'coingecko'``, deren Schlüssel nicht mit
   ``CG:`` beginnt.
2. Gehört zum Anzeige-Ticker genau eine coingecko_id (über alle Positionen),
   schlüsselt es die Zeilen auf ``CG:<coingecko_id>`` um. Existiert für ein
   Datum schon eine Zeile unter dem neuen Schlüssel, entfällt die alte.
3. Zeilen ohne eindeutige Zuordnung meldet es nur. ``--delete-unmapped``
   löscht sie.
4. Es meldet Positionen, die eine coingecko_id tragen, aber nicht vom Typ
   crypto sind. Ihr Kurs kommt seit dem Fix von Yahoo. Das Skript ändert sie
   nicht.

Idempotent: ein zweiter Lauf findet nur noch die nicht zuordenbaren Zeilen.
Erst nach dem Deploy des Fixes ausführen. Ein alter Worker schreibt sonst neue
Zeilen unter den Anzeige-Tickern.

Aufruf (via docker compose, auf dem Ziel-Host):
  docker compose exec backend python scripts/vr11_cleanup_crypto_price_cache.py                     # Dry-Run (Default)
  docker compose exec backend python scripts/vr11_cleanup_crypto_price_cache.py --apply             # schlüsselt um
  docker compose exec backend python scripts/vr11_cleanup_crypto_price_cache.py --apply --delete-unmapped
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

# Skript laeuft aus /app im Container — Backend-Source liegt direkt da
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position
from models.price_cache import PriceCache
from services.cache_service import (
    CRYPTO_PRICE_KEY_PREFIX,
    _PRICE_KEY_MAX_LEN,
    crypto_price_key,
    is_coingecko_id,
)


def _is_legacy_row():
    """Bedingung: CoinGecko-Zeile ausserhalb des CG:-Namensraums."""
    return (PriceCache.source == "coingecko") & PriceCache.ticker.notlike(f"{CRYPTO_PRICE_KEY_PREFIX}%")


async def cleanup(db: AsyncSession, apply: bool = False, delete_unmapped: bool = False) -> dict:
    """Meldet alte CoinGecko-Zeilen und schlüsselt sie bei ``apply`` um.

    Liefert einen Bericht: ``rekeyed`` und ``unmapped`` (je Ticker Zeilenzahl,
    Zeitraum und Ziel bzw. Grund) sowie ``non_crypto_positions``. Committet nur
    bei ``apply``.
    """
    legacy = (
        await db.execute(
            select(PriceCache.ticker, func.count(), func.min(PriceCache.date), func.max(PriceCache.date))
            .where(_is_legacy_row())
            .group_by(PriceCache.ticker)
            .order_by(PriceCache.ticker)
        )
    ).all()

    # Anzeige-Ticker -> coingecko_ids, über aktive und geschlossene Positionen:
    # die alten Zeilen können von einer inzwischen geschlossenen Position stammen.
    ids_by_ticker: dict[str, set[str]] = defaultdict(set)
    non_crypto: list[dict] = []
    positions = (
        await db.execute(
            select(Position.id, Position.ticker, Position.type, Position.coingecko_id, Position.is_active)
            .where(Position.coingecko_id.isnot(None), Position.coingecko_id != "")
        )
    ).all()
    for pos_id, ticker, pos_type, coingecko_id, is_active in positions:
        ids_by_ticker[ticker].add(coingecko_id)
        if pos_type != AssetType.crypto:
            non_crypto.append({
                "id": str(pos_id), "ticker": ticker, "type": pos_type.value,
                "coingecko_id": coingecko_id, "is_active": bool(is_active),
            })

    report: dict = {"rekeyed": [], "unmapped": [], "non_crypto_positions": non_crypto, "applied": apply}
    for ticker, count, first, last in legacy:
        entry = {"ticker": ticker, "rows": count, "from": first.isoformat(), "to": last.isoformat()}
        ids = ids_by_ticker.get(ticker, set())
        target = crypto_price_key(next(iter(ids))) if len(ids) == 1 else None
        if len(ids) != 1:
            entry["reason"] = "keine Position mit coingecko_id" if not ids else f"mehrere coingecko_ids: {sorted(ids)}"
        elif not is_coingecko_id(next(iter(ids))):
            entry["reason"] = f"ungültige coingecko_id: {next(iter(ids))!r}"
        elif len(target) > _PRICE_KEY_MAX_LEN:
            entry["reason"] = f"Schlüssel {target} länger als {_PRICE_KEY_MAX_LEN} Zeichen"
        if "reason" in entry:
            report["unmapped"].append(entry)
            if apply and delete_unmapped:
                await db.execute(delete(PriceCache).where(_is_legacy_row(), PriceCache.ticker == ticker))
            continue

        entry["target"] = target
        report["rekeyed"].append(entry)
        if apply:
            # (ticker, date) ist eindeutig: wo der neue Schlüssel schon einen
            # Kurs hat, entfällt die alte Zeile.
            taken = select(PriceCache.date).where(PriceCache.ticker == target)
            await db.execute(
                delete(PriceCache)
                .where(_is_legacy_row(), PriceCache.ticker == ticker, PriceCache.date.in_(taken))
                .execution_options(synchronize_session=False)
            )
            await db.execute(
                update(PriceCache)
                .where(_is_legacy_row(), PriceCache.ticker == ticker)
                .values(ticker=target)
                .execution_options(synchronize_session=False)
            )

    if apply:
        await db.commit()
    return report


def _print_report(report: dict, delete_unmapped: bool) -> None:
    applied = report["applied"]
    if not report["rekeyed"] and not report["unmapped"]:
        print("Keine alten CoinGecko-Zeilen unter Anzeige-Tickern gefunden.")
    if report["rekeyed"]:
        print(f"{'Umgeschlüsselt' if applied else 'Umzuschlüsseln'} ({len(report['rekeyed'])} Ticker):")
        for e in report["rekeyed"]:
            print(f"  {e['ticker']:<30} -> {e['target']:<30} {e['rows']:>5} Zeilen  {e['from']} bis {e['to']}")
    if report["unmapped"]:
        done = applied and delete_unmapped
        print(f"\nOhne eindeutige Zuordnung ({len(report['unmapped'])} Ticker) — {'gelöscht' if done else 'nicht verändert'}:")
        for e in report["unmapped"]:
            print(f"  {e['ticker']:<30} {e['rows']:>5} Zeilen  {e['from']} bis {e['to']}  ({e['reason']})")
        if not done:
            print("  Diese Zeilen tragen einen CHF-Krypto-Kurs unter einem fremden Ticker.")
            print("  Löschen mit: --apply --delete-unmapped")
    if report["non_crypto_positions"]:
        print(f"\nPositionen mit coingecko_id, aber nicht vom Typ crypto ({len(report['non_crypto_positions'])}):")
        for p in report["non_crypto_positions"]:
            state = "aktiv" if p["is_active"] else "geschlossen"
            print(f"  {p['id']}  {p['ticker']:<20} type={p['type']:<10} coingecko_id={p['coingecko_id']}  ({state})")
        print("  Ihr Kurs kommt seit dem Fix von Yahoo. Typ auf crypto stellen oder die ID leeren.")
    if not applied and (report["rekeyed"] or report["unmapped"]):
        print("\nDry-Run — nichts geschrieben. Mit --apply ausführen.")


async def main(apply: bool, delete_unmapped: bool) -> None:
    from db import async_session

    async with async_session() as db:
        report = await cleanup(db, apply=apply, delete_unmapped=delete_unmapped)
    _print_report(report, delete_unmapped)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="schreibt (Default: Dry-Run)")
    parser.add_argument(
        "--delete-unmapped", action="store_true",
        help="löscht mit --apply auch Zeilen ohne eindeutige Zuordnung",
    )
    args = parser.parse_args()
    asyncio.run(main(args.apply, args.delete_unmapped))
