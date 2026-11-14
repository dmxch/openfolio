"""Regressionstests zum Vollreview 11/2026, Fixer «alerts».

K035  Preis-Alarm-Mail geht an den Nutzer, nicht an ALERT_EMAIL_TO
K077  SMTP-Versand mit Gesamt-Timeout und Backoff nach einem Fehler
X09   Kurs-Schlüssel folgt der Position (yfinance-Override, Krypto, Edelmetall)
K114  expires_at wird ausgewertet
K132  Kurse je Lauf in einem MGET statt eines GET je Alarm
K102  Breakout-Mail escapt Ticker, Name und Quelle
K153  Staleness-Mail escapt Ticker
K172  Stale-Check-Mail escapt Industry-Namen
K047  Regel-Digest: gültige Severity und Restgruppe
K149  Schema-Grenzen der Preis-Alarme folgen den Spaltenbreiten
GS11  Alarm-Limit zählt alle Zeilen des Nutzers
"""

import asyncio
import html
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from dateutils import utcnow
from models.alert_preference import AlertPreference
from models.position import AssetType, Position
from models.price_alert import PriceAlert
from models.price_cache import PriceCache
from models.smtp_config import SmtpConfig
from models.user import User, UserSettings
from models.watchlist import WatchlistItem

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"
EVIL = '<a href="//evil.tld">Jetzt anmelden</a>'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x", is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_position(db, user, ticker, **kwargs) -> Position:
    pos = Position(
        user_id=user.id,
        bucket_id=uuid.uuid4(),
        ticker=ticker,
        name=ticker,
        type=kwargs.pop("type", AssetType.stock),
        shares=Decimal("1"),
        is_active=True,
        **kwargs,
    )
    db.add(pos)
    await db.commit()
    return pos


async def _make_alert(db, user, ticker, alert_type="price_above", target="200", **kwargs) -> PriceAlert:
    alert = PriceAlert(
        user_id=user.id,
        ticker=ticker,
        alert_type=alert_type,
        target_value=Decimal(target),
        currency="CHF",
        **kwargs,
    )
    db.add(alert)
    await db.commit()
    return alert


async def _make_triggered_alert(db, user, ticker="ANET", **kwargs) -> PriceAlert:
    return await _make_alert(
        db, user, ticker,
        notify_email=True,
        is_active=False,
        is_triggered=True,
        triggered_at=utcnow(),
        trigger_price=Decimal("250"),
        notification_sent=False,
        **kwargs,
    )


async def _add_smtp_config(db, user) -> None:
    from services.auth_service import encrypt_value

    db.add(SmtpConfig(
        user_id=user.id,
        host="smtp.test.local",
        port=587,
        username="alerts@test.local",
        password_encrypted=encrypt_value("secret"),
        from_email="alerts@test.local",
        use_tls=True,
    ))
    await db.commit()


class _FakePrices:
    """Ersetzt die Kurs-Lesepfade von services.cache und zeichnet sie auf."""

    def __init__(self, prices: dict[str, float]):
        self.prices = {k: {"price": v, "change_pct": 0} for k, v in prices.items()}
        self.many_calls: list[list[str]] = []
        self.single_calls: list[str] = []

    def get(self, key):
        self.single_calls.append(key)
        return self.prices.get(key)

    def get_many(self, keys):
        self.many_calls.append(list(keys))
        return {k: self.prices[k] for k in keys if k in self.prices}


def _install_prices(monkeypatch, prices: dict[str, float]) -> _FakePrices:
    from services import cache

    fake = _FakePrices(prices)
    monkeypatch.setattr(cache, "get", fake.get)
    monkeypatch.setattr(cache, "get_many", fake.get_many)
    return fake


def _patch_smtp_send(monkeypatch, send) -> None:
    """aiosmtplib.send an der Bindungsstelle ersetzen (email_service.send_smtp_message).

    Für den SMTP-Server eines Nutzers öffnet send_smtp_message vorher eine
    geprüfte Verbindung; ohne den zweiten Patch liefe eine echte DNS-Auflösung.
    """
    from unittest.mock import AsyncMock

    from services import email_service

    monkeypatch.setattr(email_service.aiosmtplib, "send", send)
    monkeypatch.setattr(email_service, "open_pinned_socket", AsyncMock(return_value=object()))


