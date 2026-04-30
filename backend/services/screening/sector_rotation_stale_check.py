"""Weekly stale-detection check for the ticker → industry mapping.

TradingView occasionally renames industries. When that happens, rows in
``ticker_industries`` keep pointing at an ``industry_name`` that no
longer exists on the freshest ``MarketIndustry`` snapshot, and those
tickers silently classify as ``unknown`` — Smart-Money hits for them
lose their branche-rotation context without any visible failure.

This check runs once per week, counts mismatches, and escalates by
email if any are found. Without escalation a WARNING-only log is
theatre — nobody reads it until the UI wirkt leer.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.market_industry import MarketIndustry
from models.ticker_industry import TickerIndustry
from services.email_service import has_smtp_configured, send_email

logger = logging.getLogger(__name__)


async def check_industry_name_drift(db: AsyncSession) -> dict:
    """Count tickers whose industry_name no longer exists in the latest MarketIndustry snapshot.

    Returns a dict with counts and a list of orphaned industry names so the
    operator can see at a glance whether one industry was renamed or the
    whole snapshot is stale. The function never raises on data issues —
    callers (cron) get an actionable count or zero.
    """
    latest_ts = (
        await db.execute(
            select(MarketIndustry.scraped_at)
            .order_by(MarketIndustry.scraped_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest_ts is None:
        return {"mismatch_count": 0, "orphan_industries": [], "total_tickers": 0, "no_snapshot": True}

    valid_industries_q = select(MarketIndustry.name).where(MarketIndustry.scraped_at == latest_ts)

    total_tickers = (
        await db.execute(select(func.count()).select_from(TickerIndustry))
    ).scalar() or 0

    orphan_rows = (
        await db.execute(
            select(TickerIndustry.industry_name, func.count(TickerIndustry.ticker))
            .where(TickerIndustry.industry_name.notin_(valid_industries_q))
            .group_by(TickerIndustry.industry_name)
        )
    ).all()

    mismatch_count = sum(c for _, c in orphan_rows)
    orphan_industries = [{"industry_name": ind, "ticker_count": c} for ind, c in orphan_rows]

    return {
        "mismatch_count": mismatch_count,
        "orphan_industries": orphan_industries,
        "total_tickers": total_tickers,
        "no_snapshot": False,
    }


def _build_alert_html(report: dict) -> str:
    rows = "".join(
        f'<tr><td style="padding:6px 12px;border:1px solid #333;">{o["industry_name"]}</td>'
        f'<td style="padding:6px 12px;border:1px solid #333;text-align:right;">{o["ticker_count"]}</td></tr>'
        for o in report["orphan_industries"]
    )
    return f"""
    <div style="background:#1a1a2e;color:#e0e0e0;padding:32px;font-family:sans-serif;max-width:700px;margin:0 auto;border-radius:12px;">
      <h2 style="color:#F59E0B;margin-top:0;">OpenFolio: Branchen-Klassifikation veraltet</h2>
      <p style="line-height:1.6;">
        Der wöchentliche Stale-Check hat <b>{report["mismatch_count"]}</b> Ticker gefunden,
        deren <code>industry_name</code> nicht mehr im aktuellen TradingView-Snapshot vorkommt.
        Wahrscheinlichste Ursache: TradingView hat eine oder mehrere Industries umbenannt.
        Bis das ticker_industries-Mapping refresh durchläuft (täglich 01:30 CET),
        klassifiziert der Smart-Money-Screener diese Hits als <code>unknown</code>.
      </p>
      <table style="border-collapse:collapse;margin:16px 0;">
        <thead><tr>
          <th style="padding:6px 12px;border:1px solid #333;background:#0f0f23;">Veraltete Industry</th>
          <th style="padding:6px 12px;border:1px solid #333;background:#0f0f23;">Ticker-Anzahl</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="color:#9ca3af;font-size:13px;line-height:1.5;">
        Total Ticker im Mapping: {report["total_tickers"]}.
        Quelle: <code>backend/services/screening/sector_rotation_stale_check.py</code>.
      </p>
      <hr style="border:none;border-top:1px solid #333;margin:24px 0;">
      <p style="color:#6b7280;font-size:12px;">OpenFolio — Sector-Rotation Stale Detection</p>
    </div>
    """


async def run_stale_check_with_alert(db: AsyncSession) -> dict:
    """Run the drift check and email an alert if mismatches are present.

    Recipient: ``settings.alert_email_to`` (preferred) or ``settings.admin_email``.
    If neither is set or SMTP is not configured the function logs a
    WARNING and returns the report regardless — the cron stays useful
    even on a freshly bootstrapped install.
    """
    report = await check_industry_name_drift(db)

    if report.get("no_snapshot"):
        logger.warning("sector-rotation stale-check: no MarketIndustry snapshot — industries-refresh may be failing")
        return report

    if report["mismatch_count"] == 0:
        logger.info("sector-rotation stale-check: 0 mismatches across %d tickers", report["total_tickers"])
        return report

    logger.warning(
        "sector-rotation stale-check: %d tickers with orphaned industry_name across %d distinct industries",
        report["mismatch_count"],
        len(report["orphan_industries"]),
    )

    recipient = settings.alert_email_to or settings.admin_email
    if not recipient or not has_smtp_configured():
        logger.warning("sector-rotation stale-check: SMTP/recipient not configured — alert not sent")
        return report

    sent = await send_email(
        to=recipient,
        subject=f"OpenFolio: Sektor-Klassifikation veraltet ({report['mismatch_count']} Ticker)",
        body_html=_build_alert_html(report),
    )
    report["email_sent"] = bool(sent)
    return report
