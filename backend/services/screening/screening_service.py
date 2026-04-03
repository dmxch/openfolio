"""Orchestrates screening scan: runs all scrapers, computes scores, persists results."""
import asyncio
import logging
import uuid
from typing import Any, Callable, Coroutine

from dateutils import utcnow
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.screening import ScreeningResult, ScreeningScan
from services.screening.activist_tracker import fetch_activist_positions
from services.screening.capitoltrades_scraper import fetch_congressional_buys
from services.screening.dataroma_scraper import fetch_superinvestor_data
from services.screening.finra_short_service import fetch_short_trends
from services.screening.openinsider_scraper import fetch_cluster_buys, fetch_large_buys
from services.screening.ftd_service import fetch_ftd_data
from services.screening.sec_buyback_service import fetch_buybacks
from services.screening.unusual_volume_service import enrich_unusual_volume

logger = logging.getLogger(__name__)

# Score weights
WEIGHT_CLUSTER_BUY = 3
WEIGHT_SUPERINVESTOR = 2
WEIGHT_BUYBACK = 2
WEIGHT_LARGE_BUY = 1
WEIGHT_CONGRESSIONAL = 1
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


async def _run_source(
    db: AsyncSession,
    scan: ScreeningScan,
    source: str,
    fetch_fn: Callable[[], Coroutine],
    lock: asyncio.Lock,
) -> Any:
    """Run a single scraper and update progress when it completes."""
    try:
        result = await fetch_fn()
        count = len(result) if isinstance(result, (list, dict)) else 0
        # For tuple results (dataroma returns tuple), sum both parts
        if isinstance(result, tuple):
            count = sum(len(r) for r in result if isinstance(r, list))
        async with lock:
            await _update_step(db, scan, source, "done", count)
        return result
    except Exception as e:
        logger.error("Source %s failed: %s", source, e)
        async with lock:
            await _update_step(db, scan, source, "error")
        return e


