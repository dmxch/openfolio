"""Watchlist Breakout Alert Service — sends email for Donchian 20d breakouts on watchlist tickers."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alert_preference import AlertPreference
from models.watchlist import WatchlistItem
from models.user import User
from services import cache
from services.email_service import send_email

logger = logging.getLogger(__name__)

ALERT_CATEGORY = "watchlist_breakout"
CACHE_TTL_HOURS = 24


async def check_breakout_alerts(db: AsyncSession) -> None:
    """Check all users' watchlists for Donchian breakout triggers and send email alerts."""

    users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()

    for user in users:
        try:
            await _check_user_breakout_alerts(db, user)
        except Exception as e:
            logger.warning(f"Breakout alert check failed for user {user.id}: {e}", exc_info=True)


async def _check_user_breakout_alerts(db: AsyncSession, user: User) -> None:
    """Check one user's watchlist for Donchian breakout alerts."""

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
    # Default (no pref row): enabled but email off -> skip
    if not pref:
        return

    # Load active watchlist items
    watchlist = (await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.is_active == True,
        )
    )).scalars().all()

    if not watchlist:
        return

    # Import scoring functions (lazy to avoid circular imports at module level)
    from services.stock_scorer import download_and_analyze, check_breakout_trigger

    triggered: list[dict] = []

    for item in watchlist:
        # Deduplication: cache key per user+ticker, TTL 24h
        dedup_key = f"breakout_email:{user.id}:{item.ticker}"
        if cache.get(dedup_key):
            continue

        analysis = download_and_analyze(item.ticker)
        if not analysis:
            continue

        breakout = check_breakout_trigger(item.ticker, analysis, item.manual_resistance)

        if breakout.get("triggered"):
            triggered.append({
                "ticker": item.ticker,
                "name": item.name,
                "current_price": breakout.get("current_price"),
                "resistance": breakout.get("resistance"),
                "resistance_source": breakout.get("resistance_source", "donchian_20d"),
                "volume_ratio": breakout.get("volume_ratio"),
                "distance_pct": breakout.get("distance_to_resistance_pct"),
            })
            cache.set(dedup_key, True, ttl=CACHE_TTL_HOURS * 3600)

    if not triggered:
        return

    # Send email for each triggered ticker
    from models.smtp_config import SmtpConfig
    smtp_cfg = await db.get(SmtpConfig, user.id)

    for alert in triggered:
        ticker = alert["ticker"]
        name = alert["name"]
        current_price = alert["current_price"]
        resistance = alert["resistance"]
        source_label = {
            "manual": "Manueller Widerstand",
            "donchian_20d": "Donchian 20d-Hoch",
            "52w_high": "52-Wochen-Hoch",
        }.get(alert["resistance_source"], alert["resistance_source"])
        volume_ratio = alert["volume_ratio"]
        distance_pct = alert["distance_pct"]

        subject = f"OpenFolio: Breakout-Kriterien erfuellt — {ticker}"
        body_html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 500px;">
            <h2 style="color: #f59e0b; margin-bottom: 8px;">Donchian Breakout erkannt</h2>
            <p style="color: #e5e7eb; font-size: 15px;">
                <strong>{ticker}</strong> ({name}) hat die Breakout-Kriterien erfuellt (Donchian 20d + Volumenbestaetigung).
            </p>
            <table style="border-collapse: collapse; margin: 16px 0; font-size: 14px; color: #d1d5db;">
                <tr><td style="padding: 4px 12px 4px 0;">Aktueller Kurs:</td><td style="font-weight: bold;">{current_price:.2f}</td></tr>
                <tr><td style="padding: 4px 12px 4px 0;">Widerstand ({source_label}):</td><td style="font-weight: bold;">{resistance:.2f}</td></tr>
                <tr><td style="padding: 4px 12px 4px 0;">Abstand:</td><td style="font-weight: bold; color: #f59e0b;">+{distance_pct:.1f}%</td></tr>
                <tr><td style="padding: 4px 12px 4px 0;">Volumen-Ratio:</td><td style="font-weight: bold;">{volume_ratio:.1f}x</td></tr>
            </table>
            <p style="color: #9ca3af; font-size: 12px; margin-top: 16px;">
                Dies ist eine automatische Benachrichtigung basierend auf deiner Watchlist.
                Keine Anlageberatung — eigene Analyse durchfuehren.
            </p>
        </div>
        """
        await send_email(user.email, subject, body_html, smtp_cfg=smtp_cfg)
        logger.info(f"Breakout alert email sent for {ticker} to user {user.id}")
