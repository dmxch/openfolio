"""Composite-Scan Liveness/Health — aggregierte Metadaten ohne Ergebnis-Payload.

Fuer unauthentifizierte Monitore (uptime-kuma) gedacht: ein Single-Field-
Verdikt (`status`) plus per-Source- und per-Signal-Coverage. Macht eine
*stumme Signal-Pipeline* sichtbar (Source done, aber 0 Signale) — was
`/api/v1/screening/latest` nicht zeigt (das listet nur per-Source-Health).

Abgrenzung zu /api/v1/screening/latest:
- kein Auth (Liveness-Probe) vs. API-Token
- kein Results-Array (leichtgewichtig) vs. voller Payload
- per-Signal-Coverage zusaetzlich
"""
from __future__ import annotations

from collections import Counter

from dateutils import utcnow
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.screening import ScreeningResult, ScreeningScan

# Konsistent mit /api/v1/screening/latest (dort scan_stale-Warning bei >2 Tagen).
# Daily-Cron laeuft Mo–Fri; bei >2 bleibt eine Fr-Scan ueber das Wochenende
# "ok" und flaggt erst Mo frueh, bevor der Mo-Cron 09:30 frisch schreibt.
_STALE_DAYS = 2


async def get_composite_scan_health(db: AsyncSession) -> dict:
    """Liveness-/Health-Snapshot des letzten completed Composite-Scans.

    status-Verdikt (Prioritaet stale > degraded > ok):
    - "no_scan"  : noch kein abgeschlossener Scan
    - "stale"    : letzter Scan aelter als _STALE_DAYS Tage
    - "degraded" : mindestens eine Source mit status=error
    - "ok"       : sonst
    """
    scan = (
        await db.execute(
            select(ScreeningScan)
            .where(ScreeningScan.status == "completed")
            .order_by(desc(ScreeningScan.started_at))
            .limit(1)
        )
    ).scalar_one_or_none()

    if scan is None:
        return {
            "status": "no_scan",
            "scan_id": None,
            "scanned_at": None,
            "finished_at": None,
            "scan_age_hours": None,
            "scan_age_days": None,
            "result_count": 0,
            "sources": {"total": 0, "done": 0, "error": 0, "empty": 0},
            "source_detail": [],
            "signal_coverage": {},
            "warnings": ["no_completed_scan_yet"],
        }

    age = (utcnow() - scan.started_at) if scan.started_at else None
    scan_age_hours = round(age.total_seconds() / 3600, 1) if age is not None else None
    scan_age_days = age.days if age is not None else None

    # Per-Source-Health aus den Scan-Steps.
    steps = list(scan.steps or [])
    source_detail: list[dict] = []
    warnings: list[str] = []
    done = error = empty = 0
    for step in steps:
        source = step.get("source", "unknown")
        status = step.get("status", "unknown")
        count = step.get("count")
        source_detail.append(
            {"source": source, "label": step.get("label", source), "status": status, "count": count}
        )
        if status == "error":
            error += 1
            warnings.append(f"pipeline_error:{source}")
        elif status == "done":
            done += 1
            if count is None or count == 0:
                empty += 1
                warnings.append(f"pipeline_empty:{source}")

    # Per-Signal-Coverage: nur die signals-Spalte laden (kein voller Result-Payload).
    sig_rows = (
        await db.execute(
            select(ScreeningResult.signals).where(ScreeningResult.scan_id == scan.id)
        )
    ).scalars().all()
    coverage: Counter[str] = Counter()
    for sig in sig_rows:
        if isinstance(sig, dict):
            for key in sig:
                coverage[key] += 1
    signal_coverage = dict(sorted(coverage.items()))

    # Verdikt — stale schlaegt degraded (ein nicht laufender Scan ist gravierender
    # als eine einzelne kaputte Source).
    if scan_age_days is not None and scan_age_days > _STALE_DAYS:
        status_verdict = "stale"
        warnings.append(f"scan_stale:{scan_age_days}_days")
    elif error > 0:
        status_verdict = "degraded"
    else:
        status_verdict = "ok"

    return {
        "status": status_verdict,
        "scan_id": str(scan.id),
        "scanned_at": scan.started_at.isoformat() if scan.started_at else None,
        "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
        "scan_age_hours": scan_age_hours,
        "scan_age_days": scan_age_days,
        "result_count": scan.result_count or len(sig_rows),
        "sources": {"total": len(steps), "done": done, "error": error, "empty": empty},
        "source_detail": source_detail,
        "signal_coverage": signal_coverage,
        "warnings": warnings,
    }
