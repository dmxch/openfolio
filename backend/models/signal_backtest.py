"""Akkumulierte Per-Signal-Forward-Return-Historie (Multi-Regime-Validierung).

Der Forward-Return-Harness zeigte: das Composite-Smart-Money-Signal ist in EINEM
Regime (Apr–Jun 2026) anti-prädiktiv — aber Invariante #3 verbietet eine
Gewichts-Änderung ohne Multi-Regime-Backtest. Ein Worker-Job persistiert darum
monatlich die univariate present-vs-absent-Statistik je Einzelsignal/Fenster.
Über die Zeit entsteht so die Regime-Historie, die eine fundierte (oder eben
gar keine) Gewichts-Entscheidung erst erlaubt. Eine Zeile = ein Lauf × Signal ×
Fenster.
"""
import uuid
from datetime import date, datetime

from dateutils import utcnow
from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SignalBacktestResult(Base):
    __tablename__ = "signal_backtest_results"
    __table_args__ = (
        UniqueConstraint("run_date", "signal_key", "window_days", name="uq_signal_backtest_run"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    signal_key: Mapped[str] = mapped_column(String(32), nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    n_present: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_absent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mean_present: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_absent: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_present: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Lauf-Kontext (Regime-Fenster + Stichprobe), repliziert je Zeile fürs Lesen.
    n_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    earliest_scan: Mapped[date | None] = mapped_column(Date, nullable=True)
    latest_scan: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
