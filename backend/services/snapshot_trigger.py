"""Background snapshot regeneration trigger.

Call trigger_snapshot_regen() after any operation that changes historical
portfolio data (position create/delete, transaction create/update/delete,
precious metal changes). The regeneration runs in the background and
does NOT block the API response.

Wer einen Regen im Vordergrund braucht (Antwort erst nach dem Lauf), nimmt
run_snapshot_regen(): derselbe Schutz gegen parallele Läufe, kein direkter
Aufruf von regenerate_snapshots().
"""

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from datetime import date

from db import async_session

logger = logging.getLogger(__name__)

# Starke Task-Referenzen (asyncio hält nur Weak-Refs — sonst kann der Task
# mid-Regen vom GC eingesammelt werden) + laufende User, damit zwei schnelle
# Trigger (Txn-Edit + Import) nicht konkurrierende Regens starten, die am
# uq_bucket_snapshot kollidieren (Review 2026-07-02, LOW-snapshot-trigger).
#
# Die Sets gelten je Prozess. Über Prozesse hinweg (zwei uvicorn-Worker, dazu
# der Worker-Prozess) reiht die Sperre in snapshot_service die Läufe ein.
_pending_tasks: set[asyncio.Task] = set()
_running_users: set[uuid.UUID] = set()
_rerun_users: set[uuid.UUID] = set()
_today_running: set[uuid.UUID] = set()
_today_rerun: set[uuid.UUID] = set()


def _spawn(coro: Coroutine) -> None:
    task = asyncio.create_task(coro)
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


def trigger_snapshot_regen(user_id: uuid.UUID, from_date: date | None = None) -> None:
    """Fire-and-forget background snapshot regeneration.

    Args:
        user_id: User whose snapshots need regeneration.
        from_date: Earliest date affected. None or a future date: skip. Today:
            rewrite today's snapshot only. Earlier: full regeneration.
    """
    if from_date is None:
        return
    today = date.today()
    if from_date > today:
        # Buchung mit Datum morgen (Nutzer östlich der Server-Zeitzone): der
        # Tageslauf jenes Tages erfasst Wert und Cashflow gemeinsam.
        return
    if from_date == today:
        # Kein Regen nötig, aber der heutige Snapshot ist meist schon
        # geschrieben und kennt den Cashflow dieser Buchung nicht (K001).
        _trigger_today_snapshot(user_id)
        return

    if user_id in _running_users:
        # Läuft bereits — nach Abschluss einmal neu laufen lassen, damit die
        # Änderung, die diesen Trigger ausgelöst hat, nicht verloren geht.
        _rerun_users.add(user_id)
        return

    _running_users.add(user_id)
    _spawn(_regen_safe(user_id))


async def run_snapshot_regen(user_id: uuid.UUID) -> dict | None:
    """Regeneriert die Snapshots eines Nutzers und wartet auf das Ergebnis.

    Returns:
        Ergebnis von regenerate_snapshots, oder None, wenn für den Nutzer schon
        ein Regen läuft (in diesem oder einem anderen Prozess).
    """
    if user_id in _running_users:
        return None
    _running_users.add(user_id)
    try:
        from services.snapshot_service import SnapshotLockBusy, regenerate_snapshots
        async with async_session() as db:
            try:
                return await regenerate_snapshots(db, user_id, wait_for_lock=False)
            except SnapshotLockBusy:
                return None
    finally:
        _finish_regen(user_id)


def _finish_regen(user_id: uuid.UUID) -> None:
    _running_users.discard(user_id)
    if user_id in _rerun_users:
        _rerun_users.discard(user_id)
        trigger_snapshot_regen(user_id, from_date=date.min)


async def _regen_safe(user_id: uuid.UUID) -> None:
    """Run regenerate_snapshots with its own DB session and error handling."""
    try:
        from services.snapshot_service import regenerate_snapshots
        async with async_session() as db:
            result = await regenerate_snapshots(db, user_id)
            if result.get("error"):
                logger.warning(f"Background snapshot regen for user {user_id} skipped: {result['error']}")
            else:
                logger.info(f"Background snapshot regen for user {user_id}: {result.get('snapshots_created', 0)} snapshots")
    except Exception:
        logger.warning(f"Background snapshot regen failed for user {user_id}", exc_info=True)
    finally:
        _finish_regen(user_id)


def _trigger_today_snapshot(user_id: uuid.UUID) -> None:
    if user_id in _today_running:
        # Der laufende Task hat das Ledger vielleicht schon gelesen.
        _today_rerun.add(user_id)
        return
    _today_running.add(user_id)
    _spawn(_today_snapshot_safe(user_id))


async def _today_snapshot_safe(user_id: uuid.UUID) -> None:
    """Rewrite today's snapshot with its own DB session and error handling."""
    try:
        from services.snapshot_service import refresh_today_snapshot
        await refresh_today_snapshot(user_id)
    except Exception:
        logger.warning(f"Today snapshot refresh failed for user {user_id}", exc_info=True)
    finally:
        _today_running.discard(user_id)
        if user_id in _today_rerun:
            _today_rerun.discard(user_id)
            _trigger_today_snapshot(user_id)
