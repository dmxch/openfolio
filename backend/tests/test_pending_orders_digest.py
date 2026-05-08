"""Tests fuer get_digest_buckets + Render-Reihenfolge der Digest-Sektionen."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from models.pending_order import PendingOrder
from models.user import User
from services import cache as app_cache
from services.pending_order_service import get_digest_buckets
from services.rule_alert_service import _render_digest_html

TEST_PASSWORD = "TestPassw0rd!2026"


async def _register(client, email):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


async def _get_user(db, email):
    return (await db.execute(select(User).where(User.email == email))).scalars().first()


def _seed_quote(ticker: str, price: float, currency: str = "USD"):
    """Memory-cache eine Quote, damit pending_order_service.get_digest_buckets sie findet."""
    app_cache.set(f"price:{ticker}", {"price": price, "currency": currency, "change_pct": 0})


def _clear_quote(ticker: str):
    try:
        app_cache.delete(f"price:{ticker}")
    except AttributeError:
        # Falls kein delete: dann setzen wir zurueck via set None
        app_cache.set(f"price:{ticker}", None)


def _add_order(db, user_id, ticker, side, limit_price, currency="USD", **extras):
    extras.setdefault("expiry_type", "gtc")
    o = PendingOrder(
        user_id=user_id,
        ticker=ticker,
        side=side,
        shares=1,
        limit_price=Decimal(str(limit_price)),
        currency=currency,
        status="open",
        **extras,
    )
    db.add(o)
    return o


@pytest.mark.asyncio
class TestDigestBuckets:
    async def test_near_bucket_within_threshold(self, client, db):
        await _register(client, "dg-near@example.com")
        user = await _get_user(db, "dg-near@example.com")
        # BUY @ 99 mit Spot 100 → distance = +0.01 (1%) → near (≤2%)
        _add_order(db, user.id, "NEAR1", "buy", 99)
        await db.commit()

        _seed_quote("NEAR1", 100.0, "USD")
        try:
            buckets = await get_digest_buckets(db, user.id, near_threshold=Decimal("0.02"))
        finally:
            _clear_quote("NEAR1")
        assert len(buckets["near"]) == 1
        assert buckets["near"][0]["ticker"] == "NEAR1"
        assert len(buckets["breached"]) == 0

    async def test_breached_bucket_negative_distance(self, client, db):
        await _register(client, "dg-br@example.com")
        user = await _get_user(db, "dg-br@example.com")
        # BUY @ 110 mit Spot 100 → distance = -0.1 (-10%) → breached
        _add_order(db, user.id, "BR1", "buy", 110)
        await db.commit()

        _seed_quote("BR1", 100.0, "USD")
        try:
            buckets = await get_digest_buckets(db, user.id)
        finally:
            _clear_quote("BR1")
        assert len(buckets["near"]) == 0
        assert len(buckets["breached"]) == 1
        assert buckets["breached"][0]["distance_pct"] < 0

    async def test_currency_mismatch_excluded_from_both_buckets(self, client, db):
        await _register(client, "dg-fx@example.com")
        user = await _get_user(db, "dg-fx@example.com")
        _add_order(db, user.id, "FX1", "buy", 99, currency="USD")
        await db.commit()

        _seed_quote("FX1", 100.0, "CHF")  # Mismatch
        try:
            buckets = await get_digest_buckets(db, user.id)
        finally:
            _clear_quote("FX1")
        assert len(buckets["near"]) == 0
        assert len(buckets["breached"]) == 0

    async def test_expired_excluded_from_both_buckets(self, client, db):
        await _register(client, "dg-exp@example.com")
        user = await _get_user(db, "dg-exp@example.com")
        # GTD-Order, abgelaufen
        _add_order(
            db, user.id, "EXP1", "buy", 99,
            expiry_type="gtd",
            expiry_date=date.today() - timedelta(days=2),
        )
        await db.commit()

        _seed_quote("EXP1", 100.0, "USD")
        try:
            buckets = await get_digest_buckets(db, user.id)
        finally:
            _clear_quote("EXP1")
        assert len(buckets["near"]) == 0
        assert len(buckets["breached"]) == 0

    async def test_far_from_limit_excluded(self, client, db):
        await _register(client, "dg-far@example.com")
        user = await _get_user(db, "dg-far@example.com")
        # BUY @ 80 mit Spot 100 → distance = +0.2 (20%) → too far
        _add_order(db, user.id, "FAR1", "buy", 80)
        await db.commit()

        _seed_quote("FAR1", 100.0, "USD")
        try:
            buckets = await get_digest_buckets(db, user.id, near_threshold=Decimal("0.02"))
        finally:
            _clear_quote("FAR1")
        assert len(buckets["near"]) == 0
        assert len(buckets["breached"]) == 0


class TestDigestRendering:
    def test_breached_section_renders_before_near(self):
        """Render-Reihenfolge: breached vor severity-groups, near danach.

        Hier: keine alerts uebergeben, nur die Buckets.
        """
        buckets = {
            "near": [{
                "ticker": "NEAR1",
                "side": "buy",
                "limit_price": 99.0,
                "current_price": 100.0,
                "currency": "USD",
                "distance_pct": 0.01,
                "broker": "IBKR",
            }],
            "breached": [{
                "ticker": "BR1",
                "side": "buy",
                "limit_price": 110.0,
                "current_price": 100.0,
                "currency": "USD",
                "distance_pct": -0.10,
                "broker": "IBKR",
            }],
        }
        html = _render_digest_html([], buckets)
        i_breached = html.find("Trigger durchbrochen")
        i_near = html.find("Offene Limit-Orders nahe am Trigger")
        assert i_breached >= 0
        assert i_near >= 0
        assert i_breached < i_near

    def test_no_buckets_renders_no_sections(self):
        html = _render_digest_html([], None)
        assert "Trigger durchbrochen" not in html
        assert "Offene Limit-Orders nahe am Trigger" not in html

    def test_only_near_renders_only_near_section(self):
        buckets = {
            "near": [{
                "ticker": "T1", "side": "buy", "limit_price": 1.0,
                "current_price": 1.005, "currency": "USD",
                "distance_pct": 0.005, "broker": None,
            }],
            "breached": [],
        }
        html = _render_digest_html([], buckets)
        assert "Trigger durchbrochen" not in html
        assert "Offene Limit-Orders nahe am Trigger" in html
