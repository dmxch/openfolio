"""Liveness-/Health-Tracking fuer die APScheduler-Worker-Jobs.

Zwei Haelften:
  * **Pure Helfer** (``max_age_for_interval``, ``compute_stale``, ``is_stale_row``)
    — testbar ohne DB/Scheduler.
  * **DB-Ops** (``record_job_run``, ``get_all_health``) — Upsert pro job_id und
    Read fuer den Admin-Endpoint.

Der Worker leitet das erwartete Lauf-Intervall aus dem Trigger ab (kein
Duplizieren der Schedule-Definition) und persistiert ``max_age_s`` mit jeder
Zeile, damit der Backend-Prozess Staleness allein aus der DB berechnen kann.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dateutils import utcnow
from models.worker_job_health import WorkerJobHealth

logger = logging.getLogger(__name__)

# Ab so vielen aufeinanderfolgenden Fehlern gilt ein Job als "failing".
FAILURE_ALERT_THRESHOLD = 3


def max_age_for_interval(interval_s: float) -> int:
    """Erwartetes Max-Alter zwischen zwei Laeufen inkl. Toleranz.

    Grace = 25% des Intervalls, mind. 10 min, max. 24 h. So ist ein 60s-Job nach
    ~11 min stale, ein Daily nach ~30 h, ein Weekly nach ~8 Tagen — ohne pro Job
    von Hand gepflegte Schwellen.
    """
    grace = min(max(interval_s * 0.25, 600.0), 86400.0)
    return int(interval_s + grace)


def is_stale_row(row: dict[str, Any], now: datetime) -> bool:
    """True, wenn ein Health-Row (als dict) sein erwartetes Max-Alter ueberschritten hat."""
    max_age = row.get("max_age_s")
    last = row.get("last_run_at")
    if not max_age or last is None:
        return False
    return (now - last).total_seconds() > max_age


def compute_stale(
    rows: list[dict[str, Any]],
    now: datetime,
    worker_started_at: datetime | None = None,
    known_job_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Bestimmt stale/failing Jobs (pure).

    - stale: ``now - last_run_at > max_age_s``
    - failing: ``consecutive_failures >= FAILURE_ALERT_THRESHOLD``
    - never_ran: bekannter Job ohne Health-Zeile, obwohl der Worker laenger als
      eine grosszuegige Frist (1 h) laeuft — faengt einen Job, der nie startet.
    Gibt je Treffer ``{job_id, reason, age_s, max_age_s, consecutive_failures}``.
    """
    out: list[dict[str, Any]] = []
    by_id = {r["job_id"]: r for r in rows}
    for r in rows:
        cf = r.get("consecutive_failures") or 0
        if is_stale_row(r, now):
            last = r["last_run_at"]
            out.append({
                "job_id": r["job_id"], "reason": "stale",
                "age_s": (now - last).total_seconds(), "max_age_s": r.get("max_age_s"),
                "consecutive_failures": cf,
            })
        elif cf >= FAILURE_ALERT_THRESHOLD:
            out.append({
                "job_id": r["job_id"], "reason": "failing",
                "age_s": None, "max_age_s": r.get("max_age_s"),
                "consecutive_failures": cf,
            })
    if known_job_ids and worker_started_at is not None:
        up_for = (now - worker_started_at).total_seconds()
        if up_for > 3600:
            for jid in known_job_ids:
                if jid not in by_id:
                    out.append({
                        "job_id": jid, "reason": "never_ran",
                        "age_s": None, "max_age_s": None, "consecutive_failures": 0,
                    })
    return out


async def record_job_run(
    db: AsyncSession,
    job_id: str,
    status: str,
    *,
    runtime_ms: int | None = None,
    error: str | None = None,
    max_age_s: int | None = None,
) -> None:
    """Upsert einer Health-Zeile nach einem Job-Lauf.

    ``success`` setzt last_success_at und nullt consecutive_failures;
    ``error`` setzt last_error_at/last_error und erhoeht consecutive_failures;
    ``missed`` aktualisiert nur den Status (kein Fehler-Zaehler).
    """
    now = utcnow()
    res = await db.execute(select(WorkerJobHealth).where(WorkerJobHealth.job_id == job_id))
    row = res.scalars().first()
    if row is None:
        row = WorkerJobHealth(job_id=job_id, consecutive_failures=0)
        db.add(row)

    row.last_run_at = now
    row.last_status = status
    row.last_runtime_ms = runtime_ms
    if max_age_s is not None:
        row.max_age_s = max_age_s
    if status == "success":
        row.last_success_at = now
        row.consecutive_failures = 0
        row.last_error = None
    elif status == "error":
        row.last_error_at = now
        row.last_error = (error or "")[:2000]
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
    await db.commit()


def _row_to_dict(r: WorkerJobHealth) -> dict[str, Any]:
    return {
        "job_id": r.job_id,
        "last_run_at": r.last_run_at,
        "last_success_at": r.last_success_at,
        "last_error_at": r.last_error_at,
        "last_status": r.last_status,
        "last_error": r.last_error,
        "last_runtime_ms": r.last_runtime_ms,
        "max_age_s": r.max_age_s,
        "consecutive_failures": r.consecutive_failures or 0,
    }


async def get_all_health(db: AsyncSession) -> list[dict[str, Any]]:
    """Alle Health-Zeilen (raw dicts) — fuer den Admin-Endpoint."""
    res = await db.execute(select(WorkerJobHealth).order_by(WorkerJobHealth.job_id))
    return [_row_to_dict(r) for r in res.scalars().all()]
