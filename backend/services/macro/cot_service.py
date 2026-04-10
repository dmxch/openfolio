"""CFTC Commitments of Traders — weekly macro/positioning ingestion.

Isolated from the equity screener. COT data is displayed in a separate
Macro/Positioning tab and has NO influence on the equity score. See
``SCOPE_SMART_MONEY_V4.md`` Block 1 for the full specification.

Data sources and scope deviation
--------------------------------
The scope asks for five instruments in one CFTC report::

    GC (Gold), SI (Silver), CL (WTI Crude), DX (USD Index), ZN (10Y T-Note)

and nominates ``fut_fin_txt_<year>.zip`` (Traders in Financial Futures, TFF) as
the sole source. That mapping is not achievable against the actual CFTC
archives:

* The commodities GC/SI/CL are published in the Disaggregated Futures-Only
  report (``fut_disagg_txt_<year>.zip``), NOT in the TFF archive.
* DX and ZN are published in the TFF archive — but their legacy names
  ``U.S. DOLLAR INDEX - ICE FUTURES U.S.`` and ``10-YEAR U.S. TREASURY NOTES
  - CHICAGO BOARD OF TRADE`` do not exist in current CFTC data (verified
  against 2024/2025/2026 annual archives). CFTC now publishes these as
  ``USD INDEX - ICE FUTURES U.S.`` and ``UST 10Y NOTE - CHICAGO BOARD OF
  TRADE``.
* CL uses ``CRUDE OIL, LIGHT SWEET-WTI - ICE FUTURES EUROPE`` (Brent-WTI)
  instead of ``WTI FINANCIAL CRUDE OIL - NYMEX`` because the NYMEX Financial
  contract is too thinly traded (Managed Money net often 0) for meaningful
  Commercials-vs-Specs analysis. ICE Brent-WTI has deeper positioning data.

Accordingly this service pulls TWO annual archives per refresh (Disaggregated
Futures-Only + TFF) and maps each configured instrument to the authoritative
current market name. Commercials/Managed Money categories are derived from
the report-specific columns::

    Disaggregated (commodities):
        commercial = Producer/Merchant/Processor/User + Swap Dealers
        managed_money = Managed Money

    TFF (financials):
        commercial = Dealer/Intermediary      (industry standard translation)
        managed_money = Leveraged Money       (industry standard translation)

This deviation preserves the scope's intent — show commercials vs.
speculators extreme positioning in the five requested markets — while
remaining truthful about the actual CFTC data layout. It is documented here
as the single source of truth for reviewers.

Signal logic
------------
Per instrument we compute a 52-week percentile rank for ``commercial_net``
and ``mm_net``::

    pct = (current - min_52w) / (max_52w - min_52w) * 100

Extreme zones are ``<= 10`` or ``>= 90`` (scope AC-2). These flags are used
only by the frontend badge; they are NOT fed into the equity score.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db import async_session
from models.macro_cot import MacroCotSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Instrument configuration
# ---------------------------------------------------------------------------
DISAGG_SOURCE = "disagg"
TFF_SOURCE = "tff"


@dataclass(frozen=True)
class CotInstrument:
    code: str
    name: str
    market_name: str
    source: str  # DISAGG_SOURCE or TFF_SOURCE


COT_INSTRUMENTS: tuple[CotInstrument, ...] = (
    CotInstrument("GC", "Gold (COMEX)", "GOLD - COMMODITY EXCHANGE INC.", DISAGG_SOURCE),
    CotInstrument("SI", "Silber (COMEX)", "SILVER - COMMODITY EXCHANGE INC.", DISAGG_SOURCE),
    CotInstrument(
        "CL",
        "Crude Oil (ICE Brent-WTI)",
        "CRUDE OIL, LIGHT SWEET-WTI - ICE FUTURES EUROPE",
        DISAGG_SOURCE,
    ),
    CotInstrument(
        "DX",
        "US Dollar Index (ICE)",
        "USD INDEX - ICE FUTURES U.S.",
        TFF_SOURCE,
    ),
    CotInstrument(
        "ZN",
        "10Y US Treasury Note (CBOT)",
        "UST 10Y NOTE - CHICAGO BOARD OF TRADE",
        TFF_SOURCE,
    ),
)

CFTC_DISAGG_URL_TEMPLATE = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
CFTC_TFF_URL_TEMPLATE = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"

EXTREME_LOW_PCT = 10.0
EXTREME_HIGH_PCT = 90.0
PERCENTILE_WINDOW_WEEKS = 52

HTTP_TIMEOUT_SECONDS = 60.0


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    v = value.strip()
    if not v or v == ".":
        return None
    try:
        return int(v.replace(",", ""))
    except ValueError:
        try:
            return int(float(v))
        except ValueError:
            return None


def _parse_report_date(value: str | None) -> date | None:
    v = (value or "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _sum_opt(*values: int | None) -> int | None:
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


@dataclass
class CotRow:
    instrument: CotInstrument
    report_date: date
    commercial_long: int | None
    commercial_short: int | None
    mm_long: int | None
    mm_short: int | None
    oi_total: int | None

    @property
    def commercial_net(self) -> int | None:
        if self.commercial_long is None or self.commercial_short is None:
            return None
        return self.commercial_long - self.commercial_short

    @property
    def mm_net(self) -> int | None:
        if self.mm_long is None or self.mm_short is None:
            return None
        return self.mm_long - self.mm_short


def _iter_disagg_rows(csv_bytes: bytes, wanted: dict[str, CotInstrument]) -> Iterable[CotRow]:
    """Yield CotRow for every Disaggregated-Report instrument in ``wanted``."""
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    for raw in reader:
        market = (raw.get("Market_and_Exchange_Names") or "").strip()
        instrument = wanted.get(market)
        if instrument is None:
            continue

        report_date = _parse_report_date(
            raw.get("Report_Date_as_YYYY-MM-DD") or raw.get("Report_Date_as_MM_DD_YYYY")
        )
        if report_date is None:
            continue

        # Commercials = Producer/Merchant/Processor/User + Swap Dealers.
        prod_long = _parse_int(raw.get("Prod_Merc_Positions_Long_All"))
        prod_short = _parse_int(raw.get("Prod_Merc_Positions_Short_All"))
        # Note: CFTC CSV header has a typo in some years (double underscore).
        swap_long = _parse_int(raw.get("Swap__Positions_Long_All")) or _parse_int(
            raw.get("Swap_Positions_Long_All")
        )
        swap_short = _parse_int(raw.get("Swap__Positions_Short_All")) or _parse_int(
            raw.get("Swap_Positions_Short_All")
        )

        commercial_long = _sum_opt(prod_long, swap_long)
        commercial_short = _sum_opt(prod_short, swap_short)

        mm_long = _parse_int(raw.get("M_Money_Positions_Long_All"))
        mm_short = _parse_int(raw.get("M_Money_Positions_Short_All"))

        oi_total = _parse_int(raw.get("Open_Interest_All"))

        yield CotRow(
            instrument=instrument,
            report_date=report_date,
            commercial_long=commercial_long,
            commercial_short=commercial_short,
            mm_long=mm_long,
            mm_short=mm_short,
            oi_total=oi_total,
        )


def _iter_tff_rows(csv_bytes: bytes, wanted: dict[str, CotInstrument]) -> Iterable[CotRow]:
    """Yield CotRow for every TFF-Report instrument in ``wanted``.

    TFF trader categories are translated to the commercial / managed_money
    terminology used by the rest of this module:

    - commercial  ← Dealer/Intermediary (hedge/market-making role)
    - managed_money ← Leveraged Money (pure-speculator category in TFF)
    """
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    for raw in reader:
        market = (raw.get("Market_and_Exchange_Names") or "").strip()
        instrument = wanted.get(market)
        if instrument is None:
            continue

        report_date = _parse_report_date(
            raw.get("Report_Date_as_YYYY-MM-DD") or raw.get("Report_Date_as_MM_DD_YYYY")
        )
        if report_date is None:
            continue

        commercial_long = _parse_int(raw.get("Dealer_Positions_Long_All"))
        commercial_short = _parse_int(raw.get("Dealer_Positions_Short_All"))

        mm_long = _parse_int(raw.get("Lev_Money_Positions_Long_All"))
        mm_short = _parse_int(raw.get("Lev_Money_Positions_Short_All"))

        oi_total = _parse_int(raw.get("Open_Interest_All"))

        yield CotRow(
            instrument=instrument,
            report_date=report_date,
            commercial_long=commercial_long,
            commercial_short=commercial_short,
            mm_long=mm_long,
            mm_short=mm_short,
            oi_total=oi_total,
        )


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------
async def _fetch_zip(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.content


def _extract_first_text_file(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        candidates = [n for n in zf.namelist() if n.lower().endswith((".txt", ".csv"))]
        if not candidates:
            raise ValueError("CFTC-Archiv enthaelt keine CSV-/TXT-Datei")
        with zf.open(candidates[0]) as fh:
            return fh.read()


async def _fetch_year(year: int) -> list[CotRow]:
    """Download + parse all configured instruments for a single report year."""
    disagg_wanted = {i.market_name: i for i in COT_INSTRUMENTS if i.source == DISAGG_SOURCE}
    tff_wanted = {i.market_name: i for i in COT_INSTRUMENTS if i.source == TFF_SOURCE}

    rows: list[CotRow] = []

    if disagg_wanted:
        try:
            zip_bytes = await _fetch_zip(CFTC_DISAGG_URL_TEMPLATE.format(year=year))
            csv_bytes = await asyncio.to_thread(_extract_first_text_file, zip_bytes)
            rows.extend(_iter_disagg_rows(csv_bytes, disagg_wanted))
        except Exception as exc:  # noqa: BLE001 — graceful per AC-4
            logger.warning("CFTC disagg fetch failed for %s: %s", year, exc)
            raise

    if tff_wanted:
        try:
            zip_bytes = await _fetch_zip(CFTC_TFF_URL_TEMPLATE.format(year=year))
            csv_bytes = await asyncio.to_thread(_extract_first_text_file, zip_bytes)
            rows.extend(_iter_tff_rows(csv_bytes, tff_wanted))
        except Exception as exc:  # noqa: BLE001 — graceful per AC-4
            logger.warning("CFTC TFF fetch failed for %s: %s", year, exc)
            raise

    return rows


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
async def _upsert_rows(db: AsyncSession, rows: list[CotRow]) -> int:
    if not rows:
        return 0

    payload = [
        {
            "instrument": r.instrument.code,
            "report_date": r.report_date,
            "commercial_long": r.commercial_long,
            "commercial_short": r.commercial_short,
            "commercial_net": r.commercial_net,
            "mm_long": r.mm_long,
            "mm_short": r.mm_short,
            "mm_net": r.mm_net,
            "oi_total": r.oi_total,
        }
        for r in rows
    ]

    dialect = db.bind.dialect.name if db.bind is not None else ""
    inserted = 0
    if dialect == "postgresql":
        stmt = pg_insert(MacroCotSnapshot).values(payload)
        stmt = stmt.on_conflict_do_nothing(index_elements=["instrument", "report_date"])
        result = await db.execute(stmt)
        inserted = result.rowcount or 0
    else:
        # Portable fallback (SQLite tests): check-then-insert.
        for entry in payload:
            exists_q = select(MacroCotSnapshot.id).where(
                MacroCotSnapshot.instrument == entry["instrument"],
                MacroCotSnapshot.report_date == entry["report_date"],
            )
            if (await db.execute(exists_q)).scalar_one_or_none() is None:
                db.add(MacroCotSnapshot(**entry))
                inserted += 1

    await db.commit()
    return inserted


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
async def refresh_cot_snapshots(years: int = 2) -> dict:
    """Pull the most recent CFTC annual archives and persist weekly snapshots.

    ``years`` controls how many annual archives we read (default 2 — current
    year plus previous year). That guarantees at least ~52 weeks of history
    even on a fresh install.
    """
    current_year = datetime.utcnow().year
    target_years = [current_year - offset for offset in range(years)]

    all_rows: list[CotRow] = []
    errors: list[str] = []

    for year in target_years:
        try:
            rows = await _fetch_year(year)
            all_rows.extend(rows)
        except Exception as exc:  # noqa: BLE001 — graceful per AC-4
            errors.append(f"{year}: {exc}")

    if not all_rows:
        return {"inserted": 0, "errors": errors, "status": "no_data"}

    async with async_session() as db:
        inserted = await _upsert_rows(db, all_rows)

    logger.info(
        "COT refresh complete: years=%s rows_parsed=%s inserted=%s errors=%s",
        target_years,
        len(all_rows),
        inserted,
        len(errors),
    )
    return {
        "inserted": inserted,
        "errors": errors,
        "status": "ok" if not errors else "partial",
        "years": target_years,
        "rows_parsed": len(all_rows),
    }


# ---------------------------------------------------------------------------
# Read-side: latest snapshot + 52w percentile
# ---------------------------------------------------------------------------
def _percentile_from_history(current: float, history: list[float]) -> float | None:
    """Return 0..100 rank of ``current`` within ``history`` (simple min/max).

    Uses the range the scope specifies:
    ``(current - min) / (max - min) * 100``. If history has zero width (no
    variation), returns ``50.0``. Returns ``None`` for empty history.
    """
    if not history:
        return None
    lo = min(history)
    hi = max(history)
    if hi == lo:
        return 50.0
    pct = (current - lo) / (hi - lo) * 100.0
    return max(0.0, min(100.0, pct))


async def get_latest_cot_overview(db: AsyncSession) -> dict:
    """Return the latest snapshot per instrument plus 52w percentile metrics."""
    instruments_payload: list[dict] = []
    latest_overall_date: date | None = None
    latest_overall_ts: datetime | None = None

    for instrument in COT_INSTRUMENTS:
        history_q = (
            select(MacroCotSnapshot)
            .where(MacroCotSnapshot.instrument == instrument.code)
            .order_by(MacroCotSnapshot.report_date.desc())
            .limit(PERCENTILE_WINDOW_WEEKS)
        )
        snapshots = (await db.execute(history_q)).scalars().all()

        if not snapshots:
            instruments_payload.append({
                "code": instrument.code,
                "name": instrument.name,
                "report_date": None,
                "commercial_net": None,
                "commercial_net_pct_52w": None,
                "mm_net": None,
                "mm_net_pct_52w": None,
                "oi_total": None,
                "is_extreme_commercial": False,
                "is_extreme_mm": False,
                "history_weeks": 0,
            })
            continue

        latest = snapshots[0]

        commercial_history = [s.commercial_net for s in snapshots if s.commercial_net is not None]
        mm_history = [s.mm_net for s in snapshots if s.mm_net is not None]

        commercial_pct = (
            _percentile_from_history(latest.commercial_net, commercial_history)
            if latest.commercial_net is not None
            else None
        )
        mm_pct = (
            _percentile_from_history(latest.mm_net, mm_history)
            if latest.mm_net is not None
            else None
        )

        is_extreme_commercial = commercial_pct is not None and (
            commercial_pct <= EXTREME_LOW_PCT or commercial_pct >= EXTREME_HIGH_PCT
        )
        is_extreme_mm = mm_pct is not None and (
            mm_pct <= EXTREME_LOW_PCT or mm_pct >= EXTREME_HIGH_PCT
        )

        if latest_overall_date is None or latest.report_date > latest_overall_date:
            latest_overall_date = latest.report_date
        if latest.created_at and (latest_overall_ts is None or latest.created_at > latest_overall_ts):
            latest_overall_ts = latest.created_at

        instruments_payload.append({
            "code": instrument.code,
            "name": instrument.name,
            "report_date": latest.report_date.isoformat() if latest.report_date else None,
            "commercial_net": latest.commercial_net,
            "commercial_net_pct_52w": round(commercial_pct, 1) if commercial_pct is not None else None,
            "mm_net": latest.mm_net,
            "mm_net_pct_52w": round(mm_pct, 1) if mm_pct is not None else None,
            "oi_total": latest.oi_total,
            "is_extreme_commercial": bool(is_extreme_commercial),
            "is_extreme_mm": bool(is_extreme_mm),
            "history_weeks": len(snapshots),
        })

    return {
        "updated_at": latest_overall_ts.isoformat() if latest_overall_ts else None,
        "report_date": latest_overall_date.isoformat() if latest_overall_date else None,
        "instruments": instruments_payload,
    }
