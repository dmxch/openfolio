"""Worker-Job-Liveness: pure Staleness-Logik + DB-Round-Trip + Admin-Endpoint."""
from datetime import timedelta

import pytest

from dateutils import utcnow
from services.worker_health_service import (
    FAILURE_ALERT_THRESHOLD,
    compute_stale,
    get_all_health,
    is_stale_row,
    max_age_for_interval,
    record_job_run,
)

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


# --- Pure Helfer ---

def test_max_age_tiers():
    assert max_age_for_interval(60) == 660            # 60s-Job: +10min grace
    assert max_age_for_interval(86400) == 108000      # daily: +6h grace -> 30h
    assert max_age_for_interval(604800) == 691200     # weekly: +24h cap -> 8d


def test_is_stale_row():
    now = utcnow()
    assert is_stale_row({"max_age_s": 660, "last_run_at": now - timedelta(seconds=700)}, now) is True
    assert is_stale_row({"max_age_s": 660, "last_run_at": now - timedelta(seconds=100)}, now) is False
    assert is_stale_row({"max_age_s": None, "last_run_at": now - timedelta(days=5)}, now) is False
    assert is_stale_row({"max_age_s": 660, "last_run_at": None}, now) is False


def test_compute_stale_by_age():
    now = utcnow()
    rows = [{"job_id": "a", "max_age_s": 660, "last_run_at": now - timedelta(seconds=700), "consecutive_failures": 0}]
    res = compute_stale(rows, now)
    assert len(res) == 1 and res[0]["job_id"] == "a" and res[0]["reason"] == "stale"


def test_compute_stale_by_failures():
    now = utcnow()
    rows = [{"job_id": "b", "max_age_s": 108000, "last_run_at": now - timedelta(seconds=100),
             "consecutive_failures": FAILURE_ALERT_THRESHOLD}]
    res = compute_stale(rows, now)
    assert len(res) == 1 and res[0]["reason"] == "failing"


def test_compute_stale_never_ran():
    now = utcnow()
    res = compute_stale([], now, worker_started_at=now - timedelta(hours=2), known_job_ids=["c"])
    assert len(res) == 1 and res[0]["job_id"] == "c" and res[0]["reason"] == "never_ran"


def test_never_ran_waits_for_the_job_interval():
    """Ein Wochen-Job, der seit dem Start noch nie faellig war, ist kein Befund."""
    now = utcnow()
    weekly = 7 * 86400 + 86400
    kwargs = {"known_job_ids": ["weekly"], "known_job_max_age": {"weekly": weekly}}

    assert compute_stale([], now, worker_started_at=now - timedelta(days=5), **kwargs) == []

    res = compute_stale([], now, worker_started_at=now - timedelta(seconds=weekly + 1), **kwargs)
    assert [(r["job_id"], r["reason"], r["max_age_s"]) for r in res] == [("weekly", "never_ran", weekly)]


def test_never_ran_short_interval_keeps_minimum_uptime():
    """Ein Minuten-Job zaehlt erst nach der Mindestlaufzeit des Workers."""
    now = utcnow()
    kwargs = {"known_job_ids": ["fast"], "known_job_max_age": {"fast": 660}}

    assert compute_stale([], now, worker_started_at=now - timedelta(minutes=30), **kwargs) == []
    res = compute_stale([], now, worker_started_at=now - timedelta(hours=2), **kwargs)
    assert [r["reason"] for r in res] == ["never_ran"]


def test_never_ran_uses_row_max_age_for_missed_only_job():
    """Nur verpasste Laeufe: die Frist kommt aus der Health-Zeile."""
    now = utcnow()
    rows = [{"job_id": "m", "max_age_s": 108000, "last_run_at": None, "consecutive_failures": 0}]

    assert compute_stale(rows, now, worker_started_at=now - timedelta(hours=2), known_job_ids=["m"]) == []
    res = compute_stale(rows, now, worker_started_at=now - timedelta(hours=31), known_job_ids=["m"])
    assert [r["reason"] for r in res] == ["never_ran"]


def test_never_ran_falls_back_to_row_when_interval_unknown():
    """Kein Intervall aus dem Trigger ableitbar: die Frist der Health-Zeile gilt."""
    now = utcnow()
    rows = [{"job_id": "m", "max_age_s": 108000, "last_run_at": None, "consecutive_failures": 0}]
    kwargs = {"known_job_ids": ["m"], "known_job_max_age": {"m": None}}

    assert compute_stale(rows, now, worker_started_at=now - timedelta(hours=2), **kwargs) == []


def test_compute_stale_skips_fresh_worker():
    """Frisch gestarteter Worker -> ein nie gelaufener Job ist noch NICHT stale."""
    now = utcnow()
    res = compute_stale([], now, worker_started_at=now - timedelta(minutes=5), known_job_ids=["c"])
    assert res == []


# --- DB-Round-Trip ---

async def test_record_run_lifecycle(db):
    await record_job_run(db, "job_x", "success", runtime_ms=120, max_age_s=108000)
    rows = {r["job_id"]: r for r in await get_all_health(db)}
    assert rows["job_x"]["last_status"] == "success"
    assert rows["job_x"]["consecutive_failures"] == 0
    assert rows["job_x"]["last_success_at"] is not None

    # Zwei Fehler in Folge -> Zaehler steigt, last_error gesetzt.
    await record_job_run(db, "job_x", "error", error="boom", max_age_s=108000)
    await record_job_run(db, "job_x", "error", error="boom2", max_age_s=108000)
    rows = {r["job_id"]: r for r in await get_all_health(db)}
    assert rows["job_x"]["consecutive_failures"] == 2
    assert rows["job_x"]["last_error"] == "boom2"
    assert rows["job_x"]["last_status"] == "error"

    # Erfolg setzt zurueck.
    await record_job_run(db, "job_x", "success", max_age_s=108000)
    rows = {r["job_id"]: r for r in await get_all_health(db)}
    assert rows["job_x"]["consecutive_failures"] == 0
    assert rows["job_x"]["last_error"] is None


# --- Admin-Endpoint ---

async def _make_user(client, db, email, admin=False):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    jwt = (await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})).json()["access_token"]
    if admin:
        from sqlalchemy import update
        from models.user import User
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return jwt


async def test_worker_health_endpoint_admin(client, db):
    jwt = await _make_user(client, db, "wh-admin@test.local", admin=True)
    await record_job_run(db, "job_y", "success", runtime_ms=50, max_age_s=108000)
    res = await client.get("/api/admin/worker-health", headers={"Authorization": f"Bearer {jwt}"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["summary"]["total"] >= 1
    job_ids = [j["job_id"] for j in body["jobs"]]
    assert "job_y" in job_ids


async def test_worker_health_endpoint_forbidden_for_non_admin(client, db):
    jwt = await _make_user(client, db, "wh-user@test.local", admin=False)
    res = await client.get("/api/admin/worker-health", headers={"Authorization": f"Bearer {jwt}"})
    assert res.status_code == 403, res.text
