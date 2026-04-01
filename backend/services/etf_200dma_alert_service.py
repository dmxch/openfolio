"""ETF 200-DMA alert service — sends email notifications for broad index ETFs below 200-DMA."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alert_preference import AlertPreference
from models.position import Position
from models.watchlist import WatchlistItem
from models.user import User
from services import cache
from services.sector_mapping import is_broad_etf
from services.utils import compute_moving_averages
from services.email_service import send_email

logger = logging.getLogger(__name__)

ALERT_CATEGORY = "etf_200dma_buy"
CACHE_TTL_HOURS = 24


async def check_etf_200dma_alerts(db: AsyncSession) -> None:
    """Check all users' positions and watchlists for broad ETFs below 200-DMA and send email alerts."""

    # Load all users
    users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()

    for user in users:
        try:
            await _check_user_alerts(db, user)
        except Exception as e:
            logger.warning(f"ETF 200-DMA alert check failed for user {user.id}: {e}")


async def _check_user_alerts(db: AsyncSession, user: User) -> None:
    """Check one user's positions and watchlist for ETF 200-DMA alerts."""

    # Check if user has email enabled for this category
    pref_result = await db.execute(
        select(AlertPreference).where(
            AlertPreference.user_id == user.id,
            AlertPreference.category == ALERT_CATEGORY,
        )
    )
    pref = pref_result.scalars().first()
    if pref and (not pref.is_enabled or not pref.notify_email):
        return
    # Default (no pref row): enabled but email off → skip
    if not pref:
        return

    # Collect unique broad ETF tickers from positions + watchlist
    tickers: set[str] = set()

    positions = (await db.execute(
        select(Position).where(
            Position.user_id == user.id,
            Position.is_active == True,
            Position.shares > 0,
        )
    )).scalars().all()
    for p in positions:
        if is_broad_etf(p.ticker):
            tickers.add(p.ticker)

    watchlist = (await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.is_active == True,
        )
    )).scalars().all()
    for w in watchlist:
        if is_broad_etf(w.ticker):
            tickers.add(w.ticker)

    if not tickers:
        return

    # Check each ticker for below-200-DMA
    triggered: list[dict] = []
    for ticker in tickers:
        # Deduplication: cache key per user+ticker, TTL 24h
        dedup_key = f"etf_200dma_email:{user.id}:{ticker}"
        if cache.get(dedup_key):
            continue

        mas = compute_moving_averages(ticker, [200])
        current = mas.get("current")
        ma200 = mas.get("ma200")

        if current is not None and ma200 is not None and current < ma200:
            triggered.append({
                "ticker": ticker,
                "current": current,
                "ma200": ma200,
            })
            cache.set(dedup_key, True, ttl=CACHE_TTL_HOURS * 3600)

    if not triggered:
        return

    # Send email
    from models.smtp_config import SmtpConfig
    smtp_cfg = await db.get(SmtpConfig, user.id)

    for alert in triggered:
        ticker = alert["ticker"]
        current = alert["current"]
        ma200 = alert["ma200"]

        subject = f"OpenFolio: ETF Kaufkriterien erfüllt — {ticker} unter 200-DMA"
        body_html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 500px;">
            <h2 style="color: #10b981; margin-bottom: 8px;">ETF unter 200-DMA</h2>
            <p style="color: #e5e7eb; font-size: 15px;">
                <strong>{ticker}</strong> handelt unter der 200-Tage-Linie — Kaufkriterien gemäss Strategie erfüllt.
            </p>
            <table style="border-collapse: collapse; margin: 16px 0; font-size: 14px; color: #d1d5db;">
                <tr><td style="padding: 4px 12px 4px 0;">Aktueller Kurs:</td><td style="font-weight: bold;">{current:.2f}</td></tr>
                <tr><td style="padding: 4px 12px 4px 0;">200-DMA:</td><td style="font-weight: bold;">{ma200:.2f}</td></tr>
                <tr><td style="padding: 4px 12px 4px 0;">Abstand:</td><td style="font-weight: bold; color: #10b981;">{((current / ma200 - 1) * 100):.1f}%</td></tr>
            </table>
            <p style="color: #9ca3af; font-size: 12px; margin-top: 16px;">
                Dies ist eine automatische Benachrichtigung basierend auf deiner Anlagestrategie.
                Keine Anlageberatung — eigene Analyse durchführen.
            </p>
        </div>
        """
        await send_email(user.email, subject, body_html, smtp_cfg=smtp_cfg)
        logger.info(f"ETF 200-DMA alert email sent for {ticker} to user {user.id}")
