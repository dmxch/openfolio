"""Background worker for scheduled jobs (separated from API process).

Runs APScheduler with:
- Intraday price refresh (every 60s during market hours, 15min otherwise)
- Daily full refresh (7:00 AM Zurich) with macro, earnings, snapshots
- Token cleanup (3:00 AM Zurich)
- Startup warmup + initial refresh
"""

import asyncio
import logging
import signal
from datetime import time, datetime
from zoneinfo import ZoneInfo

import yf_patch  # noqa: F401 — must be first to patch yfinance

from logging_config import setup_logging
setup_logging("worker")
logger = logging.getLogger("worker")

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from db import async_session, engine
from services.cache_service import refresh_cache, _save_refresh_state_to_db


import pathlib

SCHEDULER_ADVISORY_LOCK_ID = 123456789
TZ_ZURICH = ZoneInfo("Europe/Zurich")
HEARTBEAT_FILE = pathlib.Path("/app/data/worker_heartbeat")
HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
HEARTBEAT_FILE.touch(exist_ok=True)


def is_market_hours() -> bool:
    """Check if US markets are open (15:30-22:00 CET, weekdays)."""
    now = datetime.now(TZ_ZURICH)
    if now.weekday() >= 5:
        return False
    return time(15, 30) <= now.time() <= time(22, 0)


def is_extended_hours() -> bool:
    """Check if pre/post-market or European markets are active (8:00-23:00 CET, weekdays)."""
    now = datetime.now(TZ_ZURICH)
    if now.weekday() >= 5:
        return False
    return time(8, 0) <= now.time() <= time(23, 0)


async def price_refresh():
    """Lightweight price-only refresh (no macro, no snapshots). Skips outside extended hours."""
    # Write heartbeat for Docker health check (every 60s, even when skipping refresh)
    HEARTBEAT_FILE.touch(exist_ok=True)
    if not is_extended_hours():
        return
    async with async_session() as db:
        lock_result = await db.execute(text("SELECT pg_try_advisory_lock(:lid)"), {"lid": SCHEDULER_ADVISORY_LOCK_ID})
        acquired = lock_result.scalar()
        if not acquired:
            return

        try:
            result = await asyncio.wait_for(refresh_cache(db, silent=True), timeout=120)
            tickers = result.get("tickers_refreshed", 0)
            if tickers > 0:
                logger.info(f"Price refresh: {tickers} tickers updated")
        except asyncio.TimeoutError:
            logger.error("Price refresh timed out")
            await _save_refresh_state_to_db({
                "refreshing": False, "started_at": None, "ticker_count": 0,
                "status": "timeout", "last_refresh": None,
                "errors": ["Refresh abgebrochen nach 120s"],
            })
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:lid)"), {"lid": SCHEDULER_ADVISORY_LOCK_ID})

    # Check price alerts after every refresh
    await _check_alerts()


async def daily_refresh():
    """Full daily refresh: prices + macro + earnings + snapshots."""
    async with async_session() as db:
        lock_result = await db.execute(text("SELECT pg_try_advisory_lock(:lid)"), {"lid": SCHEDULER_ADVISORY_LOCK_ID})
        acquired = lock_result.scalar()
        if not acquired:
            logger.info("Daily refresh skipped — another instance holds the advisory lock")
            return

        try:
            result = await asyncio.wait_for(refresh_cache(db), timeout=120)
        except asyncio.TimeoutError:
            logger.error("Daily refresh timed out after 120s")
            await _save_refresh_state_to_db({
                "refreshing": False, "started_at": None, "ticker_count": 0,
                "status": "timeout", "last_refresh": None,
                "errors": ["Refresh abgebrochen nach 120s"],
            })
            return
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:lid)"), {"lid": SCHEDULER_ADVISORY_LOCK_ID})
        logger.info(f"Daily refresh: {result.get('tickers_refreshed', 0)} tickers")

    # Post-refresh tasks
    await _refresh_macro_indicators()
    await _refresh_earnings_dates()
    await _check_alerts()
    await _record_snapshot()


