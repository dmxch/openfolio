"""Builds and sends news digest newsletters to subscribed users."""
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from dateutils import utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.news_article import NewsArticle
from models.position import Position
from models.smtp_config import SmtpConfig
from models.user import User, UserSettings
from models.watchlist import WatchlistItem
from services.email_service import send_email

logger = logging.getLogger(__name__)


def _format_date(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%d.%m.%Y %H:%M")


def _build_article_html(article: NewsArticle) -> str:
    """Render a single article as HTML row."""
    date_str = _format_date(article.published_at)
    source = f' — {article.source}' if article.source else ''
    snippet = ""
    if article.snippet:
        text = article.snippet[:200]
        if len(article.snippet) > 200:
            text += "..."
        snippet = f'<p style="color:#9ca3af;font-size:12px;line-height:1.4;margin:4px 0 0 0;">{text}</p>'

    return f"""
    <div style="padding:10px 0;border-bottom:1px solid #2a2a3e;">
        <a href="{article.url}" style="color:#3B82F6;text-decoration:none;font-size:14px;font-weight:500;line-height:1.4;">
            {article.title}
        </a>
        <p style="color:#6b7280;font-size:11px;margin:4px 0 0 0;">{date_str}{source}</p>
        {snippet}
    </div>
    """


def _build_section_html(title: str, articles_by_ticker: dict[str, list[NewsArticle]]) -> str:
    """Build a newsletter section (Portfolio or Watchlist)."""
    if not articles_by_ticker:
        return ""

    ticker_blocks = []
    for ticker in sorted(articles_by_ticker.keys()):
        articles = articles_by_ticker[ticker]
        articles_html = "".join(_build_article_html(a) for a in articles[:5])  # max 5 per ticker
        ticker_blocks.append(f"""
        <div style="margin-bottom:20px;">
            <h3 style="color:#e0e0e0;font-size:15px;font-family:monospace;margin:0 0 8px 0;padding:8px 12px;background:#0f0f23;border-radius:6px;border-left:3px solid #3B82F6;">
                {ticker}
            </h3>
            {articles_html}
        </div>
        """)

    return f"""
    <div style="margin-bottom:32px;">
        <h2 style="color:#3B82F6;font-size:18px;margin:0 0 16px 0;padding-bottom:8px;border-bottom:2px solid #3B82F6;">
            {title}
        </h2>
        {"".join(ticker_blocks)}
    </div>
    """


async def build_newsletter_html(
    db: AsyncSession,
    user_id: uuid.UUID,
    scope: str = "all",
    since: datetime | None = None,
) -> str | None:
    """Build newsletter HTML for a user. Returns None if no news available."""
    if since is None:
        since = utcnow() - timedelta(days=1)

    # Get user's tickers
    portfolio_tickers: set[str] = set()
    watchlist_tickers: set[str] = set()

    if scope in ("portfolio", "all"):
        pos_q = select(Position.ticker).where(
            Position.user_id == user_id,
            Position.is_active == True,
            Position.shares > 0,
        )
        portfolio_tickers = set((await db.execute(pos_q)).scalars().all())

    if scope in ("watchlist", "all"):
        wl_q = select(WatchlistItem.ticker).where(
            WatchlistItem.user_id == user_id,
            WatchlistItem.is_active == True,
        )
        watchlist_tickers = set((await db.execute(wl_q)).scalars().all())

    all_tickers = portfolio_tickers | watchlist_tickers
    if not all_tickers:
        return None

    # Fetch recent articles
    query = (
        select(NewsArticle)
        .where(
            NewsArticle.ticker.in_(all_tickers),
            NewsArticle.fetched_at >= since,
        )
        .order_by(NewsArticle.published_at.desc().nullslast())
    )
    articles = (await db.execute(query)).scalars().all()

    if not articles:
        return None

    # Group by ticker, then split into portfolio vs watchlist
    portfolio_articles: dict[str, list] = defaultdict(list)
    watchlist_articles: dict[str, list] = defaultdict(list)

    for article in articles:
        if article.ticker in portfolio_tickers:
            portfolio_articles[article.ticker].append(article)
        elif article.ticker in watchlist_tickers:
            watchlist_articles[article.ticker].append(article)

    today = utcnow().strftime("%d.%m.%Y")
    total_count = len(articles)

    portfolio_section = _build_section_html("Portfolio-Nachrichten", portfolio_articles)
    watchlist_section = _build_section_html("Watchlist-Nachrichten", watchlist_articles)

    html = f"""
    <div style="background:#1a1a2e;color:#e0e0e0;padding:32px;font-family:sans-serif;max-width:600px;margin:0 auto;border-radius:12px;">
        <div style="margin-bottom:24px;">
            <h1 style="color:#e0e0e0;font-size:22px;margin:0;">OpenFolio Newsletter</h1>
            <p style="color:#6b7280;font-size:13px;margin:4px 0 0 0;">{today} — {total_count} Nachrichten</p>
        </div>

        {portfolio_section}
        {watchlist_section}

        <hr style="border:none;border-top:1px solid #333;margin:24px 0;">
        <p style="color:#6b7280;font-size:11px;line-height:1.5;">
            Dieser Newsletter wurde automatisch von OpenFolio generiert.<br>
            Du kannst die Häufigkeit in den Einstellungen ändern.
        </p>
        <p style="color:#4b5563;font-size:11px;">OpenFolio — Portfolio & Marktanalyse</p>
    </div>
    """
    return html


async def send_newsletters(db: AsyncSession) -> int:
    """Send newsletters to all subscribed users. Returns count sent."""
    # Find users with newsletter enabled
    settings_q = select(UserSettings).where(UserSettings.newsletter_frequency != "off")
    user_settings_list = (await db.execute(settings_q)).scalars().all()

    if not user_settings_list:
        return 0

    now = utcnow()
    sent_count = 0

    for us in user_settings_list:
        # Check timing
        if us.last_email_digest_at:
            if us.newsletter_frequency == "daily" and (now - us.last_email_digest_at) < timedelta(hours=20):
                continue
            if us.newsletter_frequency == "weekly" and (now - us.last_email_digest_at) < timedelta(days=6):
                continue
            # Weekly: only on Mondays
            if us.newsletter_frequency == "weekly" and now.weekday() != 0:
                continue

        # Determine lookback period
        if us.last_email_digest_at:
            since = us.last_email_digest_at
        else:
            since = now - timedelta(days=1 if us.newsletter_frequency == "daily" else 7)

        # Load user
        user = await db.get(User, us.user_id)
        if not user or not user.email:
            continue

        # Build newsletter
        scope = us.newsletter_scope or "all"
        html = await build_newsletter_html(db, us.user_id, scope=scope, since=since)
        if not html:
            continue

        # Get SMTP config
        smtp_cfg = await db.get(SmtpConfig, us.user_id)

        # Send
        subject = f"OpenFolio Newsletter — {now.strftime('%d.%m.%Y')}"
        success = await send_email(user.email, subject, html, smtp_cfg=smtp_cfg)

        if success:
            us.last_email_digest_at = now
            await db.commit()
            sent_count += 1
            logger.info("Newsletter sent to %s", user.email)

    return sent_count
