"""Test: daily_refresh nimmt den Tages-Snapshot AUCH bei Kurs-Timeout auf.

Regression-Guard fuer den Bug, bei dem ein early `return` im TimeoutError-Handler
die Post-Tasks (v.a. _record_snapshot) uebersprang -> permanente, unsichtbare
Luecke in der Snapshot-/Performance-Historie.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

import worker


async def test_daily_refresh_records_snapshot_even_on_timeout(monkeypatch):
    # advisory_lock + async_session als No-op-Kontextmanager (Lock erhalten).
    @asynccontextmanager
    async def _fake_lock(lock_id):
        yield True

    @asynccontextmanager
    async def _fake_session():
        yield object()

    # refresh_cache laeuft in den Timeout.
    async def _timeout(*args, **kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(worker, "advisory_lock", _fake_lock)
    monkeypatch.setattr(worker, "async_session", _fake_session)
    monkeypatch.setattr(worker, "refresh_cache", _timeout)
    monkeypatch.setattr(worker, "_save_refresh_state_to_db", AsyncMock())

    import services.cache_service as cs
    monkeypatch.setattr(cs, "_load_refresh_state_from_db",
                        AsyncMock(return_value={"last_refresh": None}))

    # Post-Tasks als Stubs — wir pruefen, dass sie trotz Timeout laufen.
    macro = AsyncMock()
    earnings = AsyncMock()
    alerts = AsyncMock()
    snapshot = AsyncMock()
    monkeypatch.setattr(worker, "_refresh_macro_indicators", macro)
    monkeypatch.setattr(worker, "_refresh_earnings_dates", earnings)
    monkeypatch.setattr(worker, "_check_alerts", alerts)
    monkeypatch.setattr(worker, "_record_snapshot", snapshot)

    await worker.daily_refresh()

    # Kern-Assertion: der Tages-Snapshot wird trotz Timeout aufgenommen.
    snapshot.assert_awaited_once()
    # Die uebrigen Post-Tasks ebenfalls (fielen vorher mit dem early return weg).
    macro.assert_awaited_once()
    earnings.assert_awaited_once()
    alerts.assert_awaited_once()


async def test_daily_refresh_records_snapshot_on_success(monkeypatch):
    """Gegenprobe: auch im Erfolgsfall laeuft _record_snapshot."""
    @asynccontextmanager
    async def _fake_lock(lock_id):
        yield True

    @asynccontextmanager
    async def _fake_session():
        yield object()

    async def _ok(*args, **kwargs):
        return {"tickers_refreshed": 5}

    monkeypatch.setattr(worker, "advisory_lock", _fake_lock)
    monkeypatch.setattr(worker, "async_session", _fake_session)
    monkeypatch.setattr(worker, "refresh_cache", _ok)
    monkeypatch.setattr(worker, "_refresh_macro_indicators", AsyncMock())
    monkeypatch.setattr(worker, "_refresh_earnings_dates", AsyncMock())
    monkeypatch.setattr(worker, "_check_alerts", AsyncMock())
    snapshot = AsyncMock()
    monkeypatch.setattr(worker, "_record_snapshot", snapshot)

    await worker.daily_refresh()
    snapshot.assert_awaited_once()
