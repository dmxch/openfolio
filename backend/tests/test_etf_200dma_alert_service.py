"""Tests for services/etf_200dma_alert_service.py — Email + ntfy push integration.

Should-Scope (v0.36.0): verify push delivery follows the same pref-gating as
Email and never crosses user_id buckets.
"""

import pytest

from models.alert_preference import AlertPreference
from models.ntfy_config import NtfyConfig
from models.position import AssetType, Position
from models.user import User
from services import etf_200dma_alert_service
from services.etf_200dma_alert_service import check_etf_200dma_alerts

pytestmark = pytest.mark.asyncio


# --- Helpers ---------------------------------------------------------------


async def _make_user(db, email="harry@example.com"):
    u = User(email=email, password_hash="x", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _add_pref(
    db, user, *, is_enabled=True, notify_email=False, notify_push=False,
):
    p = AlertPreference(
        user_id=user.id,
        category="etf_200dma_buy",
        is_enabled=is_enabled,
        notify_email=notify_email,
        notify_push=notify_push,
    )
    db.add(p)
    await db.commit()
    return p


async def _add_position(db, user, ticker="VOO", shares=10):
    from services.bucket_service import get_liquid_default_bucket
    liquid = await get_liquid_default_bucket(db, user.id)
    p = Position(
        user_id=user.id,
        bucket_id=liquid.id,
        ticker=ticker,
        name=ticker,
        type=AssetType.etf,
        currency="USD",
        shares=shares,
        cost_basis_chf=1000,
        is_active=True,
    )
    db.add(p)
    await db.commit()
    return p


async def _add_ntfy(db, user_id):
    cfg = NtfyConfig(
        user_id=user_id,
        server_url="https://ntfy.example.com",
        topic="openfolio-test-7K3xQ9verylongtopic",
        is_enabled=True,
    )
    db.add(cfg)
    await db.commit()
    return cfg


class _FakeCache(dict):
    """Drop-in replacement for services.cache that records get/set calls."""

    def get(self, key):
        return super().get(key)

    def set(self, key, value, ttl=None):
        self[key] = value


@pytest.fixture
def fake_cache(monkeypatch):
    fc = _FakeCache()
    monkeypatch.setattr(etf_200dma_alert_service, "cache", fc)
    return fc


@pytest.fixture
def stub_ma_below(monkeypatch):
    """Stub compute_moving_averages to return current<ma200 (=> trigger)."""
    def _fake(ticker, mas):
        return {"current": 380.0, "ma200": 400.0}

    monkeypatch.setattr(etf_200dma_alert_service, "compute_moving_averages", _fake)
    return _fake


@pytest.fixture
def stub_ma_above(monkeypatch):
    """Stub compute_moving_averages so current>=ma200 (=> NO trigger)."""
    def _fake(ticker, mas):
        return {"current": 420.0, "ma200": 400.0}

    monkeypatch.setattr(etf_200dma_alert_service, "compute_moving_averages", _fake)
    return _fake


@pytest.fixture
def capture_email(monkeypatch):
    captured = {"calls": []}

    async def _send(to, subject, body_html, smtp_cfg=None):
        captured["calls"].append({"to": to, "subject": subject})
        return True

    monkeypatch.setattr(etf_200dma_alert_service, "send_email", _send)
    return captured


@pytest.fixture
def stub_push(monkeypatch):
    """Capture send_push_aggregated calls without spawning real tasks."""
    captured = {"calls": []}

    def _fake(*, ntfy_cfg, category, alerts, redis_client=None):
        captured["calls"].append({
            "user_id": ntfy_cfg.user_id,
            "category": category,
            "alerts": list(alerts),
        })

    monkeypatch.setattr(etf_200dma_alert_service, "send_push_aggregated", _fake)
    return captured


# --- Tests ------------------------------------------------------------------


class TestPushDelivery:
    async def test_push_sent_when_pref_enabled_and_notify_push_true(
        self, db, fake_cache, stub_ma_below, capture_email, stub_push,
    ):
        """notify_push=True + ntfy_cfg => send_push_aggregated wird gerufen mit category 'etf_200dma_buy'."""
        user = await _make_user(db)
        await _add_pref(db, user, notify_email=False, notify_push=True)
        await _add_position(db, user, ticker="VOO")
        await _add_ntfy(db, user.id)

        await check_etf_200dma_alerts(db)

        assert capture_email["calls"] == []  # notify_email=False
        assert len(stub_push["calls"]) == 1
        call = stub_push["calls"][0]
        assert call["user_id"] == user.id
        assert call["category"] == "etf_200dma_buy"
        assert len(call["alerts"]) == 1
        alert = call["alerts"][0]
        assert "VOO" in alert["title"]
        assert alert["severity"] == "medium"

    async def test_push_skipped_when_pref_missing(
        self, db, fake_cache, stub_ma_below, capture_email, stub_push,
    ):
        """Kein AlertPreference => weder Email noch Push."""
        user = await _make_user(db)
        await _add_position(db, user, ticker="VOO")
        await _add_ntfy(db, user.id)

        await check_etf_200dma_alerts(db)

        assert capture_email["calls"] == []
        assert stub_push["calls"] == []

    async def test_push_skipped_when_notify_push_false(
        self, db, fake_cache, stub_ma_below, capture_email, stub_push,
    ):
        """notify_email=True + notify_push=False => nur Email, kein Push."""
        user = await _make_user(db)
        await _add_pref(db, user, notify_email=True, notify_push=False)
        await _add_position(db, user, ticker="VOO")
        await _add_ntfy(db, user.id)

        await check_etf_200dma_alerts(db)

        assert len(capture_email["calls"]) == 1
        assert stub_push["calls"] == []

    async def test_push_skipped_when_pref_disabled(
        self, db, fake_cache, stub_ma_below, capture_email, stub_push,
    ):
        """is_enabled=False blockiert beide Kanaele auch wenn beide auf true sind."""
        user = await _make_user(db)
        await _add_pref(
            db, user, is_enabled=False, notify_email=True, notify_push=True,
        )
        await _add_position(db, user, ticker="VOO")
        await _add_ntfy(db, user.id)

        await check_etf_200dma_alerts(db)

        assert capture_email["calls"] == []
        assert stub_push["calls"] == []

    async def test_push_skipped_when_no_ntfy_config(
        self, db, fake_cache, stub_ma_below, capture_email, stub_push,
    ):
        """notify_push=True aber keine NtfyConfig => kein send_push_aggregated."""
        user = await _make_user(db)
        await _add_pref(db, user, notify_email=False, notify_push=True)
        await _add_position(db, user, ticker="VOO")
        # KEIN _add_ntfy

        await check_etf_200dma_alerts(db)
        assert stub_push["calls"] == []

    async def test_no_push_when_above_200dma(
        self, db, fake_cache, stub_ma_above, capture_email, stub_push,
    ):
        """Wenn current >= ma200, gibt es kein Trigger-Event und keinen Push."""
        user = await _make_user(db)
        await _add_pref(db, user, notify_email=True, notify_push=True)
        await _add_position(db, user, ticker="VOO")
        await _add_ntfy(db, user.id)

        await check_etf_200dma_alerts(db)
        assert capture_email["calls"] == []
        assert stub_push["calls"] == []

    async def test_email_dedup_blocks_recompute_but_push_still_works_first_run(
        self, db, fake_cache, stub_ma_below, capture_email, stub_push,
    ):
        """Beim ersten Run gehen sowohl Email als auch Push raus, der Email-Dedup-Key
        wird gesetzt — beim zweiten Run greift der Email-Dedup und der ETF wird
        gar nicht mehr neu berechnet (kein zweiter Push).
        """
        user = await _make_user(db)
        await _add_pref(db, user, notify_email=True, notify_push=True)
        await _add_position(db, user, ticker="VOO")
        await _add_ntfy(db, user.id)

        await check_etf_200dma_alerts(db)
        assert len(capture_email["calls"]) == 1
        assert len(stub_push["calls"]) == 1

        # Zweiter Run: Email-Dedup-Cache hat 'etf_200dma_email:{user}:VOO'.
        await check_etf_200dma_alerts(db)
        assert len(capture_email["calls"]) == 1  # unchanged
        assert len(stub_push["calls"]) == 1


class TestMultiUserIsolation:
    async def test_user_a_alerts_never_land_in_user_b_bucket(
        self, db, fake_cache, stub_ma_below, capture_email, stub_push,
    ):
        """Multi-User-Scope: jeder User bekommt seine eigene Push-Liste."""
        user_a = await _make_user(db, email="a@example.com")
        user_b = await _make_user(db, email="b@example.com")

        await _add_pref(db, user_a, notify_email=False, notify_push=True)
        await _add_pref(db, user_b, notify_email=False, notify_push=True)
        await _add_position(db, user_a, ticker="VOO")
        await _add_position(db, user_b, ticker="VTI")
        await _add_ntfy(db, user_a.id)
        await _add_ntfy(db, user_b.id)

        await check_etf_200dma_alerts(db)

        assert len(stub_push["calls"]) == 2
        per_user = {c["user_id"]: c for c in stub_push["calls"]}
        assert user_a.id in per_user and user_b.id in per_user

        a_call = per_user[user_a.id]
        b_call = per_user[user_b.id]
        assert all("VOO" in a["title"] for a in a_call["alerts"])
        assert all("VTI" in a["title"] for a in b_call["alerts"])
