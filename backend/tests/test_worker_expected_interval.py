"""Frist der Job-Ueberwachung: Der laengste Abstand zwischen zwei Laeufen zaehlt.

Die Frist entsteht aus dem Trigger (worker._expected_interval_seconds). Massgebend
ist der laengste Abstand, nicht der zwischen den naechsten zwei Laeufen: Sonst
gilt ein Job vor seinem naechsten Lauf als ueberfaellig.
"""
from datetime import datetime, timezone

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

import worker

DAY = 86400.0
TZ = "Europe/Zurich"


def _at(monkeypatch, moment: datetime) -> None:
    monkeypatch.setattr(worker, "utcnow_aware", lambda: moment)


def test_interval_trigger_uses_its_fixed_interval():
    assert worker._expected_interval_seconds(IntervalTrigger(seconds=60)) == 60.0
    assert worker._expected_interval_seconds(IntervalTrigger(hours=1)) == 3600.0


def test_monthly_job_measured_in_january_covers_31_days(monkeypatch):
    # Am 1.1. gemessen liegen die naechsten zwei Laeufe 28 Tage auseinander
    # (1.2. bis 1.3.2027). Der Job vom 1.1. ist aber erst nach 31 Tagen faellig.
    _at(monkeypatch, datetime(2027, 1, 1, 1, 0, 30, tzinfo=timezone.utc))
    trigger = CronTrigger(day=1, hour=2, minute=0, timezone=TZ)
    assert worker._expected_interval_seconds(trigger) == pytest.approx(31 * DAY, abs=3600)


def test_weekday_job_covers_the_weekend_gap(monkeypatch):
    # Montag: Die naechsten zwei Laeufe liegen einen Tag auseinander. Ueber das
    # Wochenende sind es drei Tage.
    _at(monkeypatch, datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc))
    trigger = CronTrigger(day_of_week="mon-fri", hour=8, minute=0, timezone=TZ)
    assert worker._expected_interval_seconds(trigger) == pytest.approx(3 * DAY, abs=1)


def test_daily_job_stays_at_one_day(monkeypatch):
    _at(monkeypatch, datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc))
    trigger = CronTrigger(hour=7, minute=0, timezone=TZ)
    assert worker._expected_interval_seconds(trigger) == pytest.approx(DAY, abs=1)


def test_weekly_job_stays_at_seven_days(monkeypatch):
    _at(monkeypatch, datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc))
    trigger = CronTrigger(day_of_week="mon", hour=4, minute=30, timezone=TZ)
    assert worker._expected_interval_seconds(trigger) == pytest.approx(7 * DAY, abs=1)


def test_yearly_job_beyond_the_horizon_still_gets_its_gap(monkeypatch):
    _at(monkeypatch, datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc))
    trigger = CronTrigger(month=1, day=1, hour=2, minute=0, timezone=TZ)
    assert worker._expected_interval_seconds(trigger) == pytest.approx(365 * DAY, abs=DAY)


def test_one_shot_trigger_has_no_interval(monkeypatch):
    _at(monkeypatch, datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc))
    trigger = DateTrigger(run_date=datetime(2026, 12, 1, tzinfo=timezone.utc))
    assert worker._expected_interval_seconds(trigger) is None


def test_broken_trigger_yields_none():
    class Broken:
        def get_next_fire_time(self, previous, now):
            raise RuntimeError("boom")

    assert worker._expected_interval_seconds(Broken()) is None