def _mock_smtp(monkeypatch) -> list:
    """Erfolgreicher Versand; liefert die Liste der gesendeten Nachrichten."""
    sent: list = []

    async def _send(msg, **kwargs):
        sent.append(msg)

    _patch_smtp_send(monkeypatch, _send)
    return sent


def _global_smtp(monkeypatch, alert_email_to: str) -> None:
    import config

    monkeypatch.setattr(config.settings, "smtp_host", "smtp.operator.test")
    monkeypatch.setattr(config.settings, "smtp_user", "noreply@operator.test")
    monkeypatch.setattr(config.settings, "smtp_password", "secret")
    monkeypatch.setattr(config.settings, "alert_email_to", alert_email_to)


# ---------------------------------------------------------------------------
# K035 — Empfänger ist der Nutzer
# ---------------------------------------------------------------------------

async def test_k035_global_smtp_sends_to_user_not_to_operator(db, monkeypatch):
    from services.price_alert_service import send_alert_emails

    _global_smtp(monkeypatch, alert_email_to="ops@operator.test")
    user = await _make_user(db)
    alert = await _make_triggered_alert(db, user, note="private Notiz")
    sent = _mock_smtp(monkeypatch)

    await send_alert_emails([])

    assert len(sent) == 1
    assert sent[0]["To"] == user.email
    assert "ops@operator.test" not in sent[0].as_string()
    await db.refresh(alert)
    assert alert.notification_sent is True


async def test_k035_user_gets_mail_without_alert_email_to(db, monkeypatch):
    """Ohne ALERT_EMAIL_TO verwarf der Dienst die Mail und markierte sie als zugestellt."""
    from services.price_alert_service import send_alert_emails

    _global_smtp(monkeypatch, alert_email_to="")
    user = await _make_user(db)
    await _make_triggered_alert(db, user)
    sent = _mock_smtp(monkeypatch)

    await send_alert_emails([])

    assert [m["To"] for m in sent] == [user.email]


# ---------------------------------------------------------------------------
# K077 — Gesamt-Timeout und Backoff
# ---------------------------------------------------------------------------

async def test_k077_hanging_smtp_is_cut_off_and_backs_off(db, monkeypatch):
    import services.price_alert_service as pas

    user = await _make_user(db)
    await _add_smtp_config(db, user)
    settings_row = UserSettings(user_id=user.id)
    db.add(settings_row)
    await db.commit()
    alert = await _make_triggered_alert(db, user)

    attempts = []

    async def _hang(msg, **kwargs):
        attempts.append(msg)
        await asyncio.sleep(30)

    _patch_smtp_send(monkeypatch, _hang)
    monkeypatch.setattr(pas, "SMTP_SEND_TIMEOUT_SECONDS", 0.05, raising=False)

    # Ohne Gesamtgrenze hängt der Lauf so lange wie der Mailserver.
    await asyncio.wait_for(pas.send_alert_emails([]), timeout=3)

    assert len(attempts) == 1
    await db.refresh(alert)
    assert alert.notification_sent is False
    await db.refresh(settings_row)
    assert settings_row.last_email_digest_at is not None

    # Zweiter Lauf im Throttle-Fenster: kein neuer Verbindungsversuch.
    await asyncio.wait_for(pas.send_alert_emails([]), timeout=3)
    assert len(attempts) == 1

    # Nach dem Fenster liefert der Dienst nach.
    settings_row.last_email_digest_at = utcnow() - timedelta(minutes=16)
    await db.commit()
    sent = _mock_smtp(monkeypatch)
    await pas.send_alert_emails([])
    assert len(sent) == 1
    await db.refresh(alert)
    assert alert.notification_sent is True


async def test_k077_failing_smtp_of_one_user_does_not_block_the_next(db, monkeypatch):
    import services.price_alert_service as pas

    alerts = []
    for _ in range(2):
        user = await _make_user(db)
        await _add_smtp_config(db, user)
        alerts.append(await _make_triggered_alert(db, user))

    calls = []

    async def _first_fails(msg, **kwargs):
        calls.append(msg)
        if len(calls) == 1:
            raise ConnectionError("smtp down")

    _patch_smtp_send(monkeypatch, _first_fails)

    await pas.send_alert_emails([])

    assert len(calls) == 2
    for alert in alerts:
        await db.refresh(alert)
    assert sorted(a.notification_sent for a in alerts) == [False, True]


