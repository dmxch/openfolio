"""One-off: Backfill daily close history (2y) for all active yahoo-tradeable positions.

Zweck: der DB-Fallback von ``_get_close_series`` (MA-/MRS-Analysen) traegt nur,
wenn genug Historie in ``price_cache`` liegt. Bestandspositionen, die vor dem
Backfill-Hook (2026-06-10) angelegt wurden, akkumulieren erst ab Anlage-Datum —
zu wenig fuer MRS (>= 14 Wochen) und die 200-DMA (Befund: TSM lieferte leeres
MRS, weil yfinance im Web-Prozess klemmte und der Fallback ~8 Wochen hatte).

Idempotent (on_conflict_do_nothing) — gefahrlos mehrfach ausfuehrbar.

Run (im Backend-Container, Projekt-Root des Containers ist /app):
    docker compose exec backend python -m scripts.backfill_price_history
"""

import asyncio
import logging

from sqlalchemy import select

from db import async_session
from models.position import AssetType, Position
from services.cache_service import _NON_YAHOO_TYPES, backfill_price_history

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backfill_price_history")


def collect_backfill_tickers(positions) -> list[str]:
    """Yahoo-Ticker der Positionen, dedupliziert in stabiler Reihenfolge.

    Krypto laeuft nur ueber CoinGecko und braucht keine Yahoo-Historie. Eine
    coingecko_id bei einem anderen Typ ist ein Altbestand: die Position laeuft
    ueber Yahoo und braucht die Kurshistorie.
    """
    tickers: list[str] = []
    for pos in positions:
        if pos.type in _NON_YAHOO_TYPES or pos.gold_org or pos.type == AssetType.crypto:
            continue
        tickers.append(pos.yfinance_ticker or pos.ticker)
    return list(dict.fromkeys(tickers))


async def main() -> None:
    async with async_session() as db:
        result = await db.execute(
            select(Position).where(
                Position.is_active == True,  # noqa: E712
                Position.shares > 0,
            )
        )
        positions = result.scalars().all()

        tickers = collect_backfill_tickers(positions)

        logger.info(f"Backfilling {len(tickers)} tickers: {', '.join(tickers)}")
        total_rows = 0
        for ticker in tickers:
            rows = await backfill_price_history(db, ticker)
            total_rows += rows
            # Yahoo nicht hammern — kleine Pause zwischen Downloads
            await asyncio.sleep(1.5)

        logger.info(f"Done. {total_rows} rows written across {len(tickers)} tickers.")


if __name__ == "__main__":
    asyncio.run(main())
