"""TradingView industry-rotation scraper + persistence.

Fetches aggregated performance metrics for all US-industries from the
TradingView Scanner API (public but undocumented) and persists them as
daily snapshots in ``market_industries``.

Endpoint: POST https://scanner.tradingview.com/america/scan
Auth: none
Payload shape:
    {
      "symbols": {"query": {"types": ["industry"]}},
      "columns": [...],
      "range": [0, 200]
    }
Response: {"totalCount": int, "data": [{"s": "INDUSTRY_US:...", "d": [values]}]}

Design notes:
- The column order in the request MUST match the parse order — see
  ``_COLUMNS`` / ``_parse_row``. Any reordering breaks the mapping.
- NULL values: TradingView returns ``null`` (and occasionally sentinel
  values like 99999900 for missing long-running perfs). We accept null
  and store NULL; sentinel-detection is deliberately out-of-scope here
  to keep the scraper simple.
- Failure mode: if the POST fails or the schema changes, we raise and
  the caller (worker job) keeps the last snapshot in DB instead of
  wiping it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dateutils import utcnow
from models.market_industry import MarketIndustry

logger = logging.getLogger(__name__)


_SCANNER_URL = "https://scanner.tradingview.com/america/scan"

# Order MUST match `_parse_row` indexing.
_COLUMNS: list[str] = [
    "name",            # 0 — slug, e.g. "integrated-oil"
    "description",     # 1 — display name, e.g. "Integrated Oil"
    "change",          # 2 — intraday %
    "Perf.W",          # 3
    "Perf.1M",         # 4
    "Perf.3M",         # 5
    "Perf.6M",         # 6
    "Perf.YTD",        # 7
    "Perf.Y",          # 8
    "Perf.5Y",         # 9
    "Perf.10Y",        # 10
    "market_cap_basic", # 11
    "volume",          # 12
]

_RANGE_MAX = 200  # Scanner returns ~129 rows today; buffer for future growth.

# period query-param → SQL column on MarketIndustry
PERIOD_TO_COLUMN: dict[str, str] = {
    "1w": "perf_1w",
    "1m": "perf_1m",
    "3m": "perf_3m",
    "6m": "perf_6m",
    "ytd": "perf_ytd",
    "1y": "perf_1y",
    "5y": "perf_5y",
    "10y": "perf_10y",
}


def _to_decimal(v: Any) -> Decimal | None:
    """Coerce a JSON value into a Decimal or None.

    Treats None, empty strings, and non-numerics as NULL (no exception).
    """
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None
    # Some TradingView metrics can come back as infinities/NaN — reject.
    if not d.is_finite():
        return None
    return d


def _parse_row(raw: dict) -> dict | None:
    """Turn one scanner row into a normalised dict, or None if unusable."""
    s = raw.get("s") or ""
    d = raw.get("d") or []
    if not isinstance(d, list) or len(d) < len(_COLUMNS):
        logger.warning("tradingview industries: unexpected row shape for %s", s)
        return None

    slug = str(d[0] or "").strip() or None
    name = str(d[1] or "").strip() or None
    if not slug or not name:
        return None

    return {
        "slug": slug,
        "name": name,
        "change_pct": _to_decimal(d[2]),
        "perf_1w": _to_decimal(d[3]),
        "perf_1m": _to_decimal(d[4]),
        "perf_3m": _to_decimal(d[5]),
        "perf_6m": _to_decimal(d[6]),
        "perf_ytd": _to_decimal(d[7]),
        "perf_1y": _to_decimal(d[8]),
        "perf_5y": _to_decimal(d[9]),
        "perf_10y": _to_decimal(d[10]),
        "market_cap": _to_decimal(d[11]),
        "volume": _to_decimal(d[12]),
    }


async def fetch_industries_snapshot() -> list[dict]:
    """Fetch the latest industry aggregates from TradingView.

    Returns a list of normalised dicts. Raises if the HTTP call fails or
    the response has an unexpected schema (caller should keep the old
    snapshot in DB in that case).
    """
    payload = {
        "symbols": {"query": {"types": ["industry"]}},
        "columns": _COLUMNS,
        "range": [0, _RANGE_MAX],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _SCANNER_URL,
            json=payload,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (OpenFolio)",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    if not isinstance(body, dict) or "data" not in body:
        raise ValueError("tradingview industries: unexpected response shape")

    rows: list[dict] = []
    for raw in body.get("data") or []:
        parsed = _parse_row(raw)
        if parsed is not None:
            rows.append(parsed)

    if not rows:
        raise ValueError("tradingview industries: empty snapshot")

    logger.info("tradingview industries: fetched %d rows", len(rows))
    return rows


async def persist_snapshot(db: AsyncSession, rows: list[dict]) -> datetime:
    """Insert all rows with a common ``scraped_at`` timestamp, commit, return ts."""
    scraped_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for r in rows:
        db.add(MarketIndustry(
            id=uuid.uuid4(),
            slug=r["slug"],
            name=r["name"],
            scraped_at=scraped_at,
            change_pct=r.get("change_pct"),
            perf_1w=r.get("perf_1w"),
            perf_1m=r.get("perf_1m"),
            perf_3m=r.get("perf_3m"),
            perf_6m=r.get("perf_6m"),
            perf_ytd=r.get("perf_ytd"),
            perf_1y=r.get("perf_1y"),
            perf_5y=r.get("perf_5y"),
            perf_10y=r.get("perf_10y"),
            market_cap=r.get("market_cap"),
            volume=r.get("volume"),
        ))
    await db.commit()
    logger.info("tradingview industries: persisted %d rows at %s", len(rows), scraped_at)
    return scraped_at


async def refresh_industries(db: AsyncSession) -> dict:
    """Orchestrate fetch + persist. Returns summary dict with row count + ts.

    On fetch or persist errors the DB state is left untouched (previous
    snapshot remains queryable via ``get_latest_industries``).
    """
    rows = await fetch_industries_snapshot()
    scraped_at = await persist_snapshot(db, rows)
    return {"count": len(rows), "scraped_at": scraped_at.isoformat()}


def _row_to_dict(row: MarketIndustry) -> dict:
    def f(v: Decimal | None) -> float | None:
        return float(v) if v is not None else None
    return {
        "slug": row.slug,
        "name": row.name,
        "change_pct": f(row.change_pct),
        "perf_1w": f(row.perf_1w),
        "perf_1m": f(row.perf_1m),
        "perf_3m": f(row.perf_3m),
        "perf_6m": f(row.perf_6m),
        "perf_ytd": f(row.perf_ytd),
        "perf_1y": f(row.perf_1y),
        "perf_5y": f(row.perf_5y),
        "perf_10y": f(row.perf_10y),
        "market_cap": f(row.market_cap),
        "volume": f(row.volume),
    }


async def get_latest_industries(
    db: AsyncSession,
    *,
    period: str = "ytd",
    top: int | None = None,
    bottom: int | None = None,
    order: str = "desc",
) -> dict:
    """Read the latest snapshot, optionally sorted/limited by one metric.

    `period` picks the sort column (see ``PERIOD_TO_COLUMN``).
    `top` / `bottom` are exclusive — if both are set, `top` wins.
    `order` applies to the full listing; `bottom=N` overrides order to asc.
    """
    if period not in PERIOD_TO_COLUMN:
        raise ValueError(f"invalid period: {period}")
    column_name = PERIOD_TO_COLUMN[period]

    latest_ts = (
        await db.execute(select(MarketIndustry.scraped_at)
                          .order_by(MarketIndustry.scraped_at.desc())
                          .limit(1))
    ).scalar_one_or_none()
    if latest_ts is None:
        return {"scraped_at": None, "period": period, "count": 0, "rows": []}

    rows_res = await db.execute(
        select(MarketIndustry).where(MarketIndustry.scraped_at == latest_ts)
    )
    rows = list(rows_res.scalars().all())

    # Sort: NULLs always last regardless of order.
    sort_col = lambda r: getattr(r, column_name)  # noqa: E731
    non_null = [r for r in rows if sort_col(r) is not None]
    nulls = [r for r in rows if sort_col(r) is None]

    reverse_sort = order != "asc"
    if bottom is not None and top is None:
        # "bottom N" = the N worst; ascending order, then slice N.
        non_null.sort(key=sort_col)
        out = non_null[:bottom]
    else:
        non_null.sort(key=sort_col, reverse=reverse_sort)
        out = non_null
        if top is not None:
            out = out[:top]

    # Append nulls only when returning the full universe.
    if top is None and bottom is None:
        out = out + nulls

    return {
        "scraped_at": latest_ts.replace(tzinfo=timezone.utc).isoformat()
            if latest_ts.tzinfo is None
            else latest_ts.isoformat(),
        "period": period,
        "count": len(out),
        "rows": [_row_to_dict(r) for r in out],
    }