async def _refresh_macro_indicators():
    try:
        from services.macro_indicators_service import persist_indicators_async
        async with async_session() as db:
            await persist_indicators_async(db)
            logger.info("Macro indicators refreshed")
    except Exception as e:
        logger.warning(f"Macro indicators refresh failed: {e}")


async def _refresh_earnings_dates():
    try:
        from services.earnings_service import get_next_earnings_date
        from sqlalchemy import select
        from models.position import Position

        async with async_session() as db:
            result = await db.execute(
                select(Position).where(
                    Position.is_active == True,
                    Position.shares > 0,
                    Position.type.in_(["stock", "etf"]),
                )
            )
            positions = result.scalars().all()

            # Parallel earnings fetch (max 5 concurrent to avoid rate limits)
            sem = asyncio.Semaphore(5)
            async def _fetch_one(pos):
                async with sem:
                    yf_ticker = pos.yfinance_ticker or pos.ticker
                    return pos, await asyncio.to_thread(get_next_earnings_date, yf_ticker)

            results = await asyncio.gather(*[_fetch_one(p) for p in positions], return_exceptions=True)
            count = 0
            for r in results:
                if isinstance(r, Exception):
                    continue
                pos, ed = r
                if ed:
                    pos.next_earnings_date = ed
                    count += 1
            await db.commit()
            logger.info(f"Earnings refresh: {count}/{len(positions)} dates updated")
    except Exception as e:
        logger.warning(f"Earnings refresh failed: {e}")


async def _check_alerts():
    try:
        from services.price_alert_service import check_price_alerts, send_alert_emails
        async with async_session() as db:
            triggered = await check_price_alerts(db)
            if triggered:
                logger.info(f"Price alerts triggered: {len(triggered)}")
                await send_alert_emails(triggered)
    except Exception as e:
        logger.warning(f"Price alert check failed: {e}")


async def _record_snapshot():
    try:
        from services.snapshot_service import record_daily_snapshot
        async with async_session() as db:
            count = await record_daily_snapshot(db)
            logger.info(f"Portfolio snapshots recorded: {count}")
    except Exception as e:
        logger.warning(f"Snapshot recording failed: {e}")


async def _check_breakout_alerts():
    """Check watchlist tickers for Donchian breakouts and send email alerts."""
    try:
        from services.breakout_alert_service import check_breakout_alerts
        async with async_session() as db:
            await check_breakout_alerts(db)
    except Exception as e:
        logger.warning(f"Breakout alert check failed: {e}")


async def _check_etf_200dma_alerts():
    """Check broad index ETFs for below-200-DMA condition and send email alerts."""
    try:
        from services.etf_200dma_alert_service import check_etf_200dma_alerts
        async with async_session() as db:
            await check_etf_200dma_alerts(db)
    except Exception as e:
        logger.warning(f"ETF 200-DMA alert check failed: {e}")


async def _fetch_news():
    """Fetch news for all portfolio + watchlist tickers across all users."""
    try:
        from models.position import Position
        from models.watchlist import WatchlistItem
        from services.news_service import fetch_news_for_tickers, persist_news, cleanup_old_news
        from sqlalchemy import select as sa_select

        async with async_session() as db:
            pos_result = await db.execute(
                sa_select(Position.ticker).where(Position.is_active == True, Position.shares > 0)
            )
            wl_result = await db.execute(
                sa_select(WatchlistItem.ticker).where(WatchlistItem.is_active == True)
            )
            all_tickers = list(set(
                [r[0] for r in pos_result] + [r[0] for r in wl_result]
            ))

            if not all_tickers:
                return

            results = await fetch_news_for_tickers(all_tickers)
            total_new = 0
            for ticker, articles in results.items():
                total_new += await persist_news(db, ticker, articles)

            deleted = await cleanup_old_news(db)
            logger.info("News fetch: %d new articles for %d tickers, %d old removed", total_new, len(all_tickers), deleted)
    except Exception as e:
        logger.warning("News fetch failed: %s", e)


