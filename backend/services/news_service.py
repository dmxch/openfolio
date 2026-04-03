"""Fetches financial news from Yahoo Finance RSS and manages the news_articles table."""
import asyncio
import logging
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from dateutils import utcnow
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.news_article import NewsArticle
from models.position import Position
from models.watchlist import WatchlistItem
from services.api_utils import fetch_text

logger = logging.getLogger(__name__)

YAHOO_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"


def _parse_rss_date(date_str: str) -> datetime | None:
    """Parse RSS pubDate string to naive UTC datetime."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        # Convert to naive UTC for PostgreSQL TIMESTAMP WITHOUT TIME ZONE
        if dt.tzinfo is not None:
            from datetime import timezone
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _parse_yahoo_rss(xml_text: str) -> list[dict]:
    """Parse Yahoo Finance RSS XML into article dicts."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    articles = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not title or not url:
            continue

        articles.append({
            "title": title[:500],
            "url": url[:1000],
            "source": (item.findtext("source") or "Yahoo Finance")[:100],
            "snippet": (item.findtext("description") or "")[:2000],
            "published_at": _parse_rss_date(item.findtext("pubDate")),
        })

    return articles


async def fetch_news_for_ticker(ticker: str) -> list[dict]:
    """Fetch news articles for a single ticker from Yahoo Finance RSS."""
    url = YAHOO_RSS_URL.format(ticker=ticker)
    try:
        xml_text = await fetch_text(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; OpenFolio/1.0)"},
            timeout=10,
        )
        articles = _parse_yahoo_rss(xml_text)
        return articles
    except Exception:
        logger.debug("Yahoo RSS failed for %s, trying Google News", ticker)

    # Fallback: Google News RSS
    url2 = GOOGLE_NEWS_RSS_URL.format(ticker=ticker)
    try:
        xml_text = await fetch_text(
            url2,
            headers={"User-Agent": "Mozilla/5.0 (compatible; OpenFolio/1.0)"},
            timeout=10,
        )
        articles = _parse_yahoo_rss(xml_text)  # Same RSS format
        return articles
    except Exception:
        logger.warning("News fetch failed for %s (both sources)", ticker)
        return []


async def fetch_news_for_tickers(tickers: list[str], max_concurrent: int = 5) -> dict[str, list[dict]]:
    """Batch fetch news for multiple tickers with concurrency limit."""
    sem = asyncio.Semaphore(max_concurrent)
    results: dict[str, list[dict]] = {}

    async def _fetch(t: str) -> None:
        async with sem:
            articles = await fetch_news_for_ticker(t)
            results[t] = articles

    await asyncio.gather(*[_fetch(t) for t in tickers], return_exceptions=True)
    return results


async def persist_news(db: AsyncSession, ticker: str, articles: list[dict]) -> int:
    """Insert new articles, skip duplicates. Returns count of new articles."""
    if not articles:
        return 0

    now = utcnow()
    new_count = 0

    for article in articles:
        stmt = pg_insert(NewsArticle).values(
            id=uuid.uuid4(),
            ticker=ticker,
            title=article["title"],
            url=article["url"],
            source=article.get("source"),
            snippet=article.get("snippet"),
            published_at=article.get("published_at"),
            fetched_at=now,
        ).on_conflict_do_nothing(constraint="uq_news_ticker_url")

        result = await db.execute(stmt)
        if result.rowcount > 0:
            new_count += 1

    await db.commit()
    return new_count


async def get_news_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    scope: str = "all",
    limit: int = 50,
) -> list[dict]:
    """Get recent news for a user's portfolio and/or watchlist tickers."""
    tickers: set[str] = set()

    if scope in ("portfolio", "all"):
        pos_q = select(Position.ticker).where(
            Position.user_id == user_id,
            Position.is_active == True,
            Position.shares > 0,
        )
        pos_result = await db.execute(pos_q)
        tickers.update(r[0] for r in pos_result)

    if scope in ("watchlist", "all"):
        wl_q = select(WatchlistItem.ticker).where(
            WatchlistItem.user_id == user_id,
            WatchlistItem.is_active == True,
        )
        wl_result = await db.execute(wl_q)
        tickers.update(r[0] for r in wl_result)

    if not tickers:
        return []

    query = (
        select(NewsArticle)
        .where(NewsArticle.ticker.in_(tickers))
        .order_by(NewsArticle.published_at.desc().nullslast())
        .limit(limit)
    )
    result = await db.execute(query)
    articles = result.scalars().all()

    return [
        {
            "ticker": a.ticker,
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "snippet": a.snippet,
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "ai_summary": a.ai_summary,
            "ai_sentiment": a.ai_sentiment,
        }
        for a in articles
    ]


async def get_news_for_ticker(db: AsyncSession, ticker: str, limit: int = 20) -> list[dict]:
    """Get recent news for a single ticker."""
    query = (
        select(NewsArticle)
        .where(NewsArticle.ticker == ticker.upper())
        .order_by(NewsArticle.published_at.desc().nullslast())
        .limit(limit)
    )
    result = await db.execute(query)
    articles = result.scalars().all()

    return [
        {
            "title": a.title,
            "url": a.url,
            "publishedDate": a.published_at.isoformat() if a.published_at else None,
            "site": a.source,
            "text": a.snippet,
            "ai_summary": a.ai_summary,
            "ai_sentiment": a.ai_sentiment,
        }
        for a in articles
    ]


async def cleanup_old_news(db: AsyncSession, retention_days: int = 30) -> int:
    """Delete articles older than retention_days."""
    cutoff = utcnow() - timedelta(days=retention_days)
    result = await db.execute(
        delete(NewsArticle).where(NewsArticle.fetched_at < cutoff)
    )
    await db.commit()
    return result.rowcount
