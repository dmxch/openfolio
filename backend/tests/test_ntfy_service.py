"""Tests for services/ntfy_service — fire-and-forget push, dedup, aggregation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services import ntfy_service
from services.ntfy_service import (
    AGGREGATION_THRESHOLD,
    _pending,
    send_push_aggregated,
    send_push_for_user,
    send_push_test,
)

pytestmark = pytest.mark.asyncio


def _make_cfg(*, is_enabled=True, token=None, user_id=None):
    """Build a fake NtfyConfig-like object."""
    return SimpleNamespace(
        user_id=user_id or uuid4(),
        server_url="https://ntfy.example.com",
        topic="openfolio-test-7K3xQ9verylongtopic",
        access_token_encrypted=token,
        is_enabled=is_enabled,
    )


class _FakeRedis:
    """In-memory fake of services/cache.get/set with the same kwargs."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple] = []

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None, **kwargs):
        self.store[key] = value
        self.set_calls.append((key, value, ttl))


@pytest.fixture(autouse=True)
def _drain_pending():
    """Make sure no leftover tasks from a previous test pollute _pending."""
    _pending.clear()
    yield
    # Cancel anything still pending so it doesn't bleed into the next test.
    for t in list(_pending):
        t.cancel()
    _pending.clear()


async def test_send_push_for_user_skipped_when_disabled():
    """is_enabled=False prevents any task spawn."""
    cfg = _make_cfg(is_enabled=False)
    redis = _FakeRedis()
    send_push_for_user(
        ntfy_cfg=cfg,
        category="price_alert",
        title="AAPL: Kurs ueber 200",
        message="...",
        severity="high",
        redis_client=redis,
    )
    assert len(_pending) == 0
    assert redis.set_calls == []


async def test_send_push_for_user_dedup_hit_skips_spawn():
    """Existing dedup key prevents task spawn and second SET."""
    cfg = _make_cfg()
    redis = _FakeRedis()
    redis.store[f"ntfy_dedup:{cfg.user_id}:price_alert:AAPL"] = "1"
    send_push_for_user(
        ntfy_cfg=cfg,
        category="price_alert",
        title="AAPL",
        message="...",
        severity="high",
        redis_client=redis,
    )
    assert len(_pending) == 0
    # No new SET after the dedup hit
    assert redis.set_calls == []


async def test_send_push_aggregated_below_threshold_sends_individuals():
    """2 alerts (< AGGREGATION_THRESHOLD=3) => 2 individual tasks spawned."""
    cfg = _make_cfg()
    redis = _FakeRedis()

    # Replace _send_push_inner so tasks resolve quickly without HTTP.
    async def _noop(**kwargs):
        return None

    with patch.object(ntfy_service, "_send_push_inner", _noop):
        send_push_aggregated(
            ntfy_cfg=cfg,
            category="price_alert",
            alerts=[
                {"title": "AAPL", "message": "m1", "severity": "high"},
                {"title": "MSFT", "message": "m2", "severity": "high"},
            ],
            redis_client=redis,
        )
        # 2 tasks scheduled
        assert len(_pending) == 2
        # Drain
        await asyncio.gather(*list(_pending))


async def test_send_push_aggregated_force_aggregate_with_single_alert():
    """force_aggregate=True bypasses threshold — 1 alert produces 1 aggregated push."""
    cfg = _make_cfg()
    redis = _FakeRedis()

    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    with patch.object(ntfy_service, "_send_push_inner", _capture):
        send_push_aggregated(
            ntfy_cfg=cfg,
            category="pending_dividend",
            alerts=[
                {"title": "Offene Dividende: MSFT", "message": "m", "severity": "info"},
            ],
            redis_client=redis,
            force_aggregate=True,
        )
        assert len(_pending) == 1
        await asyncio.gather(*list(_pending))

    assert captured["title"] == "1 ausstehende Dividenden ausgelöst"
    assert captured["message"] == "Offene Dividende: MSFT"
    assert captured["priority"] == 2  # info
    keys = [k for k, _, _ in redis.set_calls]
    assert any(
        k.startswith(f"ntfy_dedup_agg:{cfg.user_id}:pending_dividend:") for k in keys
    )


async def test_send_push_aggregated_at_threshold_sends_one_aggregated():
    """3 alerts => 1 aggregated push, title 'N Preis-Alarme ausgeloest'."""
    cfg = _make_cfg()
    redis = _FakeRedis()

    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    with patch.object(ntfy_service, "_send_push_inner", _capture):
        send_push_aggregated(
            ntfy_cfg=cfg,
            category="price_alert",
            alerts=[
                {"title": "AAPL", "message": "m1", "severity": "high"},
                {"title": "MSFT", "message": "m2", "severity": "high"},
                {"title": "TSLA", "message": "m3", "severity": "high"},
            ],
            redis_client=redis,
        )
        assert len(_pending) == 1
        await asyncio.gather(*list(_pending))

    # Aggregated title format: "3 Preis-Alarme ausgelöst"
    assert captured["title"] == "3 Preis-Alarme ausgelöst"
    # Body lists first 3 titles (no "+N weitere" since exactly 3)
    assert captured["message"] == "AAPL, MSFT, TSLA"
    assert captured["priority"] == 4  # high
    # Aggregat-Dedup wurde gesetzt
    keys = [k for k, _, _ in redis.set_calls]
    assert any(k.startswith(f"ntfy_dedup_agg:{cfg.user_id}:price_alert:") for k in keys)


