"""Branche-rotation classification layer for the Smart-Money screener.

For a scored ticker, look up its TradingView industry and decide whether
the industry is currently in tailwind, headwind, neutral, concentrated
(single-stock-dominated) or unknown (ticker not in our mapping). The
classification yields an additive score bonus that is summed into the
ticker's final screener score and persisted on ``ScreeningResult``.

Design notes:
- ``classify_ticker`` is a pure function: all data is passed in as
  pre-loaded maps + a precomputed median. This makes the rule logic
  unit-testable without any DB plumbing and avoids N round-trips in the
  screener (the caller batch-loads once via ``load_classification_inputs``).
- The five regimes are evaluated in a strict priority order — the first
  match wins. This is deliberate: ``concentrated`` overrides any
  performance-based tailwind because a single-stock-dominated industry's
  performance is mostly that one stock's, not a real sector signal.
- ``unknown`` fires when the ticker has no row in ``ticker_industries``
  (e.g. SIX-CH symbols that the US-only TradingView scan does not see).
  No bonus is applied — explicit non-neutrality documented as Phase-2
  work in the design plan.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.market_industry import MarketIndustry
from models.ticker_industry import TickerIndustry
from services.screening import sector_rotation_config as cfg

logger = logging.getLogger(__name__)


# Allowed momentum strings — used by API validation and DB enum-style checks.
MOMENTUM_TAILWIND = "tailwind"
MOMENTUM_HEADWIND = "headwind"
MOMENTUM_NEUTRAL = "neutral"
MOMENTUM_CONCENTRATED = "concentrated"
MOMENTUM_UNKNOWN = "unknown"

VALID_MOMENTUM_VALUES = frozenset({
    MOMENTUM_TAILWIND,
    MOMENTUM_HEADWIND,
    MOMENTUM_NEUTRAL,
    MOMENTUM_CONCENTRATED,
    MOMENTUM_UNKNOWN,
})


@dataclass(frozen=True)
class SectorClassification:
    industry_name: str | None
    momentum: str
    sector_bonus: int


@dataclass(frozen=True)
class ClassificationInputs:
    """Bundle returned by ``load_classification_inputs`` for batched scoring."""
    ticker_industry_map: dict[str, str]
    industry_metrics_map: dict[str, dict]
    median_perf_1m: Decimal | None
    snapshot_age_seconds: float | None  # for stale-data logging


def classify_ticker(
    ticker: str,
    ticker_industry_map: dict[str, str],
    industry_metrics_map: dict[str, dict],
    median_perf_1m: Decimal | None,
) -> SectorClassification:
    """Decide tailwind/headwind/neutral/concentrated/unknown for one ticker.

    Rule order (first match wins):
      1. Ticker not in ``ticker_industry_map`` → unknown (bonus 0)
      2. Industry metrics missing or median unavailable → unknown
      3. Industry concentrated (top1_weight > X OR effective_n < Y) → concentrated (bonus 0)
      4. Tailwind: perf_1m > median AND perf_1m > 0 AND perf_3m > 0 AND rvol > X → +WEIGHT_SECTOR_TAILWIND
      5. Headwind: perf_1m < median AND perf_1m < 0 AND rvol < Y → +WEIGHT_SECTOR_HEADWIND (default 0)
      6. Otherwise neutral (bonus 0)
    """
    industry = ticker_industry_map.get(ticker.upper())
    if industry is None:
        return SectorClassification(None, MOMENTUM_UNKNOWN, 0)

    metrics = industry_metrics_map.get(industry)
    if metrics is None or median_perf_1m is None:
        return SectorClassification(industry, MOMENTUM_UNKNOWN, 0)

    top1_weight = metrics.get("top1_weight")
    effective_n = metrics.get("effective_n")
    if (top1_weight is not None and top1_weight > cfg.TOP1_CONCENTRATION_THRESHOLD) or (
        effective_n is not None and effective_n < cfg.EFFECTIVE_N_CONCENTRATION_THRESHOLD
    ):
        return SectorClassification(industry, MOMENTUM_CONCENTRATED, 0)

    perf_1m = metrics.get("perf_1m")
    perf_3m = metrics.get("perf_3m")
    rvol = metrics.get("rvol_20d")

    # Tailwind: needs all four conditions met (perf+rvol+absolute-floors)
    if (
        perf_1m is not None
        and perf_3m is not None
        and rvol is not None
        and perf_1m > median_perf_1m
        and perf_1m > 0
        and perf_3m > 0
        and rvol > cfg.RVOL_TAILWIND_THRESHOLD
    ):
        return SectorClassification(industry, MOMENTUM_TAILWIND, cfg.WEIGHT_SECTOR_TAILWIND)

    # Headwind: symmetric definition (1m below median + 1m absolutely negative + low rvol)
    if (
        perf_1m is not None
        and rvol is not None
        and perf_1m < median_perf_1m
        and perf_1m < 0
        and rvol < cfg.RVOL_HEADWIND_THRESHOLD
    ):
        return SectorClassification(industry, MOMENTUM_HEADWIND, cfg.WEIGHT_SECTOR_HEADWIND)

    return SectorClassification(industry, MOMENTUM_NEUTRAL, 0)


async def load_classification_inputs(
    db: AsyncSession,
    tickers: Iterable[str],
) -> ClassificationInputs:
    """Batch-load the data needed to classify a set of tickers.

    Two queries (independent of N tickers):
      1. ticker_industries → ticker→industry map (filtered to scored set)
      2. latest fully-committed market_industries snapshot via MAX(scraped_at)
         → industry→metrics map + median(perf_1m)

    The MAX(scraped_at) read is atomic against the industries-refresh
    transaction (snapshot rows commit together), so we never see a
    partial mid-write state. Tickers not in the map come back as
    ``unknown`` later in ``classify_ticker``.
    """
    upper_tickers = {t.upper() for t in tickers if t}
    if not upper_tickers:
        return ClassificationInputs({}, {}, None, None)

    # 1. ticker → industry
    rows = (await db.execute(
        select(TickerIndustry.ticker, TickerIndustry.industry_name)
        .where(TickerIndustry.ticker.in_(upper_tickers))
    )).all()
    ticker_industry_map: dict[str, str] = {t: ind for t, ind in rows}

    # 2. latest market_industries snapshot
    latest_ts = (await db.execute(
        select(MarketIndustry.scraped_at)
        .order_by(MarketIndustry.scraped_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if latest_ts is None:
        logger.warning("sector_rotation: no market_industries snapshot found — all tickers will be unknown")
        return ClassificationInputs(ticker_industry_map, {}, None, None)

    industry_rows = (await db.execute(
        select(MarketIndustry).where(MarketIndustry.scraped_at == latest_ts)
    )).scalars().all()

    industry_metrics_map: dict[str, dict] = {}
    perf_1m_values: list[Decimal] = []
    for r in industry_rows:
        industry_metrics_map[r.name] = {
            "perf_1m": r.perf_1m,
            "perf_3m": r.perf_3m,
            "rvol_20d": r.rvol_20d,
            "top1_weight": r.top1_weight,
            "effective_n": r.effective_n,
        }
        if r.perf_1m is not None:
            perf_1m_values.append(r.perf_1m)

    median_perf_1m = Decimal(str(median(perf_1m_values))) if perf_1m_values else None

    snapshot_age_seconds: float | None = None
    if latest_ts is not None:
        from datetime import datetime, timezone
        # latest_ts is naive UTC (consistent with how _stage_snapshot_rows stores it)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        snapshot_age_seconds = (now - latest_ts).total_seconds()
        if snapshot_age_seconds > 48 * 3600:
            logger.warning(
                "sector_rotation: latest market_industries snapshot is %.1fh old — "
                "industries-refresh may be failing", snapshot_age_seconds / 3600,
            )

    return ClassificationInputs(
        ticker_industry_map=ticker_industry_map,
        industry_metrics_map=industry_metrics_map,
        median_perf_1m=median_perf_1m,
        snapshot_age_seconds=snapshot_age_seconds,
    )
