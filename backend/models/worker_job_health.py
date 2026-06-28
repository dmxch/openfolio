"""Heartbeat-/Health-Tabelle fuer die APScheduler-Worker-Jobs.

Der Worker laeuft als eigener Prozess (kein /metrics-Scrape). Damit ein Job,
der STILL nicht mehr feuert (Worker tot, Scheduler haengt, Cron entfernt),
nicht unbemerkt bleibt, schreibt ein APScheduler-Listener nach JEDEM Lauf eine
Zeile pro ``job_id``. ``max_age_s`` (aus dem Trigger abgeleitet) macht die
Staleness fuer den Backend-Prozess berechenbar, ohne die Schedule-Definition zu
duplizieren. Siehe feedback: Crons mit DB-Writes brauchen einen Liveness-Monitor.
"""
import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class WorkerJobHealth(Base):
    __tablename__ = "worker_job_health"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # success | error | missed
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_runtime_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Erwartetes Max-Alter zwischen zwei Laeufen (aus dem Trigger abgeleitet);
    # NULL = unbekannt -> keine Staleness-Bewertung.
    max_age_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
