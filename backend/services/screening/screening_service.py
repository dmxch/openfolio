"""Orchestrates screening scan: runs all scrapers, computes scores, persists results."""
import asyncio
import logging
import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.screening import ScreeningResult, ScreeningScan
from services.screening.finra_short_service import fetch_short_trends
from services.screening.openinsider_scraper import fetch_cluster_buys, fetch_large_buys
from services.screening.sec_buyback_service import fetch_buybacks

logger = logging.getLogger(__name__)

# Score weights
WEIGHT_CLUSTER_BUY = 3
WEIGHT_BUYBACK = 2
WEIGHT_LARGE_BUY = 1
WEIGHT_SHORT_TREND = 1

# Thresholds
SHORT_TREND_MIN_CHANGE = 20.0  # % increase in short ratio over 14 days


async def _update_step(db: AsyncSession, scan: ScreeningScan, source: str, status: str, count: int | None = None) -> None:
    """Update a step in the scan progress."""
    steps = list(scan.steps or [])
    for step in steps:
        if step["source"] == source:
            step["status"] = status
            if count is not None:
                step["count"] = count
            break
    scan.steps = steps
    await db.commit()


async def run_scan(db: AsyncSession, scan_id: uuid.UUID) -> None:
    """Execute a full screening scan."""
    scan = await db.get(ScreeningScan, scan_id)
    if not scan:
        return

    scan.status = "running"
    scan.steps = [
        {"source": "finra", "label": "FINRA Short Volume", "status": "pending", "count": None},
        {"source": "openinsider_cluster", "label": "OpenInsider Cluster Buys", "status": "pending", "count": None},
        {"source": "openinsider_large", "label": "OpenInsider Grosse Käufe", "status": "pending", "count": None},
        {"source": "sec_buyback", "label": "SEC Buyback-Ankündigungen", "status": "pending", "count": None},
    ]
    await db.commit()

    # --- Run scrapers concurrently ---
    # Start FINRA (takes longest)
    await _update_step(db, scan, "finra", "running")
    finra_task = asyncio.create_task(fetch_short_trends())

    # Start OpenInsider cluster
    await _update_step(db, scan, "openinsider_cluster", "running")
    cluster_task = asyncio.create_task(fetch_cluster_buys())

    # Start OpenInsider large buys
    await _update_step(db, scan, "openinsider_large", "running")
    large_task = asyncio.create_task(fetch_large_buys())

    # Start SEC buybacks
    await _update_step(db, scan, "sec_buyback", "running")
    buyback_task = asyncio.create_task(fetch_buybacks())

    # Gather results
    short_trends, cluster_buys, large_buys, buybacks = await asyncio.gather(
        finra_task, cluster_task, large_task, buyback_task,
        return_exceptions=True,
    )

    # Handle exceptions
    if isinstance(short_trends, Exception):
        logger.error("FINRA failed: %s", short_trends)
        await _update_step(db, scan, "finra", "error")
        short_trends = {}
    else:
        await _update_step(db, scan, "finra", "done", len(short_trends))

    if isinstance(cluster_buys, Exception):
        logger.error("OpenInsider cluster failed: %s", cluster_buys)
        await _update_step(db, scan, "openinsider_cluster", "error")
        cluster_buys = []
    else:
        await _update_step(db, scan, "openinsider_cluster", "done", len(cluster_buys))

    if isinstance(large_buys, Exception):
        logger.error("OpenInsider large failed: %s", large_buys)
        await _update_step(db, scan, "openinsider_large", "error")
        large_buys = []
    else:
        await _update_step(db, scan, "openinsider_large", "done", len(large_buys))

    if isinstance(buybacks, Exception):
        logger.error("SEC buyback failed: %s", buybacks)
        await _update_step(db, scan, "sec_buyback", "error")
        buybacks = []
    else:
        await _update_step(db, scan, "sec_buyback", "done", len(buybacks))

    # --- Aggregate signals per ticker ---
    ticker_signals: dict[str, dict] = {}

    def _ensure(ticker: str, name: str = "", sector: str = "") -> dict:
        if ticker not in ticker_signals:
            ticker_signals[ticker] = {
                "name": name,
                "sector": sector,
                "score": 0,
                "signals": {},
            }
        elif name and not ticker_signals[ticker]["name"]:
            ticker_signals[ticker]["name"] = name
        return ticker_signals[ticker]

    # Cluster buys (weight 3)
    for trade in cluster_buys:
        t = trade["ticker"]
        entry = _ensure(t, trade.get("company", ""), trade.get("industry", ""))
        if "insider_cluster" not in entry["signals"]:
            entry["signals"]["insider_cluster"] = {
                "insider_count": trade.get("insider_count", 2),
                "total_value": trade.get("value", 0),
                "trade_date": trade.get("trade_date", ""),
            }
            entry["score"] += WEIGHT_CLUSTER_BUY

    # Large individual buys (weight 1) — only if not already a cluster
    for trade in large_buys:
        t = trade["ticker"]
        entry = _ensure(t, trade.get("company", ""), trade.get("industry", ""))
        if "insider_cluster" not in entry["signals"] and "large_buy" not in entry["signals"]:
            entry["signals"]["large_buy"] = {
                "value": trade.get("value", 0),
                "price": trade.get("price", 0),
                "trade_date": trade.get("trade_date", ""),
            }
            entry["score"] += WEIGHT_LARGE_BUY

    # Buybacks (weight 2)
    for bb in buybacks:
        t = bb["ticker"]
        entry = _ensure(t, bb.get("company", ""))
        if "buyback" not in entry["signals"]:
            entry["signals"]["buyback"] = {
                "filing_date": bb.get("filing_date", ""),
            }
            entry["score"] += WEIGHT_BUYBACK

    # Short trend (weight 1) — only for tickers already flagged OR with extreme trend
    for sym, trend in short_trends.items():
        if trend["change_pct"] >= SHORT_TREND_MIN_CHANGE:
            if sym in ticker_signals or trend["change_pct"] >= 50.0:
                entry = _ensure(sym)
                if "short_trend" not in entry["signals"]:
                    entry["signals"]["short_trend"] = trend
                    entry["score"] += WEIGHT_SHORT_TREND

    # --- Filter: only keep tickers with score >= 1 ---
    scored = {t: data for t, data in ticker_signals.items() if data["score"] >= 1}

    # --- Delete old results for this scan and persist new ones ---
    await db.execute(delete(ScreeningResult).where(ScreeningResult.scan_id == scan_id))

    results_to_add = []
    for ticker, data in scored.items():
        results_to_add.append(ScreeningResult(
            scan_id=scan_id,
            ticker=ticker,
            name=data["name"],
            sector=data.get("sector", ""),
            score=data["score"],
            signals=data["signals"],
        ))

    db.add_all(results_to_add)

    scan.status = "completed"
    scan.finished_at = utcnow()
    scan.result_count = len(results_to_add)
    await db.commit()

    logger.info("Screening scan %s completed: %d results", scan_id, len(results_to_add))
