"""Builds and sends AI-summarized news digest newsletters."""
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
from services.ai_summary_service import summarize_ticker_news
from services.email_service import send_email

logger = logging.getLogger(__name__)


def _format_date(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%d.%m.%Y %H:%M")


def _build_ticker_block_ai(ticker: str, summary: str, articles: list) -> str:
    """Build a compact AI-summarized ticker block."""
    article_links = ""
    for a in articles[:5]:
        date_str = _format_date(a.published_at)
        article_links += f"""
        <div style="padding:3px 0;">
            <a href="{a.url}" style="color:#6b7280;text-decoration:none;font-size:11px;">
                &#8594; {a.title[:80]}{'...' if len(a.title) > 80 else ''} <span style="color:#4b5563;">({date_str})</span>
            </a>
        </div>
        """

    return f"""
    <div style="margin-bottom:24px;padding:16px;background:#0f0f23;border-radius:8px;border-left:3px solid #3B82F6;">
        <h3 style="color:#e0e0e0;font-size:15px;font-family:monospace;margin:0 0 10px 0;">
            {ticker}
        </h3>
        <p style="color:#e0e0e0;font-size:13px;line-height:1.6;margin:0 0 12px 0;">
            {summary}
        </p>
        <div style="border-top:1px solid #2a2a3e;padding-top:8px;margin-top:8px;">
            <p style="color:#4b5563;font-size:10px;margin:0 0 4px 0;">Quellen ({len(articles)} Artikel):</p>
            {article_links}
        </div>
    </div>
    """


def _build_ticker_block_raw(ticker: str, articles: list) -> str:
    """Build a raw ticker block (fallback without AI)."""
    articles_html = ""
    for a in articles[:5]:
        date_str = _format_date(a.published_at)
        source = f' — {a.source}' if a.source else ''
        articles_html += f"""
        <div style="padding:8px 0;border-bottom:1px solid #2a2a3e;">
            <a href="{a.url}" style="color:#3B82F6;text-decoration:none;font-size:13px;">{a.title}</a>
            <p style="color:#6b7280;font-size:11px;margin:2px 0 0 0;">{date_str}{source}</p>
        </div>
        """

    return f"""
    <div style="margin-bottom:20px;">
        <h3 style="color:#e0e0e0;font-size:15px;font-family:monospace;margin:0 0 8px 0;padding:8px 12px;background:#0f0f23;border-radius:6px;border-left:3px solid #3B82F6;">
            {ticker}
        </h3>
        {articles_html}
    </div>
    """


def _build_section_html(title: str, ticker_blocks: list[str]) -> str:
    """Build a newsletter section."""
    if not ticker_blocks:
        return ""
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
    ai_provider: str | None = None,
    ai_model: str | None = None,
    ai_api_key: str | None = None,
    ai_ollama_url: str | None = None,
) -> str | None:
    """Build newsletter HTML for a user with optional AI summaries."""
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

    # Group by ticker
    by_ticker: dict[str, list] = defaultdict(list)
    for article in articles:
        by_ticker[article.ticker].append(article)

    use_ai = bool(ai_provider and ai_model)

    # Build ticker blocks with optional AI summaries
    portfolio_blocks: list[str] = []
    watchlist_blocks: list[str] = []

    for ticker in sorted(by_ticker.keys()):
        ticker_articles = by_ticker[ticker]
        headlines = [a.title for a in ticker_articles[:10]]

        if use_ai:
            summary = await summarize_ticker_news(
                headlines, ticker, ai_provider, ai_model, ai_api_key, ai_ollama_url
            )
            block = _build_ticker_block_ai(ticker, summary, ticker_articles) if summary else _build_ticker_block_raw(ticker, ticker_articles)
        else:
            block = _build_ticker_block_raw(ticker, ticker_articles)

        if ticker in portfolio_tickers:
            portfolio_blocks.append(block)
        elif ticker in watchlist_tickers:
            watchlist_blocks.append(block)

    today = utcnow().strftime("%d.%m.%Y")
    total_count = len(articles)
    ai_badge = ' <span style="color:#10b981;font-size:11px;">&#9679; KI-Zusammenfassung</span>' if use_ai else ''

    portfolio_section = _build_section_html("Portfolio-Nachrichten", portfolio_blocks)
    watchlist_section = _build_section_html("Watchlist-Nachrichten", watchlist_blocks)

    html = f"""
    <div style="background:#1a1a2e;color:#e0e0e0;padding:32px;font-family:sans-serif;max-width:600px;margin:0 auto;border-radius:12px;">
        <div style="margin-bottom:24px;">
            <h1 style="color:#e0e0e0;font-size:22px;margin:0;">OpenFolio Newsletter{ai_badge}</h1>
            <p style="color:#6b7280;font-size:13px;margin:4px 0 0 0;">{today} — {total_count} Nachrichten zu {len(by_ticker)} Titeln</p>
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
    """Send newsletters to all subscribed users with AI summaries."""
    from services.auth_service import decrypt_value

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
            if us.newsletter_frequency == "weekly" and now.weekday() != 0:
                continue

        # Require AI provider for newsletter (without AI it's too noisy)
        if not us.ai_provider:
            continue

        # Decrypt AI API key
        ai_api_key = None
        if us.ai_api_key_encrypted:
            try:
                ai_api_key = decrypt_value(us.ai_api_key_encrypted)
            except Exception:
                logger.warning("Failed to decrypt AI key for user %s", us.user_id)
                continue

        # Determine lookback
        if us.last_email_digest_at:
            since = us.last_email_digest_at
        else:
            since = now - timedelta(days=1 if us.newsletter_frequency == "daily" else 7)

        # Load user
        user = await db.get(User, us.user_id)
        if not user or not user.email:
            continue

        # Build newsletter with AI
        scope = us.newsletter_scope or "all"
        html = await build_newsletter_html(
            db, us.user_id, scope=scope, since=since,
            ai_provider=us.ai_provider, ai_model=us.ai_model,
            ai_api_key=ai_api_key, ai_ollama_url=us.ai_ollama_url,
        )
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
            logger.info("Newsletter sent to %s (AI: %s/%s)", user.email, us.ai_provider, us.ai_model)

    return sent_count
