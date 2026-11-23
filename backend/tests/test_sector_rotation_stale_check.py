"""Stale-Check des Ticker→Industry-Mappings.

Nur eine Industry, die ein früherer Snapshot kannte und der neueste nicht
mehr hat, gilt als umbenannt und löst eine Mail aus. Industries ohne
Aggregat-Zeile bei TradingView (Beispiel: «General Government» für die
TVA-Anleihen TVE/TVC) erscheinen nur im Bericht, nicht als Treffer.
"""

import uuid
from datetime import datetime, timedelta

import pytest

from models.market_industry import MarketIndustry
from models.ticker_industry import TickerIndustry
from services.screening import sector_rotation_stale_check as stale

pytestmark = pytest.mark.asyncio

T_OLD = datetime(2026, 11, 20, 1, 30)
T_NEW = T_OLD + timedelta(days=1)


def _industry(name: str, scraped_at: datetime) -> MarketIndustry:
    return MarketIndustry(
        id=uuid.uuid4(),
        slug=name.lower().replace(" ", "-"),
        name=name,
        scraped_at=scraped_at,
    )


async def _seed(db) -> None:
    db.add_all([
        _industry("Semiconductors", T_OLD),
        _industry("Old Name", T_OLD),
        _industry("Semiconductors", T_NEW),
        TickerIndustry(ticker="NVDA", industry_name="Semiconductors", updated_at=T_NEW),
        TickerIndustry(ticker="AAA", industry_name="Old Name", updated_at=T_NEW),
        TickerIndustry(ticker="TVE", industry_name="General Government", updated_at=T_NEW),
        TickerIndustry(ticker="TVC", industry_name="General Government", updated_at=T_NEW),
    ])
    await db.commit()


async def test_only_renamed_industries_count_as_mismatch(db):
    await _seed(db)

    report = await stale.check_industry_name_drift(db)

    assert report["total_tickers"] == 4
    assert report["mismatch_count"] == 1
    assert report["orphan_industries"] == [{"industry_name": "Old Name", "ticker_count": 1}]
    assert report["unaggregated_industries"] == [
        {"industry_name": "General Government", "ticker_count": 2}
    ]


async def test_unaggregated_industry_alone_sends_no_mail(db, monkeypatch):
    db.add_all([
        _industry("Semiconductors", T_NEW),
        TickerIndustry(ticker="NVDA", industry_name="Semiconductors", updated_at=T_NEW),
        TickerIndustry(ticker="TVE", industry_name="General Government", updated_at=T_NEW),
    ])
    await db.commit()

    sent: list[dict] = []

    async def fake_send_email(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(stale, "send_email", fake_send_email)
    monkeypatch.setattr(stale, "has_smtp_configured", lambda: True)
    monkeypatch.setattr(stale.settings, "alert_email_to", "ops@example.test")

    report = await stale.run_stale_check_with_alert(db)

    assert report["mismatch_count"] == 0
    assert sent == []


async def test_renamed_industry_sends_mail(db, monkeypatch):
    await _seed(db)

    sent: list[dict] = []

    async def fake_send_email(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(stale, "send_email", fake_send_email)
    monkeypatch.setattr(stale, "has_smtp_configured", lambda: True)
    monkeypatch.setattr(stale.settings, "alert_email_to", "ops@example.test")

    report = await stale.run_stale_check_with_alert(db)

    assert report["email_sent"] is True
    assert len(sent) == 1
    assert "(1 Ticker)" in sent[0]["subject"]
    assert "Old Name" in sent[0]["body_html"]
    assert "General Government" not in sent[0]["body_html"]
