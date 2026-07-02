"""SEC Form 4 insider transactions — fetch, persist, cluster-buy detection.

Lean-Probe-Scope (Kill-Gate 2026-08-15):
- Universum = DISTINCT(Portfolio + Watchlist), nicht SP500
- Filter: transaction_code in (P, S) — open-market Buys/Sells. A/M/F/G werden ignoriert.
- Cluster-Signal: >=3 distinct Insider mit code=P in 30d. CEO/CFO zaehlen 3x bei
  der Effective-Count-Berechnung (Schwellwert ist trotzdem >=3 distinct names).
- Per-Ticker-Fetch: SEC EDGAR submissions API + Form 4 primary XML.

Wiederverwendetes Pattern: services/screening/sec_13f_service.py
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.form4_transaction import Form4Transaction
from services.api_utils import fetch_json, fetch_text
from services.screening.universe import resolve_equity_universe

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SEC EDGAR config
# ---------------------------------------------------------------------------
SEC_UA = "OpenFolio/1.0 screening@openfolio.dev"
SEC_HEADERS = {"User-Agent": SEC_UA}
SEC_DELAY = 0.15  # 10 req/s limit

# Form 4 XML namespace (no prefix in actual docs)
_NS_OWNERSHIP = ""  # SEC Form 4 XML hat keinen explizit deklarierten Default-NS

# Lookback fuer Cluster-Detection
CLUSTER_WINDOW_DAYS = 30
CLUSTER_MIN_INSIDERS = 3
CEO_CFO_WEIGHT = 3  # nur fuer Effective-Count im Signal, NICHT fuer Schwellwert

# In-memory cache fuer ticker -> CIK lookup.
# Fehlgeschlagene/leere Fetches markieren die Map NICHT als geladen (bleibt
# None) — sonst klebt ein transienter SEC-Fehler bis zum Prozess-Neustart am
# langlebigen Worker (Form-4-Refresh liefert dann still 0). Ein Retry-Timestamp
# mit Cooldown verhindert, dass jeder Aufruf erneut gegen SEC haemmert.
_ticker_cik_map: dict[str, str] | None = None
_ticker_cik_map_next_retry: float = 0.0
_MAP_RETRY_COOLDOWN_S = 600  # 10 min


# ---------------------------------------------------------------------------
# Ticker → CIK resolution
# ---------------------------------------------------------------------------

async def _load_ticker_cik_map() -> dict[str, str]:
    """Lade ticker -> CIK (10-stellig padded) aus SEC company_tickers.json.

    Gibt bei Fetch-Fehler/leerem Ergebnis ein leeres Dict zurueck, OHNE den
    Modul-Cache zu setzen — der naechste Aufruf nach Ablauf des Cooldowns
    versucht den Fetch erneut.
    """
    global _ticker_cik_map, _ticker_cik_map_next_retry
    if _ticker_cik_map is not None:
        return _ticker_cik_map

    now = time.monotonic()
    if now < _ticker_cik_map_next_retry:
        return {}

    loaded: dict[str, str] = {}
    try:
        data = await fetch_json(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS,
            timeout=15,
        )
        for v in data.values():
            ticker = (v.get("ticker") or "").strip().upper()
            cik_int = v.get("cik_str")
            if ticker and cik_int is not None:
                loaded[ticker] = str(cik_int).zfill(10)
        if loaded:
            _ticker_cik_map = loaded
            logger.info("Form 4 ticker->CIK map loaded: %d entries", len(loaded))
            return _ticker_cik_map
        logger.warning(
            "Form 4: company_tickers.json returned no entries — retry in %ds",
            _MAP_RETRY_COOLDOWN_S,
        )
    except Exception:
        logger.exception("Form 4: failed to load company_tickers.json")

    _ticker_cik_map_next_retry = now + _MAP_RETRY_COOLDOWN_S
    return {}


# ---------------------------------------------------------------------------
# Universe resolution
# ---------------------------------------------------------------------------

async def _resolve_universe(db: AsyncSession) -> list[str]:
    """DISTINCT(US-Equity-Positions ∪ aktive Watchlist) ueber alle User.

    Delegiert an `services.screening.universe.resolve_equity_universe` —
    type=stock-Filter eliminiert garantierte 404s (Cash, Crypto, ETFs,
    Multi-Listing-Suffixe). Form-4-Daten sind public, daher gemeinsames
    Universum; User-Filter passiert beim Surfacing in screening_service.

    Prod-Audit 2026-05-26: Drop-Set 23 Ticker, alle mit 0 form4_transactions
    — form4_cluster-Signal byte-identisch. Siehe Memory
    project_quant_probe_and_a2_gate.
    """
    return await resolve_equity_universe(db)


# ---------------------------------------------------------------------------
# Form 4 filing discovery + XML fetch
# ---------------------------------------------------------------------------

async def _find_recent_form4_filings(
    cik: str, since: date, max_count: int = 20
) -> list[dict]:
    """Finde Form-4-Filings fuer eine CIK ab `since` via Submissions-API.

    Returns: Liste mit accession_number, filing_date, primary_document.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        data = await fetch_json(url, headers=SEC_HEADERS, timeout=15)
    except Exception:
        logger.warning("Form 4: submissions fetch failed for CIK %s", cik)
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    found: list[dict] = []
    for i in range(min(len(forms), len(dates), len(accessions))):
        if forms[i] != "4":
            continue
        try:
            fdate = date.fromisoformat(dates[i])
        except (ValueError, TypeError):
            continue
        if fdate < since:
            continue
        found.append({
            "accession_number": accessions[i],
            "filing_date": fdate,
            "primary_document": primary_docs[i] if i < len(primary_docs) else None,
        })
        if len(found) >= max_count:
            break
    return found


