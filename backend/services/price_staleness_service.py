"""Price-staleness guard — detect active positions whose latest cached price
has gone stale (silent feed death).

Catches the failure mode where a single ticker's yfinance feed dies while the
rest keep refreshing — invisible without a guard until performance / MRS /
score quietly run on a frozen price. Real case that motivated this: Roche's
Genussschein ``ROG.SW`` was converted to a participation certificate at the
2026-03-10 AGM; Yahoo dropped ``ROG.SW`` around 2026-05-19 and the position ran
17 days on a stale price before anyone noticed (siehe ``docs/research/SPIKE_SIX_COVERAGE.md``).

Mirrors the sector-rotation stale-check pattern: WARNING-log always, operator
email when stale tickers are present and SMTP is configured.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.position import AssetType, Position
from models.price_cache import PriceCache
from models.watchlist import WatchlistItem
from services.email_service import has_smtp_configured, send_email

logger = logging.getLogger(__name__)

# Calendar-day lag (relative to the freshest monitored ticker) beyond which a
# position's price counts as stale. 5 absorbs weekends + a single holiday + the
# ~1d yfinance lag; the Roche case was 17d, caught comfortably. Measuring
# against the freshest peer (not "today") auto-absorbs weekends/exchange
# holidays, so no business-day calendar is needed.
STALE_THRESHOLD_DAYS = 5

# Types priced outside the yahoo price_cache path (own pipelines or no live
# price): cash, pension, private equity, crypto (CoinGecko), precious metals.
_SKIP_TYPES = {
    AssetType.cash,
    AssetType.pension,
    AssetType.private_equity,
    AssetType.crypto,
}


async def check_price_staleness(db: AsyncSession) -> dict:
    """Find yahoo-priced holdings & watchlist items whose price_cache is stale.

    Monitors held positions (``shares > 0``) plus active watchlist items —
    both run through the same yahoo refresh, so a dead symbol on either goes
    silently stale. Crypto/metals/cash/pension/PE are priced outside price_cache
    and skipped.

    Staleness is measured relative to the freshest monitored ticker — the
    "market is fresh up to here" reference — which auto-absorbs weekends and
    exchange holidays. Tickers with no price_cache row at all count as stale.

    price_cache is global, so a dead feed affects every user; the check runs on
    the union across all users and alerts the operator (not per-user).
    """
    result = await db.execute(select(Position).where(Position.is_active.is_(True)))
    positions = result.scalars().all()

    # yf_ticker -> set of display tickers that resolve to it
    monitored: dict[str, set[str]] = {}
    for pos in positions:
        if pos.type in _SKIP_TYPES or pos.coingecko_id or pos.gold_org:
            continue
        # Nur tatsaechlich gehaltene Positionen (shares > 0). Geschlossene
        # Positionen bleiben oft is_active=true mit 0 Shares; ihr Kurs ist fuer
        # den Operator nicht handlungsrelevant (0 Shares -> 0 Wert), und ein
        # totes Symbol dort wuerde den Guard taeglich falsch alarmieren.
        if float(pos.shares or 0) <= 0:
            continue
        yf = pos.yfinance_ticker or pos.ticker
        if not yf:
            continue
        monitored.setdefault(yf, set()).add(pos.ticker)

    # Watchlist-Items: kein Wert-Impact, aber sie laufen im selben yahoo-Refresh,
    # und ein totes Symbol (z.B. BRK.B statt BRK-B) wirft still 60-s-Fehler und
    # liefert keinen Screening-Kurs. Crypto wird via CoinGecko bepreist (nicht im
    # price_cache unter ticker) → überspringen.
    wl = (await db.execute(select(WatchlistItem).where(WatchlistItem.is_active.is_(True)))).scalars().all()
    for item in wl:
        if item.type in _SKIP_TYPES or not item.ticker:
            continue
        monitored.setdefault(item.ticker, set()).add(f"{item.ticker} (Watchlist)")

    if not monitored:
        return {"stale": [], "stale_count": 0, "total_monitored": 0, "no_data": True}

    rows = (
        await db.execute(
            select(PriceCache.ticker, func.max(PriceCache.date))
            .where(PriceCache.ticker.in_(list(monitored.keys())))
            .group_by(PriceCache.ticker)
        )
    ).all()
    latest_by_ticker = {t: d for t, d in rows}

    fresh_dates = [d for d in latest_by_ticker.values() if d is not None]
    if not fresh_dates:
        # No price data at all for any monitored ticker — refresh itself is broken.
        return {"stale": [], "stale_count": 0, "total_monitored": len(monitored), "no_data": True}
    reference = max(fresh_dates)

    stale = []
    for yf, display in monitored.items():
        latest = latest_by_ticker.get(yf)
        if latest is None:
            stale.append({"ticker": yf, "display": sorted(display), "latest": None, "days_stale": None})
        else:
            days = (reference - latest).days
            if days > STALE_THRESHOLD_DAYS:
                stale.append(
                    {"ticker": yf, "display": sorted(display), "latest": latest.isoformat(), "days_stale": days}
                )

    # Missing data first, then most-stale first.
    stale.sort(key=lambda s: -(s["days_stale"] if s["days_stale"] is not None else 10**9))

    return {
        "stale": stale,
        "stale_count": len(stale),
        "total_monitored": len(monitored),
        "reference_date": reference.isoformat(),
    }


def _build_alert_html(report: dict) -> str:
    rows = "".join(
        f'<tr>'
        f'<td style="padding:6px 12px;border:1px solid #333;"><code>{s["ticker"]}</code></td>'
        f'<td style="padding:6px 12px;border:1px solid #333;">{", ".join(s["display"])}</td>'
        f'<td style="padding:6px 12px;border:1px solid #333;text-align:right;">'
        f'{"keine Daten" if s["latest"] is None else s["latest"]}</td>'
        f'<td style="padding:6px 12px;border:1px solid #333;text-align:right;">'
        f'{"—" if s["days_stale"] is None else str(s["days_stale"]) + " Tage"}</td>'
        f'</tr>'
        for s in report["stale"]
    )
    return f"""
    <div style="background:#1a1a2e;color:#e0e0e0;padding:32px;font-family:sans-serif;max-width:760px;margin:0 auto;border-radius:12px;">
      <h2 style="color:#F59E0B;margin-top:0;">OpenFolio: Kurse veraltet</h2>
      <p style="line-height:1.6;">
        Der tägliche Staleness-Check hat <b>{report["stale_count"]}</b> aktive Position(en)
        gefunden, deren letzter zwischengespeicherter Kurs gegenüber dem frischesten
        Ticker (Stand <b>{report["reference_date"]}</b>) mehr als
        {STALE_THRESHOLD_DAYS} Tage zurückliegt. Wahrscheinlichste Ursache: das
        yfinance-Symbol wurde umbenannt oder delisted (z.B. Titel-Umwandlung).
        Bis das behoben ist, laufen Performance, MRS und Score dieser Position auf
        einem eingefrorenen Preis.
      </p>
      <table style="border-collapse:collapse;margin:16px 0;">
        <thead><tr>
          <th style="padding:6px 12px;border:1px solid #333;background:#0f0f23;">yfinance-Ticker</th>
          <th style="padding:6px 12px;border:1px solid #333;background:#0f0f23;">Position</th>
          <th style="padding:6px 12px;border:1px solid #333;background:#0f0f23;">Letzter Kurs</th>
          <th style="padding:6px 12px;border:1px solid #333;background:#0f0f23;">Alter</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="color:#9ca3af;font-size:13px;line-height:1.5;">
        Überwachte Ticker total: {report["total_monitored"]}.
        Quelle: <code>backend/services/price_staleness_service.py</code>.
      </p>
      <hr style="border:none;border-top:1px solid #333;margin:24px 0;">
      <p style="color:#6b7280;font-size:12px;">OpenFolio — Price Staleness Detection</p>
    </div>
    """


async def run_staleness_check_with_alert(db: AsyncSession) -> dict:
    """Run the staleness check and email an alert if stale tickers are present.

    Recipient: ``settings.alert_email_to`` (preferred) or ``settings.admin_email``.
    If neither is set or SMTP is not configured, logs a WARNING and returns the
    report regardless — the cron stays useful even on a fresh install.
    """
    report = await check_price_staleness(db)

    if report.get("no_data"):
        logger.warning(
            "price-staleness check: no price_cache data for %d monitored tickers — refresh may be failing",
            report["total_monitored"],
        )
        return report

    if report["stale_count"] == 0:
        logger.info(
            "price-staleness check: 0 stale across %d monitored tickers (reference %s)",
            report["total_monitored"],
            report["reference_date"],
        )
        return report

    logger.warning(
        "price-staleness check: %d stale tickers (reference %s): %s",
        report["stale_count"],
        report["reference_date"],
        ", ".join(f"{s['ticker']}({s['days_stale'] if s['days_stale'] is not None else 'no-data'})" for s in report["stale"]),
    )

    recipient = settings.alert_email_to or settings.admin_email
    if not recipient or not has_smtp_configured():
        logger.warning("price-staleness check: SMTP/recipient not configured — alert not sent")
        return report

    sent = await send_email(
        to=recipient,
        subject=f"OpenFolio: {report['stale_count']} Position(en) mit veraltetem Kurs",
        body_html=_build_alert_html(report),
    )
    report["email_sent"] = bool(sent)
    return report
