"""Tests for services/rule_alert_service.py — per-user rule-alert email digest."""

import uuid

import pytest

from models.alert_preference import AlertPreference
from models.user import User
from services import rule_alert_service
from services.rule_alert_service import (
    CATEGORY_TO_PREF,
    _render_digest_html,
    _send_rule_alert_digest,
    check_rule_alerts,
)

pytestmark = pytest.mark.asyncio


# --- Helpers ---------------------------------------------------------------

async def _make_user(db, email="harry@example.com"):
    u = User(email=email, password_hash="x", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _add_pref(db, user, category, *, notify_email=True, is_enabled=True):
    p = AlertPreference(
        user_id=user.id,
        category=category,
        is_enabled=is_enabled,
        notify_email=notify_email,
    )
    db.add(p)
    await db.commit()
    return p


class _FakeCache(dict):
    """Drop-in replacement for services.cache that records get/set calls."""

    def get(self, key):
        return super().get(key)

    def set(self, key, value, ttl=None):
        self[key] = value

    def delete(self, key):
        self.pop(key, None)


@pytest.fixture
def fake_cache(monkeypatch):
    """Replace the Redis-backed cache with an in-memory dict for the duration of a test."""
    fc = _FakeCache()
    monkeypatch.setattr(rule_alert_service, "cache", fc)
    return fc


@pytest.fixture
def stub_generate_alerts(monkeypatch):
    """Return a setter that stubs generate_alerts to yield a caller-controlled list."""
    calls = {"count": 0, "last_positions": None}

    def install(alerts):
        def _fake(positions, climate, user_prefs, watchlist_tickers=None):
            calls["count"] += 1
            calls["last_positions"] = positions
            return alerts

        monkeypatch.setattr(rule_alert_service, "generate_alerts", _fake)

    return install, calls


@pytest.fixture
def stub_portfolio(monkeypatch):
    """Stub get_portfolio_summary to return a single synthetic position."""
    calls = {"count": 0}

    async def _summary(db, user_id):
        calls["count"] += 1
        return {
            "positions": [
                {
                    "ticker": "LHX",
                    "name": "L3Harris Technologies",
                    "type": "stock",
                    "shares": 10,
                    "market_value_chf": 5000.0,
                    "current_price": 205.0,
                    "stop_loss_price": 200.0,
                    "position_type": "satellite",
                }
            ]
        }

    monkeypatch.setattr(rule_alert_service, "get_portfolio_summary", _summary)
    return calls


@pytest.fixture
def stub_no_positions(monkeypatch):
    async def _summary(db, user_id):
        return {"positions": []}

    monkeypatch.setattr(rule_alert_service, "get_portfolio_summary", _summary)


@pytest.fixture(autouse=True)
def stub_external_calls(monkeypatch):
    """Neutralise climate, watchlist-MA, and SMTP lookups for all tests."""
    monkeypatch.setattr(rule_alert_service, "get_market_climate", lambda: {})

    async def _empty_watchlist(db, user):
        return []

    monkeypatch.setattr(rule_alert_service, "_build_watchlist_tickers", _empty_watchlist)


@pytest.fixture
def capture_send(monkeypatch):
    """Stub send_email to record calls and return a configurable success flag."""
    captured = {"calls": [], "return_value": True}

    async def _send(to, subject, body_html, smtp_cfg=None):
        captured["calls"].append({"to": to, "subject": subject, "body_html": body_html})
        return captured["return_value"]

    monkeypatch.setattr(rule_alert_service, "send_email", _send)
    return captured


# --- Tests ------------------------------------------------------------------


class TestPreferenceFiltering:
    async def test_skips_user_without_email_prefs(
        self, db, fake_cache, stub_portfolio, capture_send, stub_generate_alerts
    ):
        """No AlertPreference row with notify_email=True -> early return before summary load."""
        install, gen_calls = stub_generate_alerts
        install([])
        user = await _make_user(db)
        await _add_pref(db, user, "stop_proximity", notify_email=False)

        await check_rule_alerts(db)

        assert capture_send["calls"] == []
        assert stub_portfolio["count"] == 0
        assert gen_calls["count"] == 0

    async def test_respects_notify_email_false_on_matching_category(
        self, db, fake_cache, stub_portfolio, capture_send, stub_generate_alerts
    ):
        """Alert emitted for a category whose pref has notify_email=False is dropped."""
        user = await _make_user(db)
        # One pref has notify_email=True so outer short-circuit passes; but the
        # alert's own category has notify_email=False.
        await _add_pref(db, user, "ma_critical", notify_email=True)
        await _add_pref(db, user, "stop_proximity", notify_email=False)

        install, _ = stub_generate_alerts
        install([
            {
                "category": "stop_proximity",
                "ticker": "LHX",
                "title": "t",
                "message": "m",
                "severity": "high",
            }
        ])

        await check_rule_alerts(db)
        assert capture_send["calls"] == []

    async def test_respects_is_enabled_false(
        self, db, fake_cache, stub_portfolio, capture_send, stub_generate_alerts
    ):
        """is_enabled=False blocks mail even when notify_email=True."""
        user = await _make_user(db)
        # Satisfy outer short-circuit with a second category that is fully enabled.
        await _add_pref(db, user, "ma_critical", notify_email=True)
        await _add_pref(db, user, "stop_proximity", notify_email=True, is_enabled=False)

        install, _ = stub_generate_alerts
        install([
            {
                "category": "stop_proximity",
                "ticker": "LHX",
                "title": "t",
                "message": "m",
                "severity": "high",
            }
        ])

        await check_rule_alerts(db)
        assert capture_send["calls"] == []

    async def test_category_without_pref_mapping_skipped(
        self, db, fake_cache, stub_portfolio, capture_send, stub_generate_alerts
    ):
        """Alerts whose raw category has no entry in CATEGORY_TO_PREF are ignored."""
        user = await _make_user(db)
        await _add_pref(db, user, "stop_proximity", notify_email=True)

        install, _ = stub_generate_alerts
        # currency_mismatch + data_quality intentionally omitted from CATEGORY_TO_PREF
        install([
            {
                "category": "currency_mismatch",
                "ticker": "XYZ",
                "title": "t",
                "message": "m",
                "severity": "critical",
            }
        ])

        await check_rule_alerts(db)
        assert capture_send["calls"] == []


class TestSendPath:
    async def test_stop_proximity_triggers_email(
        self, db, fake_cache, stub_portfolio, capture_send, stub_generate_alerts
    ):
        """Harry's case: stop_proximity on LHX with notify_email=True -> digest sent."""
        user = await _make_user(db)
        await _add_pref(db, user, "stop_proximity", notify_email=True)

        install, _ = stub_generate_alerts
        install([
            {
                "category": "stop_proximity",
                "ticker": "LHX",
                "title": "L3Harris: Kurs naehert sich dem Stop-Loss",
                "message": "LHX nur noch 2.1% ueber Stop",
                "severity": "high",
            }
        ])

        await check_rule_alerts(db)

        assert len(capture_send["calls"]) == 1
        call = capture_send["calls"][0]
        assert call["to"] == "harry@example.com"
        assert "LHX" in call["subject"]
        assert "ausgeloest" in call["subject"].lower() or "ausgelöst" in call["subject"].lower()
        assert "LHX" in call["body_html"]

    async def test_subject_truncates_ticker_list(
        self, db, fake_cache, stub_portfolio, capture_send, stub_generate_alerts
    ):
        """With 5 distinct tickers, subject shows first 3 + '+2'."""
        user = await _make_user(db)
        await _add_pref(db, user, "stop_proximity", notify_email=True)

        install, _ = stub_generate_alerts
        install([
            {
                "category": "stop_proximity",
                "ticker": t,
                "title": "t",
                "message": "m",
                "severity": "high",
            }
            for t in ("AAA", "BBB", "CCC", "DDD", "EEE")
        ])

        await check_rule_alerts(db)
        subj = capture_send["calls"][0]["subject"]
        assert "AAA" in subj and "BBB" in subj and "CCC" in subj
        assert "+2" in subj
        assert "DDD" not in subj and "EEE" not in subj


class TestDedupe:
    async def test_dedupe_blocks_second_run_within_24h(
        self, db, fake_cache, stub_portfolio, capture_send, stub_generate_alerts
    ):
        """Second call with same ticker+category finds cache hit and skips."""
        user = await _make_user(db)
        await _add_pref(db, user, "stop_proximity", notify_email=True)

        install, _ = stub_generate_alerts
        install([
            {
                "category": "stop_proximity",
                "ticker": "LHX",
                "title": "t",
                "message": "m",
                "severity": "high",
            }
        ])

        await check_rule_alerts(db)
        await check_rule_alerts(db)

        assert len(capture_send["calls"]) == 1

    async def test_dedupe_global_key_for_ticker_less_alerts(
        self, db, fake_cache, stub_portfolio, capture_send, stub_generate_alerts
    ):
        """VIX alert without ticker maps to a '_global'-suffixed cache key."""
        user = await _make_user(db)
        await _add_pref(db, user, "vix", notify_email=True)

        install, _ = stub_generate_alerts
        install([
            {
                "category": "vix",
                "title": "VIX bei 38 — RISK OFF",
                "message": "Marktumfeld kritisch",
                "severity": "critical",
            }
        ])

        await check_rule_alerts(db)
        assert any(k.endswith(":vix:_global") for k in fake_cache.keys())

    async def test_cache_not_set_when_send_fails(
        self, db, fake_cache, stub_portfolio, capture_send, stub_generate_alerts
    ):
        """send_email returning False must leave cache empty so retry is possible."""
        user = await _make_user(db)
        await _add_pref(db, user, "stop_proximity", notify_email=True)

        install, _ = stub_generate_alerts
        install([
            {
                "category": "stop_proximity",
                "ticker": "LHX",
                "title": "t",
                "message": "m",
                "severity": "high",
            }
        ])
        capture_send["return_value"] = False

        await check_rule_alerts(db)
        assert not any(k.startswith("rule_alert_email:") for k in fake_cache.keys())
        # Next run (flip to success) must re-trigger since cache was not set.
        capture_send["return_value"] = True
        await check_rule_alerts(db)
        assert len(capture_send["calls"]) == 2


class TestRobustness:
    async def test_empty_positions_early_return(
        self, db, fake_cache, stub_no_positions, capture_send, stub_generate_alerts
    ):
        """User with no positions skips generate_alerts and mail entirely."""
        install, gen_calls = stub_generate_alerts
        install([])
        user = await _make_user(db)
        await _add_pref(db, user, "stop_proximity", notify_email=True)

        await check_rule_alerts(db)
        assert gen_calls["count"] == 0
        assert capture_send["calls"] == []

    async def test_exception_in_generate_alerts_does_not_break_loop(
        self, db, fake_cache, stub_portfolio, capture_send, monkeypatch
    ):
        """If generate_alerts raises for user A, user B must still be processed."""
        user_a = await _make_user(db, email="a@example.com")
        user_b = await _make_user(db, email="b@example.com")
        await _add_pref(db, user_a, "stop_proximity", notify_email=True)
        await _add_pref(db, user_b, "stop_proximity", notify_email=True)

        call_order: list[str] = []

        def _fake(positions, climate, user_prefs, watchlist_tickers=None):
            # Route by email so we know which user is being processed via
            # the captured send calls (order of users is insertion order).
            call_order.append("generate")
            if len(call_order) == 1:
                raise RuntimeError("boom")
            return [
                {
                    "category": "stop_proximity",
                    "ticker": "LHX",
                    "title": "t",
                    "message": "m",
                    "severity": "high",
                }
            ]

        monkeypatch.setattr(rule_alert_service, "generate_alerts", _fake)

        await check_rule_alerts(db)

        # Exactly one email went out — to the user whose generate_alerts
        # did not raise. The other user's exception was swallowed.
        assert len(capture_send["calls"]) == 1


class TestMapping:
    async def test_category_to_pref_is_synced_with_main_map(self):
        """Guard against drift between the UI endpoint map and this service."""
        # These keys are the raw categories emitted by alert_service.generate_alerts.
        # Any new category emitted there should be added here AND in main.py's CATEGORY_MAP.
        expected = {
            "stop_loss_missing", "stop_loss_unconfirmed",
            "stop_proximity", "stop_reached",
            "stop_loss_review", "stop_loss_age",
            "ma_critical", "ma_warning",
            "position_limit", "sector_limit", "loss",
            "market", "vix", "earnings",
            "allocation_satellite", "allocation_core",
            "position_type_missing", "etf_200dma_buy",
        }
        assert set(CATEGORY_TO_PREF.keys()) == expected


class TestDigestRendering:
    async def test_html_groups_by_severity(self):
        html = _render_digest_html([
            {"category": "stop_proximity", "ticker": "LHX",
             "title": "T1", "message": "M1", "severity": "high"},
            {"category": "vix", "title": "T2", "message": "M2", "severity": "critical"},
        ])
        # Critical section must come before High section in output order.
        assert html.index("Kritisch") < html.index("Hoch")
        assert "LHX" in html and "T1" in html and "T2" in html

    async def test_send_digest_subject_format(self, monkeypatch, fake_cache):
        captured = {}

        async def _send(to, subject, body_html, smtp_cfg=None):
            captured["subject"] = subject
            captured["to"] = to
            return True

        monkeypatch.setattr(rule_alert_service, "send_email", _send)
        u = User(id=uuid.uuid4(), email="x@example.com", password_hash="x")

        await _send_rule_alert_digest(
            u,
            [{"category": "stop_proximity", "ticker": "LHX",
              "title": "t", "message": "m", "severity": "high",
              "_pref_cat": "stop_proximity", "_dedup_key": "k"}],
            None,
        )
        assert "LHX" in captured["subject"]
        assert captured["to"] == "x@example.com"
