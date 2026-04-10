"""SEC 13F-HR Q/Q diff analysis with consensus architecture.

Fetches 13F-HR filings from SEC EDGAR for tracked superinvestor funds,
parses holdings from the XML infotable, persists snapshots, computes
quarter-over-quarter diffs, and aggregates consensus signals.

See SCOPE_SMART_MONEY_V4.md Block 3 for the full specification.

Data flow:
  1. refresh_13f_holdings  — fetch & persist latest filings for all funds
  2. compute_diffs         — Q/Q position changes per fund per ticker
  3. compute_consensus_signals — aggregate diffs, apply consensus thresholds
"""
from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.fund_holdings import FundHoldingsSnapshot
from services.api_utils import fetch_json, fetch_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SEC EDGAR config
# ---------------------------------------------------------------------------
SEC_UA = "OpenFolio/1.0 screening@openfolio.dev"
SEC_HEADERS = {"User-Agent": SEC_UA}
SEC_DELAY = 0.15  # 10 req/s limit → 0.15s between requests

# Verified fund CIKs — see scripts/fund_cik_verification.json
TRACKED_13F_FUNDS: dict[str, str] = {
    "0001067983": "Berkshire Hathaway (Buffett)",
    "0001649339": "Scion Asset Management (Burry)",
    "0001336528": "Pershing Square Capital (Ackman)",
    "0001656456": "Appaloosa LP (Tepper)",
    "0001549575": "Dalal Street LLC (Pabrai)",
    "0001040273": "Third Point LLC (Loeb)",
    "0000949509": "Oaktree Capital Management (Marks)",
    "0001061768": "Baupost Group LLC/MA (Klarman)",
    "0001079114": "Greenlight Capital (Einhorn)",
}

# 13F infotable XML namespace
_NS_13F = "http://www.sec.gov/edgar/document/thirteenf/informationtable"

# CUSIP → ticker cache (populated from SEC company_tickers.json)
_cusip_ticker_map: dict[str, str] | None = None
_name_ticker_map: dict[str, str] | None = None

# Consensus scoring weights
CONSENSUS_THRESHOLD = 3
SCORE_TABLE: dict[str, dict[str, int]] = {
    "new_position": {"single": 1, "consensus": 3},
    "added":        {"single": 0, "consensus": 2},
    "reduced":      {"single": 0, "consensus": -1},
    "closed":       {"single": 0, "consensus": -1},
}

ACTION_LABELS: dict[str, str] = {
    "new_position": "Neue Position",
    "added": "Aufgestockt (>20%)",
    "reduced": "Reduziert (>20%)",
    "closed": "Geschlossen",
}

# ---------------------------------------------------------------------------
# Ticker resolution
# ---------------------------------------------------------------------------


