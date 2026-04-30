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
            from services.cache_service import _load_refresh_state_from_db
            prev = await _load_refresh_state_from_db()
            await _save_refresh_state_to_db({
                "refreshing": False, "started_at": None, "ticker_count": 0,
                "status": "timeout", "last_refresh": prev.get("last_refresh"),
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
            from services.cache_service import _load_refresh_state_from_db
            prev = await _load_refresh_state_from_db()
            await _save_refresh_state_to_db({
                "refreshing": False, "started_at": None, "ticker_count": 0,
                "status": "timeout", "last_refresh": prev.get("last_refresh"),
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


async def _check_rule_alerts():
    """Run generate_alerts per user and email a digest of rule-based alerts."""
    try:
        from services.rule_alert_service import check_rule_alerts
        async with async_session() as db:
            await check_rule_alerts(db)
    except Exception as e:
        logger.warning(f"Rule-Alert check failed: {e}")


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


async def cot_weekly_refresh():
    """Pull CFTC Commitments of Traders snapshots (isolated macro panel).

    Saturday 09:00 Europe/Zurich — CFTC publishes on Fridays, Saturday is safe.
    See SCOPE_SMART_MONEY_V4.md Block 1.
    """
    try:
        from services.macro.cot_service import refresh_cot_snapshots
        result = await refresh_cot_snapshots()
        logger.info(
            "COT weekly refresh: inserted=%s rows_parsed=%s status=%s errors=%s",
            result.get("inserted"),
            result.get("rows_parsed"),
            result.get("status"),
            len(result.get("errors", [])),
        )
    except Exception as exc:
        # AC-4: never crash the worker — keep last known snapshot intact
        logger.warning(f"COT weekly refresh failed: {exc}")


async def refresh_13f_holdings_job():
    """Daily check for new 13F-HR filings from tracked superinvestor funds."""
    try:
        from services.screening.sec_13f_service import refresh_13f_holdings
        async with async_session() as db:
            result = await refresh_13f_holdings(db)
            logger.info("13F refresh: %s", result)
    except Exception:
        logger.exception("13F refresh failed")


async def industries_refresh_job():
    """Daily snapshot of TradingView US-industries (branchen-rotation)."""
    try:
        from services.tradingview_industries_service import refresh_industries
        async with async_session() as db:
            result = await refresh_industries(db)
            logger.info("industries refresh: %s", result)
    except Exception:
        # Never wipe existing snapshot on transient scrape errors.
        logger.exception("industries refresh failed")


async def etf_holdings_refresh_job():
    """Wöchentlich Mo 04:30 CET: refresh User-ETF-Holdings via FMP für
    Konzentrations-Banner (Phase B + Phase 1.1). Idempotent durch TTL-Check
    pro ETF. Per-ETF-Failures werden geloggt, andere ETFs laufen weiter.

    Phase 1.1: Nach dem Refresh wird ein Post-Refresh-Coverage-Check
    ausgeführt. Wenn FMP einen neuen Ticker reinrotiert (recent IPO,
    M&A-Resultat), der nicht in `ticker_industries`/`SECTOR_OVERRIDES`
    klassifiziert ist → Coverage degradiert silent. Der Check schreibt
    eine Warning mit Liste der unclassified Tickers ins Log, damit der
    Operator das in den nächsten SECTOR_OVERRIDES-Sweep aufnehmen kann.
    """
    try:
        from services.etf_holdings_service import refresh_all_user_etfs
        async with async_session() as db:
            result = await refresh_all_user_etfs(db)
            logger.info("etf_holdings_refresh: %s", result)
    except Exception:
        logger.exception("etf_holdings_refresh failed")
        return

    # Post-Refresh-Coverage-Check (Phase 1.1)
    try:
        await _check_sector_coverage_after_refresh()
    except Exception:
        logger.exception("post-refresh sector-coverage check failed")


async def _check_sector_coverage_after_refresh():
    """Nach etf_holdings-Refresh: prüfe Sektor-Coverage pro ETF.
    Schreibt Warning wenn unclassified Tickers existieren — gegen Silent-Decay.
    """
    from sqlalchemy import select, distinct
    from models.etf_holding import EtfHolding
    from services.sector_classification_service import classify_tickers_bulk
    from services.analysis_config import SECTOR_COVERAGE_MIN_PCT

    async with async_session() as db:
        # Distinct holdings pro ETF
        rows = (await db.execute(
            select(EtfHolding.etf_ticker, EtfHolding.holding_ticker, EtfHolding.weight_pct)
        )).all()
        if not rows:
            return

        # Bulk-Klassifikation aller distinct holding_tickers
        all_tickers = list({r[1] for r in rows})
        sectors = classify_tickers_bulk(all_tickers)

        # Coverage pro ETF berechnen
        per_etf: dict[str, dict] = {}
        for etf_t, hold_t, weight in rows:
            entry = per_etf.setdefault(etf_t, {"classified": 0.0, "unclassified": 0.0, "unclass_tickers": []})
            w = float(weight)
            if sectors.get(hold_t) is None:
                entry["unclassified"] += w
                entry["unclass_tickers"].append((hold_t, w))
            else:
                entry["classified"] += w

        for etf_t, data in per_etf.items():
            total = data["classified"] + data["unclassified"]
            if total <= 0:
                continue
            classified_pct = data["classified"] / total * 100.0
            if classified_pct < SECTOR_COVERAGE_MIN_PCT:
                # Warning mit den größten unclassified Tickers
                top_unclass = sorted(data["unclass_tickers"], key=lambda x: -x[1])[:10]
                top_str = ", ".join(f"{t}({w:.2f}%)" for t, w in top_unclass)
                logger.warning(
                    "sector-coverage degraded: %s at %.1f%% (threshold %.0f%%). "
                    "Add to SECTOR_OVERRIDES: %s",
                    etf_t, classified_pct, SECTOR_COVERAGE_MIN_PCT, top_str,
                )


async def sector_rotation_stale_check_job():
    """Weekly check: flag ticker_industries rows whose industry_name no longer
    exists in the latest TradingView industries snapshot. Emails the operator
    when mismatches are present so silent decay doesn't accumulate over months.
    """
    try:
        from services.screening.sector_rotation_stale_check import run_stale_check_with_alert
        async with async_session() as db:
            report = await run_stale_check_with_alert(db)
            logger.info("sector-rotation stale-check: %s", report)
    except Exception:
        logger.exception("sector-rotation stale-check failed")


async def cleanup_old_screening_scans():
    """Delete screening scans older than 365 days. Cascades to ScreeningResult."""
    from datetime import timedelta
    from dateutils import utcnow
    from sqlalchemy import delete as sa_delete
    from models.screening import ScreeningScan

    async with async_session() as db:
        now = utcnow()
        cutoff = now - timedelta(days=365)

        result = await db.execute(
            sa_delete(ScreeningScan).where(ScreeningScan.started_at < cutoff)
        )
        deleted = result.rowcount
        await db.commit()

        if deleted > 0:
            logger.info(f"Screening cleanup: {deleted} scans older than 365 days removed")


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

    # Screening scan cleanup at 04:00 CET (after token cleanup at 03:00)
    scheduler.add_job(
        cleanup_old_screening_scans,
        CronTrigger(hour=4, minute=0, timezone="Europe/Zurich"),
        id="screening_cleanup",
    )

    # CFTC COT weekly refresh — Saturday 09:00 Europe/Zurich (published Fridays)
    scheduler.add_job(
        cot_weekly_refresh,
        CronTrigger(hour=9, minute=0, day_of_week="sat", timezone="Europe/Zurich"),
        id="cot_weekly_refresh",
    )

    # SEC 13F daily check at 08:00 CET (new filings from tracked funds)
    scheduler.add_job(
        refresh_13f_holdings_job,
        CronTrigger(hour=8, minute=0, timezone="Europe/Zurich"),
        id="sec_13f_refresh",
    )

    # TradingView US-industries daily snapshot at 01:30 CET (after US close)
    scheduler.add_job(
        industries_refresh_job,
        CronTrigger(hour=1, minute=30, timezone="Europe/Zurich"),
        id="industries_refresh",
    )

    # ETF-Holdings refresh — wöchentlich Mo 04:30 CET (Phase B Core-Overlap).
    # Idempotent durch TTL-Check (30 Tage) — wenn ein ETF schon frisch ist,
    # wird er übersprungen. Robuster als monatlicher Cron gegen Failures.
    scheduler.add_job(
        etf_holdings_refresh_job,
        CronTrigger(hour=4, minute=30, day_of_week="mon", timezone="Europe/Zurich"),
        id="etf_holdings_refresh",
    )

    # Weekly stale-check on ticker→industry mapping at Monday 06:30 CET
    # (industries_refresh runs daily at 01:30, so on Monday at 06:30 the
    # latest snapshot is fresh and any drift is real, not just lag).
    scheduler.add_job(
        sector_rotation_stale_check_job,
        CronTrigger(hour=6, minute=30, day_of_week="mon", timezone="Europe/Zurich"),
        id="sector_rotation_stale_check",
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

    # Portfolio-rule alert digest at 22:40 CET (after breakout + ETF-200DMA jobs)
    scheduler.add_job(
        _check_rule_alerts,
        CronTrigger(hour=22, minute=40, timezone="Europe/Zurich"),
        id="rule_alerts",
    )

    scheduler.start()
    logger.info("Scheduler started (daily 07:00 + intraday every 60s + breakout alerts 22:30 + ETF 200-DMA 22:35 + rule alerts 22:40)")

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