# ---------------------------------------------------------------------------
# X09 — Kurs-Schlüssel der Position
# ---------------------------------------------------------------------------

async def test_x09_alert_reads_price_under_yfinance_override(db, monkeypatch):
    from services.price_alert_service import check_price_alerts

    user = await _make_user(db)
    await _make_position(db, user, "ROG.SW", yfinance_ticker="ROP.SW")
    alert = await _make_alert(db, user, "ROG.SW", target="200")
    # Unter dem Anzeige-Ticker liegt ein fremder, alter Kurs.
    _install_prices(monkeypatch, {"price:ROP.SW": 250.0, "price:ROG.SW": 100.0})

    triggered = await check_price_alerts(db)

    assert [t["trigger_price"] for t in triggered] == [250.0]
    await db.refresh(alert)
    assert alert.is_triggered is True


async def test_x09_crypto_and_metal_positions_read_their_own_keys(db, monkeypatch):
    from services.price_alert_service import check_price_alerts

    user = await _make_user(db)
    await _make_position(db, user, "BTC", type=AssetType.crypto, coingecko_id="bitcoin")
    await _make_position(db, user, "XAUCHF=X", type=AssetType.commodity, gold_org=True)
    await _make_alert(db, user, "BTC", target="50000")
    await _make_alert(db, user, "XAUCHF=X", target="2000")
    fake = _install_prices(monkeypatch, {"crypto:bitcoin": 90000.0, "metal_chf:XAUCHF=X": 3000.0})

    triggered = await check_price_alerts(db)

    assert {t["ticker"]: t["trigger_price"] for t in triggered} == {"BTC": 90000.0, "XAUCHF=X": 3000.0}
    assert sorted(fake.many_calls[0]) == ["crypto:bitcoin", "metal_chf:XAUCHF=X"]


async def test_x09_position_key_wins_over_watchlist_and_is_user_scoped(db, monkeypatch):
    from services.price_alert_service import check_price_alerts

    holder = await _make_user(db)
    watcher = await _make_user(db)
    await _make_position(db, holder, "ROG.SW", yfinance_ticker="ROP.SW")
    db.add(WatchlistItem(user_id=holder.id, ticker="ROG.SW", name="Roche"))
    db.add(WatchlistItem(user_id=watcher.id, ticker="ROG.SW", name="Roche"))
    await db.commit()
    alert_holder = await _make_alert(db, holder, "ROG.SW", target="200")
    alert_watcher = await _make_alert(db, watcher, "ROG.SW", target="200")
    # Der Override gilt nur für den Nutzer, dem die Position gehört.
    _install_prices(monkeypatch, {"price:ROP.SW": 250.0, "price:ROG.SW": 100.0})

    triggered = await check_price_alerts(db)

    assert [t["id"] for t in triggered] == [str(alert_holder.id)]
    await db.refresh(alert_watcher)
    assert alert_watcher.is_active is True
    assert alert_watcher.is_triggered is False


# ---------------------------------------------------------------------------
# K114 — expires_at
# ---------------------------------------------------------------------------

async def test_k114_expired_alert_is_deactivated_not_triggered(db, monkeypatch):
    from services.price_alert_service import check_price_alerts

    user = await _make_user(db)
    await _make_position(db, user, "ANET")
    expired = await _make_alert(db, user, "ANET", expires_at=utcnow() - timedelta(minutes=1))
    _install_prices(monkeypatch, {"price:ANET": 250.0})

    triggered = await check_price_alerts(db)

    assert triggered == []
    await db.refresh(expired)
    assert expired.is_active is False
    assert expired.is_triggered is False
    assert expired.triggered_at is None


async def test_k114_alert_before_expiry_and_without_expiry_trigger(db, monkeypatch):
    from services.price_alert_service import check_price_alerts

    user = await _make_user(db)
    await _make_position(db, user, "ANET")
    pending = await _make_alert(db, user, "ANET", expires_at=utcnow() + timedelta(days=7))
    open_end = await _make_alert(db, user, "ANET")
    _install_prices(monkeypatch, {"price:ANET": 250.0})

    triggered = await check_price_alerts(db)

    assert {t["id"] for t in triggered} == {str(pending.id), str(open_end.id)}


# ---------------------------------------------------------------------------
# K132 — ein MGET je Lauf
# ---------------------------------------------------------------------------

