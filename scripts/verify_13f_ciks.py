"""
verify_13f_ciks.py
==================

Stand-alone verification script for 13F-HR filer CIKs against SEC EDGAR.

Purpose
-------
Pre-condition for the planned Smart Money Screener Block 3 in OpenFolio.
Without verified CIKs the block will NOT be implemented. The script takes
fund NAMES (not CIKs) as input, queries SEC EDGAR, extracts candidate CIKs
from the response and confirms each candidate has actually filed a 13F-HR
within the last two years.

Output
------
scripts/fund_cik_verification.json — machine readable report.

Usage
-----
    python scripts/verify_13f_ciks.py

Constraints
-----------
* httpx only (no requests) — OpenFolio convention.
* SEC requires a descriptive User-Agent, otherwise 403.
* Max 10 requests per second — we sleep 0.15s between calls (~6.6 r/s).
* Stand-alone: NO imports from the OpenFolio backend package.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

USER_AGENT = "OpenFolio Research 13F-Verification contact@openfolio.local"

# Full-text search endpoint (returns JSON). This is the primary discovery API.
EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# Submissions API — per CIK, returns recent filings list as JSON.
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# Classic browse-edgar fallback (HTML, only used if JSON search fails entirely).
BROWSE_EDGAR_URL = "https://www.sec.gov/cgi-bin/browse-edgar"

# SEC says <= 10 req/s. We aim well below.
REQUEST_DELAY_SECONDS = 0.15

# A 13F is considered "recent" if filed within this window.
RECENT_WINDOW_DAYS = 365 * 2

OUTPUT_PATH = Path(__file__).parent / "fund_cik_verification.json"


# Funds to verify. NOTE: do NOT pre-fill CIKs here — the script must
# discover them. The "query" string is what we send to EDGAR.
FUNDS: list[dict[str, str]] = [
    {
        "name": "Berkshire Hathaway",
        "manager": "Warren Buffett",
        "query": "berkshire hathaway",
    },
    {
        "name": "Scion Asset Management",
        "manager": "Michael Burry",
        "query": "scion asset management",
    },
    {
        "name": "Pershing Square Capital Management",
        "manager": "Bill Ackman",
        "query": "pershing square capital management",
    },
    {
        "name": "Appaloosa Management",
        "manager": "David Tepper",
        "query": "appaloosa",
    },
    {
        "name": "Pabrai Investment Funds",
        "manager": "Mohnish Pabrai",
        # Pabrai files via "Dalal Street LLC". Querying the manager name
        # increases recall because EDGAR indexes managing-member names too.
        "query": "dalal street",
    },
    {
        "name": "Third Point LLC",
        "manager": "Dan Loeb",
        "query": "third point",
    },
    {
        "name": "Elliott Investment Management",
        "manager": "Paul Singer",
        "query": "elliott investment management",
    },
    {
        "name": "Baupost Group",
        "manager": "Seth Klarman",
        "query": "baupost",
    },
    {
        "name": "Oaktree Capital Management",
        "manager": "Howard Marks",
        "query": "oaktree capital management",
    },
    {
        "name": "Greenlight Capital",
        "manager": "David Einhorn",
        "query": "greenlight capital",
    },
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """A single CIK candidate matched against a fund query."""

    cik: str
    company_name: str
    last_13f_hr_filing: str | None = None
    confidence: str = "unknown"  # high | medium | low | unknown


@dataclass
class FundResult:
    name: str
    manager: str
    query: str
    candidates: list[Candidate] = field(default_factory=list)
    status: str = "not_found"  # verified | ambiguous | not_found | no_recent_13f
    notes: str = ""


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _make_client() -> httpx.Client:
    """Build the shared sync httpx client with the SEC-mandated User-Agent."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json, text/html;q=0.9",
        "Host-Hint": "efts.sec.gov",
    }
    return httpx.Client(headers=headers, timeout=20.0, follow_redirects=True)


def _sleep_for_ratelimit() -> None:
    """Politeness delay between SEC requests (10 req/s ceiling)."""
    time.sleep(REQUEST_DELAY_SECONDS)


# ---------------------------------------------------------------------------
# EDGAR search
# ---------------------------------------------------------------------------