async def _load_ticker_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Load SEC company_tickers.json for name → ticker resolution.

    Returns (name_map, cusip_map). CUSIP map is empty for now — SEC
    company_tickers.json does not contain CUSIPs, but we keep the
    structure for future FMP integration.
    """
    global _cusip_ticker_map, _name_ticker_map
    if _name_ticker_map is not None and _cusip_ticker_map is not None:
        return _name_ticker_map, _cusip_ticker_map

    _cusip_ticker_map = {}
    _name_ticker_map = {}

    try:
        data = await fetch_json(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS,
            timeout=15,
        )
        for v in data.values():
            ticker = v.get("ticker", "")
            title = (v.get("title") or "").strip().upper()
            if ticker and title:
                _name_ticker_map[title] = ticker
        logger.info("13F ticker map loaded: %d entries", len(_name_ticker_map))
    except Exception:
        logger.exception("Failed to load SEC company_tickers.json for 13F")

    return _name_ticker_map, _cusip_ticker_map


def _resolve_ticker(issuer_name: str, name_map: dict[str, str]) -> str | None:
    """Try to resolve an issuer name to a ticker symbol.

    Uses exact match first, then substring matching on the company name.
    Returns None if unresolvable.
    """
    if not issuer_name:
        return None

    clean = issuer_name.strip().upper()

    # Exact match
    if clean in name_map:
        return name_map[clean]

    # Try removing common suffixes
    for suffix in (" INC", " CORP", " CO", " LTD", " PLC", " LP",
                   " LLC", " GROUP", " HOLDINGS", " INTERNATIONAL",
                   " COM", " CL A", " CLASS A", " CL B", " CLASS B",
                   " NEW", " COMMON"):
        stripped = clean.rstrip(".").removesuffix(suffix).strip()
        if stripped in name_map:
            return name_map[stripped]

    # Partial match: find shortest name_map key that starts with clean
    # (handles cases like "APPLE INC" matching "APPLE INC")
    candidates = []
    for key, ticker in name_map.items():
        if key.startswith(clean) or clean.startswith(key):
            candidates.append((len(key), ticker))
    if candidates:
        candidates.sort(key=lambda x: abs(len(clean) - x[0]))
        return candidates[0][1]

    return None


# ---------------------------------------------------------------------------
# Quarter utilities
# ---------------------------------------------------------------------------


def _quarter_end(q_label: str) -> date:
    """Parse '2025-Q4' → date(2025, 12, 31)."""
    year, q = q_label.split("-Q")
    month = {1: 3, 2: 6, 3: 9, 4: 12}[int(q)]
    if month in (3, 12):
        day = 31
    elif month == 6:
        day = 30
    elif month == 9:
        day = 30
    else:
        day = 31
    return date(int(year), month, day)


def _quarter_label(d: date) -> str:
    """date(2025, 12, 31) → '2025-Q4'."""
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def _prev_quarter_end(d: date) -> date:
    """Given a quarter-end date, return the previous quarter's end date."""
    if d.month <= 3:
        return date(d.year - 1, 12, 31)
    elif d.month <= 6:
        return date(d.year, 3, 31)
    elif d.month <= 9:
        return date(d.year, 6, 30)
    else:
        return date(d.year, 9, 30)


def _period_date_to_quarter_end(period: date) -> date:
    """Normalize a period_date to its quarter-end date."""
    if period.month <= 3:
        return date(period.year, 3, 31)
    elif period.month <= 6:
        return date(period.year, 6, 30)
    elif period.month <= 9:
        return date(period.year, 9, 30)
    else:
        return date(period.year, 12, 31)


def check_quarter_ready(quarter: str) -> bool:
    """True if today >= quarter-end + 75 days (aggregation stichtag)."""
    q_end = _quarter_end(quarter)
    ready_date = q_end + timedelta(days=75)
    return date.today() >= ready_date


def _quarter_ready_date(quarter: str) -> date:
    """Return the date when consensus becomes available for this quarter."""
    return _quarter_end(quarter) + timedelta(days=75)


# ---------------------------------------------------------------------------
# Phase 1: Fetch & Persist
# ---------------------------------------------------------------------------


async def _find_latest_13f_filing(
    cik: str, fund_name: str
) -> dict | None:
    """Find the most recent 13F-HR filing for a fund via EDGAR submissions API.

    Returns dict with accession_number, filing_date, period_date, or None.
    """
    results = await _find_13f_filings(cik, fund_name, count=1)
    return results[0] if results else None