async def test_k132_prices_are_read_once_per_run(db, monkeypatch):
    from services.price_alert_service import check_price_alerts

    for _ in range(2):
        user = await _make_user(db)
        await _make_position(db, user, "AAPL")
        await _make_position(db, user, "MSFT")
        for target in ("900", "950", "999"):
            await _make_alert(db, user, "AAPL", target=target)
            await _make_alert(db, user, "MSFT", target=target)
    fake = _install_prices(monkeypatch, {"price:AAPL": 250.0, "price:MSFT": 400.0})

    assert await check_price_alerts(db) == []

    assert len(fake.many_calls) == 1
    assert sorted(fake.many_calls[0]) == ["price:AAPL", "price:MSFT"]
    assert fake.single_calls == []


# ---------------------------------------------------------------------------
# K102 — Breakout-Mail
# ---------------------------------------------------------------------------

async def test_k102_breakout_mail_escapes_ticker_name_and_source(db, monkeypatch):
    import services.breakout_alert_service as bas
    from services import stock_scorer

    user = await _make_user(db)
    db.add(AlertPreference(user_id=user.id, category="breakout", is_enabled=True, notify_email=True))
    db.add(WatchlistItem(user_id=user.id, ticker="<b>T</b>", name=EVIL))
    await db.commit()

    monkeypatch.setattr(stock_scorer, "_download_and_analyze", lambda ticker: {"ok": True})
    monkeypatch.setattr(
        stock_scorer,
        "check_breakout_trigger",
        lambda ticker, analysis, manual_resistance: {
            "triggered": True,
            "current_price": 10.0,
            "resistance": 9.0,
            "resistance_source": "<i>quelle</i>",
            "volume_ratio": 2.0,
            "distance_to_resistance_pct": 11.1,
        },
    )

    class _Cache(dict):
        def set(self, key, value, ttl=None):
            self[key] = value

    monkeypatch.setattr(bas, "cache", _Cache())
    mails = []

    async def _send(to, subject, body_html, smtp_cfg=None):
        mails.append(body_html)
        return True

    monkeypatch.setattr(bas, "send_email", _send)

    await bas.check_breakout_alerts(db)

    assert len(mails) == 1
    body = mails[0]
    for raw in (EVIL, "<b>T</b>", "<i>quelle</i>"):
        assert raw not in body
        assert html.escape(raw) in body


# ---------------------------------------------------------------------------
# K153 / K172 — Betreiber-Mails
# ---------------------------------------------------------------------------

async def test_k153_staleness_mail_escapes_tickers(db):
    from services.price_staleness_service import _build_alert_html, check_price_staleness

    owner = uuid.uuid4()
    for ticker in (EVIL, "AAPL"):
        db.add(Position(
            user_id=owner, bucket_id=uuid.uuid4(), ticker=ticker, name=ticker,
            type=AssetType.stock, is_active=True, shares=1.0,
        ))
    db.add(PriceCache(ticker="AAPL", date=date(2026, 6, 5), close=100.0, currency="CHF", source="yahoo"))
    await db.commit()

    report = await check_price_staleness(db)
    assert [s["ticker"] for s in report["stale"]] == [EVIL]

    body = _build_alert_html(report)
    assert "<a href" not in body
    # Der Ticker steht in zwei Spalten: als yfinance-Ticker und als Position.
    assert body.count(html.escape(EVIL)) == 2


async def test_k172_stale_check_mail_escapes_industry_names():
    from services.screening.sector_rotation_stale_check import _build_alert_html

    body = _build_alert_html({
        "mismatch_count": 3,
        "orphan_industries": [{"industry_name": EVIL, "ticker_count": 3}],
        "total_tickers": 10,
    })

    assert "<a href" not in body
    assert html.escape(EVIL) in body


# ---------------------------------------------------------------------------
# K047 — Severity im Regel-Digest
# ---------------------------------------------------------------------------