async def run_scan(db: AsyncSession, scan_id: uuid.UUID) -> None:
    """Execute a full screening scan with all 7 data sources."""
    scan = await db.get(ScreeningScan, scan_id)
    if not scan:
        return

    scan.status = "running"
    scan.steps = [
        {"source": "openinsider_cluster", "label": "OpenInsider Cluster Buys", "status": "running", "count": None},
        {"source": "openinsider_large", "label": "OpenInsider Grosse Käufe", "status": "running", "count": None},
        {"source": "sec_buyback", "label": "SEC Buyback-Ankündigungen", "status": "running", "count": None},
        {"source": "capitoltrades", "label": "Capitol Trades (Kongress)", "status": "running", "count": None},
        {"source": "dataroma", "label": "Dataroma Superinvestoren", "status": "running", "count": None},
        {"source": "finra", "label": "FINRA Short Volume", "status": "running", "count": None},
        {"source": "activist", "label": "Aktivisten-Tracking (SEC)", "status": "running", "count": None},
        {"source": "ftd", "label": "SEC Fails-to-Deliver", "status": "running", "count": None},
        {"source": "volume", "label": "Unusual Volume", "status": "pending", "count": None},
    ]
    await db.commit()

    # Lock serializes DB writes so concurrent completions don't conflict
    db_lock = asyncio.Lock()

    # Run primary sources concurrently — each updates its own step when done
    results = await asyncio.gather(
        _run_source(db, scan, "openinsider_cluster", fetch_cluster_buys, db_lock),
        _run_source(db, scan, "openinsider_large", fetch_large_buys, db_lock),
        _run_source(db, scan, "sec_buyback", fetch_buybacks, db_lock),
        _run_source(db, scan, "capitoltrades", fetch_congressional_buys, db_lock),
        _run_source(db, scan, "dataroma", fetch_superinvestor_data, db_lock),
        _run_source(db, scan, "finra", fetch_short_trends, db_lock),
        _run_source(db, scan, "activist", fetch_activist_positions, db_lock),
        _run_source(db, scan, "ftd", fetch_ftd_data, db_lock),
    )

    cluster_buys = results[0] if not isinstance(results[0], Exception) else []
    large_buys = results[1] if not isinstance(results[1], Exception) else []
    buybacks = results[2] if not isinstance(results[2], Exception) else []
    congress_buys = results[3] if not isinstance(results[3], Exception) else []
    dataroma_result = results[4] if not isinstance(results[4], Exception) else ([], [])
    short_trends = results[5] if not isinstance(results[5], Exception) else {}
    activist_positions = results[6] if not isinstance(results[6], Exception) else []
    ftd_data = results[7] if not isinstance(results[7], Exception) else {}

    # Unpack dataroma tuple
    if isinstance(dataroma_result, tuple) and len(dataroma_result) == 2:
        superinvestor_buys, grand_portfolio = dataroma_result
    else:
        superinvestor_buys, grand_portfolio = [], []

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

    # 1. Cluster buys (weight 3)
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

    # 2. Superinvestor / Activist (weight 2)
    portfolio_tickers = set()
    for holding in grand_portfolio:
        t = holding.get("ticker", "")
        if t and holding.get("num_investors", 0) >= 3:
            entry = _ensure(t, holding.get("company", ""))
            if "superinvestor" not in entry["signals"]:
                entry["signals"]["superinvestor"] = {
                    "source": "dataroma_portfolio",
                    "num_investors": holding.get("num_investors", 0),
                }
                entry["score"] += WEIGHT_SUPERINVESTOR
                portfolio_tickers.add(t)

    for buy in superinvestor_buys:
        t = buy.get("ticker", "")
        if not t or t in portfolio_tickers:
            continue
        entry = _ensure(t, buy.get("company", ""))
        if "superinvestor" not in entry["signals"]:
            entry["signals"]["superinvestor"] = {
                "source": "dataroma_realtime",
                "investor": buy.get("investor", ""),
                "value": buy.get("value", 0),
            }
            entry["score"] += WEIGHT_SUPERINVESTOR

    for pos in activist_positions:
        t = pos.get("ticker", "")
        if not t:
            continue
        entry = _ensure(t, pos.get("company", ""))
        if "activist" not in entry["signals"]:
            entry["signals"]["activist"] = {
                "investor": pos.get("investor", ""),
                "form": pos.get("form", ""),
                "filing_date": pos.get("filing_date", ""),
            }
            if "superinvestor" not in entry["signals"]:
                entry["score"] += WEIGHT_SUPERINVESTOR

    # 3. Buybacks (weight 2)
    for bb in buybacks:
        t = bb["ticker"]
        entry = _ensure(t, bb.get("company", ""))
        if "buyback" not in entry["signals"]:
            entry["signals"]["buyback"] = {
                "filing_date": bb.get("filing_date", ""),
            }
            entry["score"] += WEIGHT_BUYBACK

    # 4. Large individual buys (weight 1)
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

    # 5. Congressional buys (weight 1)
    for cb in congress_buys:
        t = cb.get("ticker", "")
        if not t:
            continue
        entry = _ensure(t, cb.get("company", ""))
        if "congressional" not in entry["signals"]:
            entry["signals"]["congressional"] = {
                "source": "capitoltrades",
            }
            entry["score"] += WEIGHT_CONGRESSIONAL

    # 6. Short trend (weight 1)
    for sym, trend in short_trends.items():
        if trend["change_pct"] >= SHORT_TREND_MIN_CHANGE:
            if sym in ticker_signals or trend["change_pct"] >= 50.0:
                entry = _ensure(sym)
                if "short_trend" not in entry["signals"]:
                    entry["signals"]["short_trend"] = trend
                    entry["score"] += WEIGHT_SHORT_TREND

    # 7. Fails-to-Deliver (bonus warning, no score points)
    for sym, ftd in ftd_data.items():
        if sym in ticker_signals:
            entry = ticker_signals[sym]
            entry["signals"]["ftd"] = ftd

    # --- Filter: only keep tickers with score >= 1 ---
    scored = {t: data for t, data in ticker_signals.items() if data["score"] >= 1}

    # 8. Unusual Volume enrichment — only for scored tickers (per-ticker via yfinance)
    async with db_lock:
        await _update_step(db, scan, "volume", "running")

    try:
        scored_tickers = list(scored.keys())
        volume_data = await enrich_unusual_volume(scored_tickers)
        for sym, vol in volume_data.items():
            if sym in scored:
                scored[sym]["signals"]["unusual_volume"] = vol
                scored[sym]["score"] += 1  # +1 bonus point
        async with db_lock:
            await _update_step(db, scan, "volume", "done", len(volume_data))
    except Exception as e:
        logger.error("Unusual volume failed: %s", e)
        async with db_lock:
            await _update_step(db, scan, "volume", "error")

    # --- Delete old results for this scan and persist new ones ---
    await db.execute(delete(ScreeningResult).where(ScreeningResult.scan_id == scan_id))

    results_to_add = []
    for ticker, data in scored.items():
        data["score"] = min(data["score"], 10)
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
