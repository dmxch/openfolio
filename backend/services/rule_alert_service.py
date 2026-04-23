"""Portfolio-Rule Alert Service — emails a daily digest of triggered generate_alerts() rules.

Runs once per day via the worker. For each active user:
- loads AlertPreferences; early-returns if the user has no notify_email=True row
- reuses services.alert_service.generate_alerts() to compute the same alerts
  that the /api/alerts endpoint shows in the UI
- filters alerts by AlertPreference (is_enabled + notify_email) per category
- dedupes via a Redis cache (24h TTL, keyed by user+category+ticker) to
  prevent sending the same alert on two consecutive runs
- sends a single HTML digest via services.email_service.send_email
"""

import asyncio
import html
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alert_preference import AlertPreference
from models.smtp_config import SmtpConfig
from models.user import User, UserSettings
from models.watchlist import WatchlistItem
from services import cache
from services.alert_service import generate_alerts
from services.email_service import send_email
from services.market_analyzer import get_market_climate
from services.portfolio_service import get_portfolio_summary
from services.sector_mapping import is_broad_etf
from services.settings_service import settings_to_dict
from services.utils import compute_moving_averages, prefetch_close_series

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24

# Map alert_service category strings to AlertPreference.category keys
# (the UI-visible setting name). Kept in sync with CATEGORY_MAP in main.py
# and category_toggle in alert_service.py.
CATEGORY_TO_PREF: dict[str, str] = {
    "stop_loss_missing": "stop_missing",
    "stop_loss_unconfirmed": "stop_unconfirmed",
    "stop_proximity": "stop_proximity",
    "stop_reached": "stop_proximity",
    "stop_loss_review": "stop_review",
    "stop_loss_age": "stop_review",
    "ma_critical": "ma_critical",
    "ma_warning": "ma_warning",
    "position_limit": "position_limit",
    "sector_limit": "sector_limit",
    "loss": "loss",
    "market": "market_climate",
    "vix": "vix",
    "earnings": "earnings",
    "allocation_satellite": "allocation",
    "allocation_core": "allocation",
    "position_type_missing": "position_type_missing",
    "etf_200dma_buy": "etf_200dma_buy",
}

SEVERITY_ORDER = ["critical", "high", "medium", "info", "positive"]
SEVERITY_LABEL = {
    "critical": "Kritisch",
    "high": "Hoch",
    "medium": "Mittel",
    "info": "Info",
    "positive": "Kaufkriterien",
}
SEVERITY_COLOR = {
    "critical": "#ef4444",
    "high": "#f59e0b",
    "medium": "#eab308",
    "info": "#3b82f6",
    "positive": "#10b981",
}


async def check_rule_alerts(db: AsyncSession) -> None:
    """Entry point for the cron job. Iterates active users, isolates per-user failures."""
    users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()
    for user in users:
        try:
            await _check_user_rule_alerts(db, user)
        except Exception as e:
            logger.warning(
                f"Rule-Alert check failed for user {user.id}: {e}",
                exc_info=True,
            )


async def _check_user_rule_alerts(db: AsyncSession, user: User) -> None:
    """Run generate_alerts for one user, filter by AlertPreference, dedupe, email."""

    pref_rows = (await db.execute(
        select(AlertPreference).where(AlertPreference.user_id == user.id)
    )).scalars().all()
    pref_map = {p.category: p for p in pref_rows}

    if not any(p.is_enabled and p.notify_email for p in pref_rows):
        return

    summary = await get_portfolio_summary(db, user.id)
    positions = summary.get("positions", [])
    if not positions:
        return

    climate = await asyncio.to_thread(get_market_climate)

    settings_row = (await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )).scalars().first()
    user_prefs_dict = settings_to_dict(settings_row) if settings_row else {}

    watchlist_tickers = await _build_watchlist_tickers(db, user)

    try:
        alerts = generate_alerts(
            positions, climate, user_prefs_dict,
            watchlist_tickers=watchlist_tickers,
        )
    except Exception as e:
        logger.warning(f"generate_alerts failed for user {user.id}: {e}", exc_info=True)
        return

    to_send: list[dict] = []
    for a in alerts:
        raw_cat = a.get("category", "")
        pref_cat = CATEGORY_TO_PREF.get(raw_cat)
        if not pref_cat:
            continue
        pref = pref_map.get(pref_cat)
        if not pref or not pref.is_enabled or not pref.notify_email:
            continue

        ticker = a.get("ticker") or "_global"
        dedup_key = f"rule_alert_email:{user.id}:{pref_cat}:{ticker}"
        if cache.get(dedup_key):
            continue
        a["_pref_cat"] = pref_cat
        a["_dedup_key"] = dedup_key
        to_send.append(a)

    if not to_send:
        return

    smtp_cfg = await db.get(SmtpConfig, user.id)
    sent = await _send_rule_alert_digest(user, to_send, smtp_cfg)

    if sent:
        for a in to_send:
            cache.set(a["_dedup_key"], True, ttl=CACHE_TTL_HOURS * 3600)
        logger.info(
            f"Rule-Alert digest sent to user {user.id}: {len(to_send)} alerts "
            f"across {len({a['_pref_cat'] for a in to_send})} categories"
        )