async def test_k047_generate_alerts_only_emits_known_severities():
    from services.alert_service import generate_alerts
    from services.rule_alert_service import SEVERITY_ORDER

    # Buy-and-hold: weder Position noch Bucket haben eine Stop-Regel.
    position = {
        "ticker": "NESN.SW", "name": "Nestlé", "type": "stock", "bucket_id": None,
        "sector": "Consumer", "market_value_chf": 10_000, "shares": 10,
        "current_price": 100, "stop_loss_price": None, "pnl_pct": 0,
        "ma_status": "KRITISCH",
    }

    alerts = generate_alerts([position], None)

    ma_alerts = [a for a in alerts if a["category"] == "ma_critical"]
    assert len(ma_alerts) == 1
    assert ma_alerts[0]["severity"] == "high"
    assert all(a["severity"] in SEVERITY_ORDER for a in alerts)


async def test_k047_digest_renders_unknown_severity_in_rest_group():
    from services.rule_alert_service import _render_digest_html

    body = _render_digest_html([
        {"category": "ma_critical", "ticker": "AAPL", "title": "Unter 150-DMA: Apple",
         "message": "Fundamental-Check empfohlen", "severity": "warning"},
        {"category": "vix", "title": "VIX", "message": "erhöht", "severity": "critical"},
    ])

    assert "AAPL" in body and "Unter 150-DMA: Apple" in body
    assert "Weitere (1)" in body
    # Die Restgruppe steht nach den bekannten Stufen.
    assert body.index("Kritisch") < body.index("Weitere")


# ---------------------------------------------------------------------------
# K149 / GS11 — api/alerts.py
# ---------------------------------------------------------------------------

async def _register_and_login(client, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def test_k149_schema_limits_fit_column_widths():
    from api.alerts import AlertCreate, AlertUpdate

    columns = PriceAlert.__table__.c
    checked = set()
    for schema in (AlertCreate, AlertUpdate):
        for name, field in schema.model_fields.items():
            width = getattr(columns[name].type, "length", None) if name in columns else None
            if width is None:
                continue
            max_length = next(
                (m.max_length for m in field.metadata if hasattr(m, "max_length")), None
            )
            assert max_length is not None, f"{schema.__name__}.{name} ohne max_length"
            assert max_length <= width, f"{schema.__name__}.{name}: {max_length} > {width}"
            checked.add(name)
    assert checked == {"ticker", "alert_type", "currency", "note"}


async def test_k149_overlong_values_get_422(client):
    headers = await _register_and_login(client, "k149@example.com")
    valid = {"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0}

    for override in ({"ticker": "A" * 21}, {"note": "n" * 201}, {"alert_type": "t" * 21}):
        res = await client.post("/api/price-alerts", json={**valid, **override}, headers=headers)
        assert res.status_code == 422, override

    # Die Spaltenbreite selbst bleibt erlaubt.
    res = await client.post(
        "/api/price-alerts", json={**valid, "ticker": "A" * 20, "note": "n" * 200}, headers=headers
    )
    assert res.status_code == 200
    alert_id = res.json()["id"]

    res = await client.patch(f"/api/price-alerts/{alert_id}", json={"note": "n" * 201}, headers=headers)
    assert res.status_code == 422


async def test_gs11_limit_counts_triggered_and_inactive_alerts(client, db, monkeypatch):
    import api.alerts as alerts_api

    monkeypatch.setattr(alerts_api, "MAX_PRICE_ALERTS_PER_USER", 3, raising=False)
    headers = await _register_and_login(client, "gs11@example.com")
    other_headers = await _register_and_login(client, "gs11-other@example.com")
    user_id = (
        await db.execute(select(User.id).where(User.email == "gs11@example.com"))
    ).scalar_one()

    # Ausgelöste und deaktivierte Alarme belegen keinen aktiven Platz mehr,
    # zählen aber gegen die Obergrenze.
    for triggered in (True, True, False):
        await _make_alert(db, await db.get(User, user_id), "AAPL", is_active=False, is_triggered=triggered)

    payload = {"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0}
    res = await client.post("/api/price-alerts", json=payload, headers=headers)
    assert res.status_code == 400
    assert "Alarm-Limit" in res.json()["detail"]

    # Die Grenze gilt je Nutzer.
    res = await client.post("/api/price-alerts", json=payload, headers=other_headers)
    assert res.status_code == 200

    # Löschen gibt den Platz wieder frei.
    listed = await client.get("/api/price-alerts", headers=headers)
    res = await client.delete(f"/api/price-alerts/{listed.json()[0]['id']}", headers=headers)
    assert res.status_code == 204
    res = await client.post("/api/price-alerts", json=payload, headers=headers)
    assert res.status_code == 200