def search_edgar(client: httpx.Client, query: str) -> dict[str, Any]:
    """
    Query the EDGAR full-text search for 13F-HR filings matching `query`.

    The endpoint returns JSON of the form::

        {
          "hits": {
            "hits": [
              {
                "_id": "...",
                "_source": {
                  "ciks": ["0001067983"],
                  "display_names": ["BERKSHIRE HATHAWAY INC  (0001067983) (Filer)"],
                  "form": "13F-HR",
                  "file_date": "2025-02-14",
                  ...
                }
              },
              ...
            ],
            "total": {"value": N}
          }
        }

    Returns the parsed JSON dict (empty dict on failure).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    params = {
        "q": f'"{query}"',
        "forms": "13F-HR",
        "dateRange": "custom",
        "startdt": "2024-01-01",
        "enddt": today,
    }
    try:
        resp = client.get(EFTS_SEARCH_URL, params=params)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  ! search_edgar failed for {query!r}: {exc}", file=sys.stderr)
        return {}
    finally:
        _sleep_for_ratelimit()


def extract_ciks(response: dict[str, Any]) -> list[Candidate]:
    """
    Extract unique (cik, company_name) pairs from a full-text-search response.

    The display_name field looks like::

        "BAUPOST GROUP LLC/MA  (0001061165) (Filer)"

    We parse cik(s) from the `ciks` array and pair them with the leading
    company name in `display_names`. Duplicate CIKs are de-duplicated.
    """
    seen: dict[str, Candidate] = {}
    hits = response.get("hits", {}).get("hits", []) or []
    for hit in hits:
        src = hit.get("_source", {}) or {}
        ciks = src.get("ciks") or []
        names = src.get("display_names") or []
        for idx, cik in enumerate(ciks):
            cik_norm = str(cik).zfill(10)
            if cik_norm in seen:
                continue
            display = names[idx] if idx < len(names) else (names[0] if names else "")
            company_name = display.split("(")[0].strip() if display else ""
            seen[cik_norm] = Candidate(cik=cik_norm, company_name=company_name)
    return list(seen.values())


# ---------------------------------------------------------------------------
# Recent-13F verification per CIK
# ---------------------------------------------------------------------------


def check_recent_13f(client: httpx.Client, cik: str) -> str | None:
    """
    Check whether `cik` has filed a 13F-HR within the recent window.

    Uses https://data.sec.gov/submissions/CIK{cik}.json which returns the
    recent filings index for the given entity. Returns the ISO date of the
    most recent 13F-HR filing or None if none found.
    """
    url = SUBMISSIONS_URL.format(cik=int(cik))
    try:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  ! check_recent_13f failed for CIK {cik}: {exc}", file=sys.stderr)
        return None
    finally:
        _sleep_for_ratelimit()

    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=RECENT_WINDOW_DAYS)
    latest: str | None = None
    for form, date_str in zip(forms, dates):
        if form != "13F-HR":
            continue
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            continue
        if latest is None or date_str > latest:
            latest = date_str
    return latest


# ---------------------------------------------------------------------------
# Per-fund processing
# ---------------------------------------------------------------------------


def _classify_status(result: FundResult) -> None:
    """
    Decide the overall status string based on the candidates collected.

    Rules
    -----
    * 0 candidates                          -> not_found
    * >=1 candidate, none with recent 13F   -> no_recent_13f
    * exactly 1 candidate w/ recent 13F     -> verified
    * >1 candidate w/ recent 13F            -> ambiguous (manual triage)
    """
    if not result.candidates:
        result.status = "not_found"
        return

    recent = [c for c in result.candidates if c.last_13f_hr_filing]
    if not recent:
        result.status = "no_recent_13f"
        if not result.notes:
            result.notes = (
                "Candidate(s) found in EDGAR full-text search but no 13F-HR "
                "filing within the last 2 years. Possible reasons: "
                "confidential treatment, fund wound down, files via different "
                "advisor entity."
            )
        return

    # Mark high-confidence: exactly one recent filer
    if len(recent) == 1:
        recent[0].confidence = "high"
        result.status = "verified"
    else:
        for c in recent:
            c.confidence = "medium"
        result.status = "ambiguous"
        if not result.notes:
            result.notes = (
                f"{len(recent)} entities filed 13F-HR recently — manual "
                "selection required (e.g. parent vs. subsidiary advisor)."
            )


def process_fund(client: httpx.Client, fund: dict[str, str]) -> FundResult:
    """Run search + verification pipeline for a single fund definition."""
    result = FundResult(name=fund["name"], manager=fund["manager"], query=fund["query"])
    print(f"-> {fund['name']} (query={fund['query']!r})")

    response = search_edgar(client, fund["query"])
    candidates = extract_ciks(response)

    if not candidates:
        print("   no candidates found")
        _classify_status(result)
        return result

    print(f"   {len(candidates)} candidate(s) — verifying recent 13F-HR")
    for cand in candidates:
        last = check_recent_13f(client, cand.cik)
        cand.last_13f_hr_filing = last
        cand.confidence = "low" if last is None else "medium"
        result.candidates.append(cand)

    _classify_status(result)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point — runs the verification for every fund and writes JSON."""
    print(f"Verifying {len(FUNDS)} funds against SEC EDGAR")
    print(f"User-Agent: {USER_AGENT}")
    print(f"Output:     {OUTPUT_PATH}")
    print("-" * 60)

    results: list[FundResult] = []
    with _make_client() as client:
        for fund in FUNDS:
            try:
                results.append(process_fund(client, fund))
            except Exception as exc:  # noqa: BLE001 — script must not abort
                print(f"  !! unexpected error for {fund['name']}: {exc}", file=sys.stderr)
                results.append(
                    FundResult(
                        name=fund["name"],
                        manager=fund["manager"],
                        query=fund["query"],
                        status="not_found",
                        notes=f"Script error: {exc}",
                    )
                )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "edgar_api_used": "full-text-search (efts.sec.gov) + submissions (data.sec.gov)",
        "user_agent": USER_AGENT,
        "recent_window_days": RECENT_WINDOW_DAYS,
        "funds": [
            {
                "name": r.name,
                "manager": r.manager,
                "query": r.query,
                "candidates": [asdict(c) for c in r.candidates],
                "status": r.status,
                "notes": r.notes,
            }
            for r in results
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print("-" * 60)
    print(f"Wrote {OUTPUT_PATH}")

    # Brief summary on stdout for quick eyeballing.
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    print("Summary:", ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