async def _build_watchlist_tickers(db: AsyncSession, user: User) -> list[dict]:
    """Assemble the watchlist_tickers payload expected by generate_alerts.

    Mirrors the logic in main.py:/api/alerts — broad-ETF watchlist items get
    their 200-DMA status attached so generate_alerts can emit etf_200dma_buy
    entries for watchlist tickers the user does not yet hold.
    """
    wl_items = (await db.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == user.id)
    )).scalars().all()

    broad_tickers = [w.ticker for w in wl_items if is_broad_etf(w.ticker)]
    ma_map: dict[str, bool | None] = {}
    if broad_tickers:
        await asyncio.to_thread(prefetch_close_series, broad_tickers)

        def _compute_mas():
            out: dict[str, bool | None] = {}
            for t in broad_tickers:
                mas = compute_moving_averages(t, [200])
                current = mas.get("current")
                ma200 = mas.get("ma200")
                out[t] = current > ma200 if current is not None and ma200 is not None else None
            return out

        ma_map = await asyncio.to_thread(_compute_mas)

    return [
        {
            "ticker": w.ticker,
            "name": w.name or w.ticker,
            "ma_detail": {"above_ma200": ma_map.get(w.ticker)},
        }
        for w in wl_items
    ]


async def _send_rule_alert_digest(
    user: User, alerts_to_send: list[dict], smtp_cfg,
) -> bool:
    """Build the digest subject + HTML and hand off to email_service.send_email."""
    tickers_in_order = [a["ticker"] for a in alerts_to_send if a.get("ticker")]
    unique_tickers: list[str] = list(dict.fromkeys(tickers_in_order))
    sample = ", ".join(unique_tickers[:3]) if unique_tickers else "Portfolio"
    more = max(0, len(unique_tickers) - 3)
    more_suffix = f", +{more}" if more else ""
    plural = "e" if len(alerts_to_send) != 1 else ""
    subject = (
        f"OpenFolio: {len(alerts_to_send)} Regel-Alarm{plural} ausgeloest "
        f"({sample}{more_suffix})"
    )

    body_html = _render_digest_html(alerts_to_send)
    return await send_email(user.email, subject, body_html, smtp_cfg=smtp_cfg)


def _render_digest_html(alerts: list[dict]) -> str:
    """Dark-theme HTML digest grouped by severity (critical -> positive)."""
    groups: dict[str, list[dict]] = {sev: [] for sev in SEVERITY_ORDER}
    for a in alerts:
        sev = a.get("severity", "info")
        groups.setdefault(sev, []).append(a)

    sections_html = ""
    for sev in SEVERITY_ORDER:
        bucket = groups.get(sev) or []
        if not bucket:
            continue
        color = SEVERITY_COLOR.get(sev, "#9ca3af")
        label = SEVERITY_LABEL.get(sev, sev.capitalize())
        rows = ""
        for a in bucket:
            ticker = html.escape(a.get("ticker") or "—")
            title = html.escape(a.get("title") or "")
            message = html.escape(a.get("message") or "")
            rows += (
                "<tr style=\"border-bottom:1px solid #2a2a3e;\">"
                f"<td style=\"padding:8px 12px 8px 0;color:#fff;font-weight:bold;white-space:nowrap;\">{ticker}</td>"
                f"<td style=\"padding:8px 12px 8px 0;color:#e5e7eb;\">{title}</td>"
                f"<td style=\"padding:8px 0;color:#9ca3af;\">{message}</td>"
                "</tr>"
            )
        sections_html += (
            f"<h3 style=\"color:{color};border-bottom:1px solid {color};"
            "padding-bottom:4px;margin:24px 0 8px 0;font-size:16px;\">"
            f"{label} ({len(bucket)})</h3>"
            "<table style=\"width:100%;border-collapse:collapse;font-size:14px;\">"
            f"{rows}"
            "</table>"
        )

    plural = "e" if len(alerts) != 1 else ""
    return (
        "<div style=\"background:#1a1a2e;color:#e0e0e0;padding:32px;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "max-width:600px;margin:0 auto;border-radius:12px;\">"
        "<h2 style=\"color:#f59e0b;margin-top:0;\">Portfolio-Regel-Alarme</h2>"
        f"<p style=\"color:#9ca3af;font-size:14px;\">"
        f"{len(alerts)} Signal{plural} seit deinem letzten Digest.</p>"
        f"{sections_html}"
        "<hr style=\"border:none;border-top:1px solid #333;margin:24px 0;\">"
        "<p style=\"color:#6b7280;font-size:12px;line-height:1.5;\">"
        "Automatische Benachrichtigung basierend auf deinen Alarm-Einstellungen. "
        "Kategorien einzeln deaktivieren: Einstellungen &rarr; Alarme.<br>"
        "OpenFolio &mdash; Keine Anlageberatung.</p>"
        "</div>"
    )