async def _fetch_form4_xml(cik: str, accession: str, primary_doc: str | None) -> str | None:
    """Lade die Form-4-XML (primary document) eines Filings."""
    cik_raw = cik.lstrip("0") or "0"
    acc_no_dashes = accession.replace("-", "")

    # primaryDocument ist meist das XML direkt; sonst Index-Page als Fallback
    if primary_doc and primary_doc.lower().endswith(".xml"):
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_no_dashes}/{primary_doc}"
        try:
            return await fetch_text(url, headers=SEC_HEADERS, timeout=15)
        except Exception:
            logger.debug("Form 4: primary doc fetch failed %s", url)

    # Fallback: Index-Page nach .xml durchsuchen
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_no_dashes}/"
    try:
        index_html = await fetch_text(index_url, headers=SEC_HEADERS, timeout=15)
    except Exception:
        return None
    match = re.search(r'href="([^"]*\.xml)"', index_html, re.IGNORECASE)
    if not match:
        return None
    xml_path = match.group(1)
    if not xml_path.startswith("/"):
        xml_path = f"/Archives/edgar/data/{cik_raw}/{acc_no_dashes}/{xml_path}"
    try:
        return await fetch_text(f"https://www.sec.gov{xml_path}", headers=SEC_HEADERS, timeout=15)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# XML parser
# ---------------------------------------------------------------------------

def _text(elem: ET.Element | None, default: str = "") -> str:
    if elem is None or elem.text is None:
        return default
    return elem.text.strip()