async def test_send_push_aggregated_above_threshold_with_extras_in_title():
    """5 alerts => '5 ... ausgeloest' and body shows '+2 weitere'."""
    cfg = _make_cfg()
    redis = _FakeRedis()

    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    with patch.object(ntfy_service, "_send_push_inner", _capture):
        send_push_aggregated(
            ntfy_cfg=cfg,
            category="price_alert",
            alerts=[
                {"title": "AAPL", "message": "m", "severity": "high"},
                {"title": "MSFT", "message": "m", "severity": "high"},
                {"title": "TSLA", "message": "m", "severity": "high"},
                {"title": "NVDA", "message": "m", "severity": "high"},
                {"title": "AMD", "message": "m", "severity": "high"},
            ],
            redis_client=redis,
        )
        await asyncio.gather(*list(_pending))

    assert captured["title"] == "5 Preis-Alarme ausgelöst"
    assert captured["message"].endswith("+2 weitere")


async def test_send_push_aggregated_dedup_hit_skips_spawn():
    """Existing aggregat-dedup key prevents the aggregated push."""
    from datetime import date

    cfg = _make_cfg()
    redis = _FakeRedis()
    redis.store[
        f"ntfy_dedup_agg:{cfg.user_id}:price_alert:{date.today().isoformat()}"
    ] = "1"

    with patch.object(ntfy_service, "_send_push_inner", AsyncMock()):
        send_push_aggregated(
            ntfy_cfg=cfg,
            category="price_alert",
            alerts=[{"title": f"T{i}", "message": "m", "severity": "high"} for i in range(5)],
            redis_client=redis,
        )
    assert len(_pending) == 0


async def test_pending_set_strong_reference_drains_after_done():
    """Spawned task is added to _pending and removed after completion."""
    cfg = _make_cfg()

    async def _slow(**kwargs):
        await asyncio.sleep(0)

    with patch.object(ntfy_service, "_send_push_inner", _slow):
        send_push_for_user(
            ntfy_cfg=cfg,
            category="price_alert",
            title="AAPL",
            message="m",
            severity="high",
            redis_client=None,
        )
        assert len(_pending) == 1
        await asyncio.gather(*list(_pending))
    # add_done_callback is scheduled; give the loop a tick
    for _ in range(5):
        if not _pending:
            break
        await asyncio.sleep(0)
    assert len(_pending) == 0


async def test_send_push_inner_swallows_http_503():
    """HTTP 503 must not raise — it must only log."""
    import httpx

    class _Resp:
        status_code = 503

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "503", request=MagicMock(), response=MagicMock(status_code=503)
            )

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return _Resp()

    with patch.object(ntfy_service.httpx, "AsyncClient", _Client):
        # Should NOT raise
        await ntfy_service._send_push_inner(
            server_url="https://x",
            topic="t",
            title="T",
            message="m",
            access_token_encrypted=None,
            priority=3,
            tags=None,
        )


async def test_send_push_test_success_returns_ok():
    cfg = _make_cfg()

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return _Resp()

    with patch.object(ntfy_service.httpx, "AsyncClient", _Client):
        ok, msg = await send_push_test(cfg)
    assert ok is True
    assert msg == ""


async def test_send_push_test_403_returns_status_in_error():
    import httpx

    cfg = _make_cfg()

    class _Resp:
        status_code = 403
        reason_phrase = "Forbidden"

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "403", request=MagicMock(), response=self
            )

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return _Resp()

    with patch.object(ntfy_service.httpx, "AsyncClient", _Client):
        ok, msg = await send_push_test(cfg)
    assert ok is False
    assert "403" in msg


async def test_token_decrypt_called_when_set():
    """Encrypted token gets decrypted and used as Bearer header."""
    cfg = _make_cfg(token="ENCRYPTED_BLOB")

    captured_headers: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None, headers=None, **kwargs):
            captured_headers.update(headers or {})
            return _Resp()

    with patch.object(ntfy_service, "decrypt_value", return_value="plaintext-token"), \
         patch.object(ntfy_service.httpx, "AsyncClient", _Client):
        await ntfy_service._send_push_inner(
            server_url="https://x",
            topic="t",
            title="T",
            message="m",
            access_token_encrypted="ENCRYPTED_BLOB",
            priority=3,
            tags=None,
        )

    assert captured_headers.get("Authorization") == "Bearer plaintext-token"


async def test_multi_user_bucket_isolation_dedup_keys_differ():
    """Per-User-Dedup-Keys verwenden user_id — User A + User B kollidieren nicht."""
    cfg_a = _make_cfg(user_id=uuid4())
    cfg_b = _make_cfg(user_id=uuid4())
    redis = _FakeRedis()

    async def _noop(**kwargs):
        return None

    with patch.object(ntfy_service, "_send_push_inner", _noop):
        # Same title for both users — must result in TWO independent dedup keys
        send_push_for_user(
            ntfy_cfg=cfg_a,
            category="price_alert",
            title="AAPL",
            message="m",
            severity="high",
            redis_client=redis,
        )
        send_push_for_user(
            ntfy_cfg=cfg_b,
            category="price_alert",
            title="AAPL",
            message="m",
            severity="high",
            redis_client=redis,
        )
        await asyncio.gather(*list(_pending))

    keys = [k for k, _, _ in redis.set_calls]
    assert f"ntfy_dedup:{cfg_a.user_id}:price_alert:AAPL" in keys
    assert f"ntfy_dedup:{cfg_b.user_id}:price_alert:AAPL" in keys
    assert len(set(keys)) == 2  # disjoint
