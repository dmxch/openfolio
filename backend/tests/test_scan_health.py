"""Tests fuer /api/health/composite-scan + services.screening.scan_health.

Validiert:
- Verdikt-Logik: no_scan / ok / degraded / stale (Prioritaet stale > degraded)
- per-Source-Zaehlung (done/error/empty) aus steps
- per-Signal-Coverage aus den Result-signals
- pipeline_error/pipeline_empty/scan_stale-Warnings
- Endpoint ist unauthentifiziert erreichbar
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from models.screening import ScreeningResult, ScreeningScan

pytestmark = pytest.mark.asyncio


async def _make_scan(db, *, status="completed", age_hours=1.0, steps=None, results=None):
    started = datetime.utcnow() - timedelta(hours=age_hours)
    scan = ScreeningScan(
        status=status,
        started_at=started,
        finished_at=started + timedelta(minutes=20),
        result_count=len(results or []),
        steps=steps or [],
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)
    for r in results or []:
        db.add(ScreeningResult(
            scan_id=scan.id,
            ticker=r["ticker"],
            name=r.get("name", r["ticker"]),
            score=r.get("score", 5),
            score_display=r.get("score_display", 50),
            signals=r.get("signals", {}),
            sector_bonus=0,
        ))
    await db.commit()
    return scan


async def _get(client: AsyncClient) -> dict:
    res = await client.get("/api/health/composite-scan")
    assert res.status_code == 200
    return res.json()


async def test_no_scan_returns_no_scan(client: AsyncClient, db):
    body = await _get(client)
    assert body["status"] == "no_scan"
    assert body["scan_id"] is None
    assert body["result_count"] == 0
    assert body["warnings"] == ["no_completed_scan_yet"]


async def test_fresh_scan_ok_with_coverage(client: AsyncClient, db):
    await _make_scan(
        db,
        age_hours=2,
        steps=[
            {"source": "openinsider", "label": "OpenInsider", "status": "done", "count": 40},
            {"source": "sec_13f", "label": "SEC 13F", "status": "done", "count": 12},
        ],
        results=[
            {"ticker": "AAPL", "signals": {"insider_cluster": {}, "form4_cluster": {}}},
            {"ticker": "MSFT", "signals": {"insider_cluster": {}}},
            {"ticker": "NVDA", "signals": {"estimate_revision": {}}},
        ],
    )
    body = await _get(client)
    assert body["status"] == "ok"
    assert body["result_count"] == 3
    assert body["sources"] == {"total": 2, "done": 2, "error": 0, "empty": 0}
    assert body["signal_coverage"] == {
        "estimate_revision": 1,
        "form4_cluster": 1,
        "insider_cluster": 2,
    }
    assert body["warnings"] == []
    assert body["scan_age_hours"] is not None


async def test_source_error_is_degraded(client: AsyncClient, db):
    await _make_scan(
        db,
        age_hours=1,
        steps=[
            {"source": "openinsider", "status": "done", "count": 10},
            {"source": "six_ser", "status": "error", "count": None},
        ],
        results=[{"ticker": "AAPL", "signals": {"insider_cluster": {}}}],
    )
    body = await _get(client)
    assert body["status"] == "degraded"
    assert body["sources"]["error"] == 1
    assert "pipeline_error:six_ser" in body["warnings"]


async def test_empty_pipeline_warns_but_stays_ok(client: AsyncClient, db):
    await _make_scan(
        db,
        age_hours=1,
        steps=[
            {"source": "openinsider", "status": "done", "count": 10},
            {"source": "estimate_revision", "status": "done", "count": 0},
        ],
        results=[{"ticker": "AAPL", "signals": {"insider_cluster": {}}}],
    )
    body = await _get(client)
    assert body["status"] == "ok"
    assert body["sources"]["empty"] == 1
    assert "pipeline_empty:estimate_revision" in body["warnings"]


async def test_stale_scan_flagged(client: AsyncClient, db):
    await _make_scan(
        db,
        age_hours=24 * 4,  # 4 Tage alt
        steps=[{"source": "openinsider", "status": "done", "count": 10}],
        results=[{"ticker": "AAPL", "signals": {"insider_cluster": {}}}],
    )
    body = await _get(client)
    assert body["status"] == "stale"
    assert body["scan_age_days"] >= 3
    assert any(w.startswith("scan_stale:") for w in body["warnings"])


async def test_stale_beats_degraded(client: AsyncClient, db):
    """Ein staler Scan mit zusaetzlichem Source-Error meldet trotzdem 'stale'."""
    await _make_scan(
        db,
        age_hours=24 * 4,
        steps=[
            {"source": "openinsider", "status": "done", "count": 10},
            {"source": "six_ser", "status": "error", "count": None},
        ],
        results=[{"ticker": "AAPL", "signals": {"insider_cluster": {}}}],
    )
    body = await _get(client)
    assert body["status"] == "stale"
    # Source-Error-Warning bleibt trotzdem sichtbar.
    assert "pipeline_error:six_ser" in body["warnings"]


async def test_only_latest_completed_scan_counts(client: AsyncClient, db):
    """Aeltere completed + juengerer running werden ignoriert; nur letzter completed."""
    await _make_scan(db, age_hours=48, steps=[{"source": "x", "status": "done", "count": 1}],
                      results=[{"ticker": "OLD", "signals": {"a": {}}}])
    await _make_scan(db, age_hours=1, status="running",
                     steps=[{"source": "x", "status": "running"}])
    await _make_scan(db, age_hours=3, steps=[{"source": "x", "status": "done", "count": 2}],
                     results=[{"ticker": "NEW", "signals": {"insider_cluster": {}, "buyback": {}}}])
    body = await _get(client)
    assert body["status"] == "ok"
    assert body["result_count"] == 1
    assert body["signal_coverage"] == {"buyback": 1, "insider_cluster": 1}