async def cleanup_expired_tokens():
    from datetime import timedelta
    from dateutils import utcnow
    from sqlalchemy import delete as sa_delete
    from models.user import RefreshToken
    from models.password_reset_token import PasswordResetToken

    async with async_session() as db:
        now = utcnow()
        cutoff = now - timedelta(days=7)

        result = await db.execute(
            sa_delete(RefreshToken).where(
                (RefreshToken.revoked == True) | (RefreshToken.expires_at < now),
                RefreshToken.created_at < cutoff,
            )
        )
        rt_deleted = result.rowcount

        result = await db.execute(
            sa_delete(PasswordResetToken).where(
                (PasswordResetToken.used == True) | (PasswordResetToken.expires_at < now)
            )
        )
        prt_deleted = result.rowcount

        await db.commit()
        logger.info(f"Token cleanup: {rt_deleted} refresh tokens, {prt_deleted} reset tokens removed")


async def warmup_market_cache():
    """Pre-load sector rotation and market climate into cache."""
    from services.sector_analyzer import get_sector_rotation
    from services.market_analyzer import get_market_climate

    try:
        await asyncio.to_thread(get_sector_rotation)
        logger.info("Cache warmup: sector rotation loaded")
    except Exception as e:
        logger.warning(f"Cache warmup: sector rotation failed: {e}")

    try:
        await asyncio.to_thread(get_market_climate)
        logger.info("Cache warmup: market climate loaded")
    except Exception as e:
        logger.warning(f"Cache warmup: market climate failed: {e}")


async def startup_refresh():
    """Initial refresh after a short delay."""
    await asyncio.sleep(3)
    await warmup_market_cache()

    try:
        from services.cache_service import seed_historical_prices
        async with async_session() as db:
            await seed_historical_prices(db)
    except Exception as e:
        logger.warning(f"Historical seed failed: {e}")

    await daily_refresh()


async def main():
    # DB health check
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Database connected")

    # Start scheduler
    scheduler = AsyncIOScheduler()

    # Daily full refresh at 7:00 AM Zurich (macro, earnings, snapshots)
    scheduler.add_job(
        daily_refresh,
        CronTrigger(hour=7, minute=0, timezone="Europe/Zurich"),
        id="daily_refresh",
    )

    # Intraday price refresh during extended hours (every 60s)
    scheduler.add_job(
        price_refresh,
        IntervalTrigger(seconds=60),
        id="intraday_refresh",
        max_instances=1,
    )

    # Token cleanup at 3:00 AM
    scheduler.add_job(
        cleanup_expired_tokens,
        CronTrigger(hour=3, minute=0, timezone="Europe/Zurich"),
        id="token_cleanup",
    )

    # Breakout alerts at 22:30 CET (after US market close)
    scheduler.add_job(
        _check_breakout_alerts,
        CronTrigger(hour=22, minute=30, timezone="Europe/Zurich"),
        id="breakout_alerts",
    )

    # ETF 200-DMA alerts at 22:35 CET (after US market close)
    scheduler.add_job(
        _check_etf_200dma_alerts,
        CronTrigger(hour=22, minute=35, timezone="Europe/Zurich"),
        id="etf_200dma_alerts",
    )

    # News fetch at 06:30 and 18:00 CET
    scheduler.add_job(
        _fetch_news,
        CronTrigger(hour=6, minute=30, timezone="Europe/Zurich"),
        id="news_fetch_morning",
    )
    scheduler.add_job(
        _fetch_news,
        CronTrigger(hour=18, minute=0, timezone="Europe/Zurich"),
        id="news_fetch_afternoon",
    )

    scheduler.start()
    logger.info("Scheduler started (daily 07:00 + intraday every 60s + breakout alerts 22:30 + ETF 200-DMA 22:35 + news 06:30/18:00)")

    # Run initial refresh
    asyncio.create_task(startup_refresh())

    # Keep running until signal
    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    await stop_event.wait()

    scheduler.shutdown(wait=False)
    await engine.dispose()
    logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
