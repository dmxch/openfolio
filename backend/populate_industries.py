"""One-shot script: fetch the latest TradingView industries snapshot and persist it.

Run inside the backend container:

    docker compose exec backend python -m populate_industries

Prints a one-line summary. Exits non-zero on failure.
"""
import asyncio
import logging
import sys

from db import async_session
from services.tradingview_industries_service import refresh_industries

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("populate_industries")


async def main() -> int:
    async with async_session() as db:
        try:
            summary = await refresh_industries(db)
        except Exception as exc:
            logger.exception("populate_industries failed: %s", exc)
            return 1
    print(f"persisted {summary['count']} industries @ {summary['scraped_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