async def _find_13f_filings(
    cik: str, fund_name: str, count: int = 1
) -> list[dict]:
    """Find the N most recent 13F-HR filings for a fund via EDGAR submissions API.

    Returns list of dicts with accession_number, filing_date, period_date.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        data = await fetch_json(url, headers=SEC_HEADERS, timeout=15)
    except Exception:
        logger.warning("13F: failed to fetch submissions for %s (%s)", fund_name, cik)
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    periods = recent.get("reportDate", [])

    found: list[dict] = []
    seen_periods: set[str] = set()
    for i in range(min(len(forms), len(dates), len(accessions))):
        form = forms[i]
        if form != "13F-HR":
            continue

        period = periods[i] if i < len(periods) else None
        # Deduplicate by period (amended filings)
        if period and period in seen_periods:
            continue
        if period:
            seen_periods.add(period)

        found.append({
            "accession_number": accessions[i],
            "filing_date": dates[i],
            "period_date": period,
            "cik_raw": cik.lstrip("0"),
        })
        if len(found) >= count:
            break

    if not found:
        logger.info("13F: no 13F-HR filing found for %s (%s)", fund_name, cik)
    return found


async def _fetch_infotable_xml(
    cik_raw: str, accession: str
) -> str | None:
    """Fetch the 13F infotable XML from the filing index.

    Strategy: load the filing index page, find the XML document with
    'infotable' or 'information' in its name.
    """
    acc_no_dashes = accession.replace("-", "")
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_no_dashes}/"

    try:
        index_html = await fetch_text(index_url, headers=SEC_HEADERS, timeout=15)
    except Exception:
        logger.warning("13F: failed to fetch filing index %s", index_url)
        return None

    # Find XML file with infotable/information in name
    # The index page is HTML with links to all documents
    xml_pattern = re.compile(
        r'href="([^"]*(?:infotable|information)[^"]*\.xml)"',
        re.IGNORECASE,
    )
    match = xml_pattern.search(index_html)

    if not match:
        # Fallback: try any .xml file that is not the primary document
        xml_fallback = re.compile(r'href="([^"]+\.xml)"', re.IGNORECASE)
        xml_matches = xml_fallback.findall(index_html)
        # Filter out primary doc XMLs (usually contain "primary" or are very short names)
        infotable_candidates = [
            m for m in xml_matches
            if "primary" not in m.lower() and "r1" not in m.lower()
        ]
        if not infotable_candidates:
            logger.warning(
                "13F: no infotable XML found in filing index for CIK %s acc %s",
                cik_raw, accession,
            )
            return None
        xml_filename = infotable_candidates[0]
    else:
        xml_filename = match.group(1)

    # Build full URL
    if xml_filename.startswith("http"):
        xml_url = xml_filename
    elif xml_filename.startswith("/"):
        xml_url = f"https://www.sec.gov{xml_filename}"
    else:
        xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_no_dashes}/{xml_filename}"

    await asyncio.sleep(SEC_DELAY)

    try:
        xml_text = await fetch_text(xml_url, headers=SEC_HEADERS, timeout=30)
    except Exception:
        logger.warning("13F: failed to fetch infotable XML %s", xml_url)
        return None

    return xml_text


def _parse_infotable_xml(xml_text: str) -> list[dict[str, Any]]:
    """Parse 13F infotable XML into list of holding dicts.

    Returns list of {issuer_name, cusip, shares, value_1000}.
    """
    holdings: list[dict[str, Any]] = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("13F: XML parse error: %s", e)
        return holdings

    # Handle namespaced and non-namespaced elements
    # Try common namespace first
    ns = {"ns": _NS_13F}

    # Find all infoTable entries (case-insensitive tag search)
    entries = root.findall(".//ns:infoTable", ns)
    if not entries:
        # Try without namespace
        entries = []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag.lower() == "infotable":
                entries.append(elem)

    for entry in entries:
        issuer_name = _xml_text(entry, "nameOfIssuer", ns)
        cusip = _xml_text(entry, "cusip", ns)
        value_str = _xml_text(entry, "value", ns)
        shares_str = _xml_text(entry, "sshPrnamt", ns)

        if not shares_str:
            # Try nested path
            for child in entry.iter():
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag.lower() == "sshprnamt" and child.text:
                    shares_str = child.text.strip()
                    break

        if not shares_str:
            continue

        try:
            shares = int(shares_str.replace(",", ""))
        except ValueError:
            continue

        value_1000 = None
        if value_str:
            try:
                value_1000 = int(value_str.replace(",", ""))
            except ValueError:
                pass

        holdings.append({
            "issuer_name": issuer_name or "",
            "cusip": cusip or "",
            "shares": shares,
            "value_1000": value_1000,
        })

    return holdings


def _xml_text(parent: ET.Element, tag_name: str, ns: dict[str, str]) -> str | None:
    """Extract text from a child element, handling namespaces."""
    # Try with namespace
    elem = parent.find(f".//ns:{tag_name}", ns)
    if elem is not None and elem.text:
        return elem.text.strip()

    # Try without namespace
    for child in parent.iter():
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local.lower() == tag_name.lower() and child.text:
            return child.text.strip()

    return None


async def refresh_13f_holdings(db: AsyncSession) -> dict:
    """Fetch latest 13F-HR filings for all tracked funds, parse and persist.

    Returns summary dict with counts of processed/skipped/failed funds.
    """
    name_map, _ = await _load_ticker_maps()

    processed = 0
    skipped = 0
    failed = 0
    total_holdings = 0
    total_resolved = 0
    total_unresolved = 0

    for cik, fund_name in TRACKED_13F_FUNDS.items():
        await asyncio.sleep(SEC_DELAY)

        # Step 1: Find latest 13F-HR filing
        filing = await _find_latest_13f_filing(cik, fund_name)
        if not filing:
            skipped += 1
            continue

        filing_date_str = filing["filing_date"]
        period_date_str = filing.get("period_date")
        accession = filing["accession_number"]
        cik_raw = filing["cik_raw"]

        # Parse dates
        try:
            f_date = date.fromisoformat(filing_date_str)
        except (ValueError, TypeError):
            logger.warning("13F: invalid filing date %s for %s", filing_date_str, fund_name)
            failed += 1
            continue

        if period_date_str:
            try:
                p_date = date.fromisoformat(period_date_str)
            except (ValueError, TypeError):
                p_date = _period_date_to_quarter_end(f_date)
        else:
            p_date = _period_date_to_quarter_end(f_date)

        # Normalize to quarter end
        p_date = _period_date_to_quarter_end(p_date)

        # Check if we already have this fund + period
        existing = await db.execute(
            select(func.count()).select_from(FundHoldingsSnapshot).where(
                FundHoldingsSnapshot.fund_cik == cik,
                FundHoldingsSnapshot.period_date == p_date,
            )
        )
        if existing.scalar() > 0:
            logger.debug(
                "13F: already have %s for period %s, skipping", fund_name, p_date
            )
            skipped += 1
            continue

        # Step 2: Fetch infotable XML
        await asyncio.sleep(SEC_DELAY)
        xml_text = await _fetch_infotable_xml(cik_raw, accession)
        if not xml_text:
            failed += 1
            continue

        # Step 3: Parse holdings
        raw_holdings = _parse_infotable_xml(xml_text)
        if not raw_holdings:
            logger.warning(
                "13F: no holdings parsed from infotable for %s (%s)",
                fund_name, accession,
            )
            failed += 1
            continue

        # Step 4: Resolve tickers and aggregate by ticker
        # Multiple share classes (e.g. AXP Class A / Class B) map to the
        # same ticker — sum shares and value to avoid duplicate-key errors.
        ticker_agg: dict[str, dict] = {}
        resolved_count = 0
        unresolved_count = 0

        for h in raw_holdings:
            ticker = _resolve_ticker(h["issuer_name"], name_map)
            if not ticker:
                unresolved_count += 1
                logger.debug(
                    "13F: unresolved issuer '%s' (CUSIP: %s) for %s",
                    h["issuer_name"], h["cusip"], fund_name,
                )
                continue

            resolved_count += 1
            value_usd = h["value_1000"] * 1000 if h["value_1000"] is not None else None

            if ticker in ticker_agg:
                ticker_agg[ticker]["shares"] += h["shares"]
                if value_usd is not None:
                    ticker_agg[ticker]["value_usd"] = (
                        (ticker_agg[ticker]["value_usd"] or 0) + value_usd
                    )
            else:
                ticker_agg[ticker] = {
                    "fund_cik": cik,
                    "fund_name": fund_name,
                    "ticker": ticker,
                    "shares": h["shares"],
                    "value_usd": value_usd,
                    "filing_date": f_date,
                    "period_date": p_date,
                }

        rows_to_insert = list(ticker_agg.values())

        # Step 5: Upsert into DB
        if rows_to_insert:
            stmt = pg_insert(FundHoldingsSnapshot).values(rows_to_insert)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_fund_holdings_cik_ticker_period",
                set_={
                    "shares": stmt.excluded.shares,
                    "value_usd": stmt.excluded.value_usd,
                    "filing_date": stmt.excluded.filing_date,
                    "fund_name": stmt.excluded.fund_name,
                },
            )
            await db.execute(stmt)
            await db.commit()

        processed += 1
        total_holdings += len(raw_holdings)
        total_resolved += resolved_count
        total_unresolved += unresolved_count

        logger.info(
            "13F: %s — %d holdings parsed, %d resolved, %d unresolved (period: %s)",
            fund_name, len(raw_holdings), resolved_count, unresolved_count, p_date,
        )

    result = {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "total_holdings_parsed": total_holdings,
        "total_resolved": total_resolved,
        "total_unresolved": total_unresolved,
    }
    logger.info("13F refresh complete: %s", result)
    return result


# ---------------------------------------------------------------------------
# Phase 2: Compute Diffs
# ---------------------------------------------------------------------------


async def compute_diffs(db: AsyncSession, quarter: str) -> list[dict]:
    """Compute Q/Q position changes for all funds in a given quarter.

    Returns list of diff dicts with fund_cik, fund_name, ticker, action,
    change_pct, filing_date.
    """
    q_end = _quarter_end(quarter)
    prev_q_end = _prev_quarter_end(q_end)

    # Load current quarter holdings
    current_q = await db.execute(
        select(FundHoldingsSnapshot).where(
            FundHoldingsSnapshot.period_date == q_end,
        )
    )
    current_holdings = current_q.scalars().all()

    # Load previous quarter holdings
    prev_q = await db.execute(
        select(FundHoldingsSnapshot).where(
            FundHoldingsSnapshot.period_date == prev_q_end,
        )
    )
    prev_holdings = prev_q.scalars().all()

    # Index by (fund_cik, ticker)
    prev_map: dict[tuple[str, str], FundHoldingsSnapshot] = {}
    for h in prev_holdings:
        prev_map[(h.fund_cik, h.ticker)] = h

    curr_map: dict[tuple[str, str], FundHoldingsSnapshot] = {}
    for h in current_holdings:
        curr_map[(h.fund_cik, h.ticker)] = h

    diffs: list[dict] = []

    # Check current holdings against previous
    for (cik, ticker), curr in curr_map.items():
        prev = prev_map.get((cik, ticker))

        if prev is None:
            diffs.append({
                "fund_cik": cik,
                "fund_name": curr.fund_name,
                "ticker": ticker,
                "action": "new_position",
                "change_pct": None,
                "filing_date": curr.filing_date.isoformat(),
            })
        else:
            if prev.shares == 0:
                ratio = float("inf")
            else:
                ratio = curr.shares / prev.shares

            if ratio >= 1.2:
                action = "added"
                change_pct = round((ratio - 1) * 100, 1)
            elif ratio <= 0.8:
                action = "reduced"
                change_pct = round((ratio - 1) * 100, 1)
            else:
                continue  # unchanged — skip

            diffs.append({
                "fund_cik": cik,
                "fund_name": curr.fund_name,
                "ticker": ticker,
                "action": action,
                "change_pct": change_pct,
                "filing_date": curr.filing_date.isoformat(),
            })

    # Check for closed positions (in prev but not in current)
    for cik in set(h.fund_cik for h in current_holdings):
        prev_tickers_for_fund = {
            t for (c, t) in prev_map if c == cik
        }
        curr_tickers_for_fund = {
            t for (c, t) in curr_map if c == cik
        }
        closed = prev_tickers_for_fund - curr_tickers_for_fund
        for ticker in closed:
            prev_h = prev_map[(cik, ticker)]
            diffs.append({
                "fund_cik": cik,
                "fund_name": prev_h.fund_name,
                "ticker": ticker,
                "action": "closed",
                "change_pct": -100.0,
                "filing_date": None,
            })

    return diffs


# ---------------------------------------------------------------------------
# Phase 3: Consensus Aggregation
# ---------------------------------------------------------------------------


async def compute_consensus_signals(db: AsyncSession) -> list[dict]:
    """Aggregate diffs by ticker, apply consensus thresholds.

    Returns list of ticker-centric signal dicts ready for integration
    into the screening scan results.
    """
    # Determine the latest quarter that has at least 1 filing
    latest_period = await db.execute(
        select(func.max(FundHoldingsSnapshot.period_date))
    )
    max_period = latest_period.scalar()
    if max_period is None:
        logger.info("13F consensus: no holdings data available")
        return []

    quarter = _quarter_label(max_period)
    is_ready = check_quarter_ready(quarter)
    ready_date = _quarter_ready_date(quarter)

    # Compute diffs for this quarter
    diffs = await compute_diffs(db, quarter)
    if not diffs:
        logger.info("13F consensus: no diffs for quarter %s", quarter)
        return []

    # Group diffs by ticker and action
    ticker_actions: dict[str, dict[str, list[dict]]] = {}
    for diff in diffs:
        ticker = diff["ticker"]
        action = diff["action"]
        if ticker not in ticker_actions:
            ticker_actions[ticker] = {}
        if action not in ticker_actions[ticker]:
            ticker_actions[ticker][action] = []
        ticker_actions[ticker][action].append({
            "fund": diff["fund_name"],
            "action": action,
            "filing_date": diff["filing_date"],
        })

    # Project signals
    signals: list[dict] = []

    for ticker, actions in ticker_actions.items():
        # Find the dominant action (most funds agree on)
        best_action = None
        best_count = 0
        for action, fund_list in actions.items():
            if len(fund_list) > best_count:
                best_count = len(fund_list)
                best_action = action

        if best_action is None:
            continue

        funds = actions[best_action]
        consensus_count = len(funds)

        if is_ready and consensus_count >= CONSENSUS_THRESHOLD:
            score = SCORE_TABLE[best_action]["consensus"]
            signal_key = "superinvestor_13f_consensus"
            signal = {
                "signal_key": signal_key,
                "ticker": ticker,
                "action": best_action,
                "action_label": ACTION_LABELS.get(best_action, best_action),
                "consensus_count": consensus_count,
                "funds": funds,
                "quarter": quarter,
                "quarter_ready_date": ready_date.isoformat(),
                "score_applied": score,
            }
        else:
            # Single-fund signal (before day 75 or < 3 funds)
            score = SCORE_TABLE[best_action]["single"]
            signal_key = "superinvestor_13f_single"
            signal = {
                "signal_key": signal_key,
                "ticker": ticker,
                "action": best_action,
                "action_label": ACTION_LABELS.get(best_action, best_action),
                "consensus_count": consensus_count,
                "funds": funds,
                "quarter": quarter,
                "score_applied": score,
            }
            if not is_ready:
                signal["quarter_status"] = "pending"

        # Only emit signals that have a non-zero score or are new_position
        if score != 0 or best_action == "new_position":
            signals.append(signal)

    logger.info(
        "13F consensus: quarter=%s ready=%s diffs=%d signals=%d",
        quarter, is_ready, len(diffs), len(signals),
    )
    return signals


# ---------------------------------------------------------------------------
# Backfill: fetch last N quarters for all tracked funds
# ---------------------------------------------------------------------------


async def backfill_13f_holdings(db: AsyncSession, quarters: int = 2) -> dict:
    """Fetch the last N 13F-HR filings per fund to seed Q/Q diff baseline.

    Unlike refresh_13f_holdings (which only fetches the latest filing),
    this fetches multiple historical filings so compute_diffs has a
    previous quarter to compare against.
    """
    name_map, _ = await _load_ticker_maps()

    processed = 0
    skipped = 0
    failed = 0
    total_holdings = 0
    total_resolved = 0

    for cik, fund_name in TRACKED_13F_FUNDS.items():
        await asyncio.sleep(SEC_DELAY)

        filings = await _find_13f_filings(cik, fund_name, count=quarters)
        if not filings:
            skipped += 1
            continue

        for filing in filings:
            filing_date_str = filing["filing_date"]
            period_date_str = filing.get("period_date")
            accession = filing["accession_number"]
            cik_raw = filing["cik_raw"]

            try:
                f_date = date.fromisoformat(filing_date_str)
            except (ValueError, TypeError):
                failed += 1
                continue

            if period_date_str:
                try:
                    p_date = date.fromisoformat(period_date_str)
                except (ValueError, TypeError):
                    p_date = _period_date_to_quarter_end(f_date)
            else:
                p_date = _period_date_to_quarter_end(f_date)

            p_date = _period_date_to_quarter_end(p_date)

            # Skip if already have this fund + period
            existing = await db.execute(
                select(func.count()).select_from(FundHoldingsSnapshot).where(
                    FundHoldingsSnapshot.fund_cik == cik,
                    FundHoldingsSnapshot.period_date == p_date,
                )
            )
            if existing.scalar() > 0:
                skipped += 1
                continue

            await asyncio.sleep(SEC_DELAY)
            xml_text = await _fetch_infotable_xml(cik_raw, accession)
            if not xml_text:
                failed += 1
                continue

            raw_holdings = _parse_infotable_xml(xml_text)
            if not raw_holdings:
                failed += 1
                continue

            ticker_agg: dict[str, dict] = {}
            resolved_count = 0
            for h in raw_holdings:
                ticker = _resolve_ticker(h["issuer_name"], name_map)
                if not ticker:
                    continue
                resolved_count += 1
                value_usd = h["value_1000"] * 1000 if h["value_1000"] is not None else None
                if ticker in ticker_agg:
                    ticker_agg[ticker]["shares"] += h["shares"]
                    if value_usd is not None:
                        ticker_agg[ticker]["value_usd"] = (
                            (ticker_agg[ticker]["value_usd"] or 0) + value_usd
                        )
                else:
                    ticker_agg[ticker] = {
                        "fund_cik": cik,
                        "fund_name": fund_name,
                        "ticker": ticker,
                        "shares": h["shares"],
                        "value_usd": value_usd,
                        "filing_date": f_date,
                        "period_date": p_date,
                    }

            rows_to_insert = list(ticker_agg.values())
            if rows_to_insert:
                stmt = pg_insert(FundHoldingsSnapshot).values(rows_to_insert)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_fund_holdings_cik_ticker_period",
                    set_={
                        "shares": stmt.excluded.shares,
                        "value_usd": stmt.excluded.value_usd,
                        "filing_date": stmt.excluded.filing_date,
                        "fund_name": stmt.excluded.fund_name,
                    },
                )
                await db.execute(stmt)
                await db.commit()

            processed += 1
            total_holdings += len(raw_holdings)
            total_resolved += resolved_count
            logger.info(
                "13F backfill: %s period=%s — %d holdings, %d resolved",
                fund_name, p_date, len(raw_holdings), resolved_count,
            )

    result = {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "total_holdings_parsed": total_holdings,
        "total_resolved": total_resolved,
    }
    logger.info("13F backfill complete: %s", result)
    return result
