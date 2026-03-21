"""Background snapshot regeneration trigger.

Call trigger_snapshot_regen() after any operation that changes historical
portfolio data (position create/delete, transaction create/update/delete,
precious metal changes). The regeneration runs in the background and
does NOT block the API response.
"""

import asyncio
import logging
import uuid
from datetime import date

from db import async_session

logger = logging.getLogger(__name__)


def trigger_snapshot_regen(user_id: uuid.UUID, from_date: date | None = None) -> None:
    """Fire-and-forget background snapshot regeneration.

    Args:
        user_id: User whose snapshots need regeneration.
        from_date: Earliest date affected. If None or today, skip (no historical impact).
    """
    if from_date is None or from_date >= date.today():
        return  # No historical impact, daily snapshot will handle it

    asyncio.create_task(_regen_safe(user_id))


async def _regen_safe(user_id: uuid.UUID) -> None:
    """Run regenerate_snapshots with its own DB session and error handling."""
    try:
        from services.snapshot_service import regenerate_snapshots
        async with async_session() as db:
            result = await regenerate_snapshots(db, user_id)
            logger.info(f"Background snapshot regen for user {user_id}: {result.get('snapshots_created', 0)} snapshots")
    except Exception:
        logger.warning(f"Background snapshot regen failed for user {user_id}", exc_info=True)