def _safe_decimal(s: str) -> Decimal | None:
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _parse_form4_xml(xml_content: str, ticker: str, filing_date: date) -> list[dict]:
    """Parse Form-4-XML. Returns Liste von Non-Derivative-Transaktionen.

    Nur non-derivative transactions (echte Stuecke), keine Optionen/Derivate.
    Filter passiert downstream auf transaction_code.
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        logger.debug("Form 4 XML parse error for %s %s", ticker, filing_date)
        return []

    # reportingOwner kann mehrfach vorkommen — wir nehmen den ersten als
    # Insider-Name. Mehrere Owner pro Filing ist selten bei Form 4.
    owner = root.find(".//reportingOwner")
    if owner is None:
        return []
    insider_name = _text(owner.find(".//rptOwnerName"))
    if not insider_name:
        return []

    rel = owner.find(".//reportingOwnerRelationship")
    is_director = _text(rel.find("isDirector") if rel is not None else None) == "1"
    is_officer = _text(rel.find("isOfficer") if rel is not None else None) == "1"
    officer_title = _text(rel.find("officerTitle") if rel is not None else None)
    role_parts: list[str] = []
    if is_officer:
        role_parts.append(officer_title or "Officer")
    if is_director:
        role_parts.append("Director")
    insider_role = " / ".join(role_parts) or None

    rows: list[dict] = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        txn_date_str = _text(txn.find(".//transactionDate/value"))
        try:
            txn_date = date.fromisoformat(txn_date_str)
        except (ValueError, TypeError):
            continue
        code = _text(txn.find(".//transactionCoding/transactionCode"))
        shares = _safe_decimal(_text(txn.find(".//transactionShares/value")))
        price = _safe_decimal(_text(txn.find(".//transactionPricePerShare/value")))
        if not code or shares is None:
            continue
        value_usd: Decimal | None = None
        if price is not None and shares is not None:
            value_usd = (shares * price).quantize(Decimal("0.01"))
        rows.append({
            "ticker": ticker,
            "filing_date": filing_date,
            "transaction_date": txn_date,
            "insider_name": insider_name[:200],
            "insider_role": (insider_role[:100] if insider_role else None),
            "transaction_code": code[:2],
            "shares": int(shares),
            "price": price,
            "value_usd": value_usd,
        })
    return rows


# ---------------------------------------------------------------------------
# Refresh pipeline
# ---------------------------------------------------------------------------

def _aggregate_daily_transactions(rows: list[dict]) -> list[dict]:
    """Aggregiere gleichtaegige Teilausfuehrungen desselben Insiders mit gleichem Code.

    Der Dedup-Key (uq_form4_ticker_filing_insider_date_code) kollabiert mehrere
    Teilausfuehrungen eines Tages zu EINER Row — on_conflict_do_nothing behaelt
    nur die erste, total_value im Cluster-Signal wuerde unterschaetzt. Deshalb
    VOR dem Insert aggregieren: shares und value_usd summieren, price als
    wertgewichteter Schnitt der Teilausfuehrungen mit bekanntem Preis.
    """
    agg: dict[tuple, dict] = {}
    merge_counts: dict[tuple, int] = {}
    # key -> (shares mit bekanntem Preis, Summe value_usd dieser shares)
    priced: dict[tuple, tuple[int, Decimal]] = {}

    for r in rows:
        key = (
            r["ticker"], r["filing_date"], r["insider_name"],
            r["transaction_date"], r["transaction_code"],
        )
        merge_counts[key] = merge_counts.get(key, 0) + 1
        if r["price"] is not None and r["value_usd"] is not None:
            p_shares, p_value = priced.get(key, (0, Decimal("0")))
            priced[key] = (p_shares + r["shares"], p_value + r["value_usd"])
        cur = agg.get(key)
        if cur is None:
            agg[key] = dict(r)
        else:
            cur["shares"] += r["shares"]

    for key, cur in agg.items():
        if merge_counts[key] <= 1:
            continue  # Einzel-Row: Original-Preis/-Value unveraendert lassen
        p_shares, p_value = priced.get(key, (0, Decimal("0")))
        if p_shares > 0:
            cur["value_usd"] = p_value.quantize(Decimal("0.01"))
            cur["price"] = (p_value / Decimal(p_shares)).quantize(Decimal("0.0001"))
        else:
            cur["value_usd"] = None
            cur["price"] = None

    return list(agg.values())


async def refresh_form4_for_ticker(
    db: AsyncSession, ticker: str, cik: str, lookback_days: int = 90
) -> int:
    """Hole alle Form-4-Filings eines Tickers seit `lookback_days`, persist.

    Returns: Anzahl der eingefuegten Transaktionen (nach Dedup).
    """
    since = date.today() - timedelta(days=lookback_days)
    filings = await _find_recent_form4_filings(cik, since, max_count=50)
    if not filings:
        return 0

    all_rows: list[dict] = []
    for f in filings:
        await asyncio.sleep(SEC_DELAY)
        xml_content = await _fetch_form4_xml(
            cik, f["accession_number"], f.get("primary_document")
        )
        if not xml_content:
            continue
        all_rows.extend(_parse_form4_xml(xml_content, ticker, f["filing_date"]))

    inserted = 0
    for r in _aggregate_daily_transactions(all_rows):
        stmt = pg_insert(Form4Transaction).values(**r)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[
                "ticker", "filing_date", "insider_name",
                "transaction_date", "transaction_code",
            ]
        )
        result = await db.execute(stmt)
        if result.rowcount:
            inserted += int(result.rowcount)
    if inserted:
        await db.commit()
    return inserted


async def refresh_form4_universe(db: AsyncSession) -> dict[str, Any]:
    """Refresh Form-4 fuer Portfolio + Watchlist DISTINCT Tickers."""
    tickers = await _resolve_universe(db)
    cik_map = await _load_ticker_cik_map()
    total_inserted = 0
    skipped_unknown_cik: list[str] = []
    for t in tickers:
        cik = cik_map.get(t)
        if not cik:
            skipped_unknown_cik.append(t)
            continue
        try:
            count = await refresh_form4_for_ticker(db, t, cik)
            total_inserted += count
        except Exception:
            logger.exception("Form 4 refresh failed for %s", t)
            # Session nach einem (transienten) DB-Fehler bereinigen — sonst bleibt
            # sie im failed-transaction-state und ALLE Folge-Ticker werfen
            # PendingRollbackError (gleiches Muster wie dividend_forecast_service).
            try:
                await db.rollback()
            except Exception:
                logger.exception("Form 4 rollback failed for %s", t)
    return {
        "tickers_scanned": len(tickers),
        "tickers_no_cik": len(skipped_unknown_cik),
        "transactions_inserted": total_inserted,
    }


# ---------------------------------------------------------------------------
# Cluster-Signal computation (used by screening_service)
# ---------------------------------------------------------------------------

async def compute_cluster_signals(db: AsyncSession) -> list[dict]:
    """Liefer pro Ticker einen Cluster-Buy-Signal-Dict, falls Kriterien erfuellt.

    Kriterium: >=3 distinct Insider mit transaction_code='P' in CLUSTER_WINDOW_DAYS.
    Effective-Score erhoeht sich, wenn CEO/CFO unter den Buyern sind (CEO_CFO_WEIGHT).

    Returns: Liste von Dicts mit ticker/insider_count/total_value/has_ceo_cfo/trade_date.
    """
    since = date.today() - timedelta(days=CLUSTER_WINDOW_DAYS)
    q = (
        select(Form4Transaction)
        .where(
            Form4Transaction.transaction_code == "P",
            Form4Transaction.transaction_date >= since,
        )
    )
    rows = (await db.execute(q)).scalars().all()

    by_ticker: dict[str, dict] = {}
    for r in rows:
        bucket = by_ticker.setdefault(r.ticker, {
            "insiders": set(),
            "ceo_cfo_insiders": set(),
            "total_value": Decimal("0"),
            "latest_date": r.transaction_date,
        })
        bucket["insiders"].add(r.insider_name)
        if r.value_usd is not None:
            bucket["total_value"] += r.value_usd
        if r.transaction_date > bucket["latest_date"]:
            bucket["latest_date"] = r.transaction_date
        role_upper = (r.insider_role or "").upper()
        if "CEO" in role_upper or "CFO" in role_upper or "CHIEF EXECUTIVE" in role_upper or "CHIEF FINANCIAL" in role_upper:
            bucket["ceo_cfo_insiders"].add(r.insider_name)

    signals: list[dict] = []
    for ticker, data in by_ticker.items():
        n_insiders = len(data["insiders"])
        if n_insiders < CLUSTER_MIN_INSIDERS:
            continue
        n_ceo_cfo = len(data["ceo_cfo_insiders"])
        effective = n_insiders + n_ceo_cfo * (CEO_CFO_WEIGHT - 1)
        signals.append({
            "ticker": ticker,
            "insider_count": n_insiders,
            "ceo_cfo_count": n_ceo_cfo,
            "effective_score": effective,
            "total_value": float(data["total_value"]),
            "latest_trade_date": data["latest_date"].isoformat(),
            "window_days": CLUSTER_WINDOW_DAYS,
        })
    signals.sort(key=lambda s: s["effective_score"], reverse=True)
    return signals
