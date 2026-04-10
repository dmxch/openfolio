"""Fetches management transaction buys from SIX SER (Swiss Exchange Regulation).

SIX SER publishes mandatory management transaction notifications at:
https://www.ser-ag.com/en/resources/notifications-market-participants/management-transactions.html

The underlying JSON API is public, paginated, and requires no authentication.
"""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from services.api_utils import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.ser-ag.com/sheldon/management_transactions/v1"

# Conservative delay between paginated requests (no visible rate limit,
# but we want to be a good citizen).
_REQUEST_DELAY = 0.5

# Security type codes that represent equity (shares).
# "1" = Beteiligungsrechte (shares), "7" = Verguetungsaktien (compensation shares).
# Options, convertible bonds etc. are excluded.
_EQUITY_SECURITY_TYPES = {"1", "7"}

# Obligor function code labels (SIX SER codes).
_OBLIGOR_LABELS: dict[str, str] = {
    "1": "Mitglied der Geschaeftsleitung",
    "2": "VR-Mitglied",
    "3": "Revisionsstelle",
    "4": "Nahestehende Person",
}

# Mapping: SIX SER submitter ID -> yfinance ticker (.SW suffix).
# Covers SMI-30 + key SMIM constituents. Unknown issuers are logged and skipped.
# Source: issuers.json from SER API, manually verified against yfinance.
ISSUER_TICKER_MAP: dict[str, str] = {
    # SMI constituents (verified against issuers.json Id field)
    "ABBLTD": "ABBN.SW",
    "ALCON": "ALC.SW",
    "GIVAUDAN": "GIVN.SW",
    "HOLCIM": "HOLN.SW",
    "KUEHNE": "KNIN.SW",
    "LOGITECH": "LOGN.SW",
    "LONZA": "LONN.SW",
    "NESTLE": "NESN.SW",
    "NOVARTIS": "NOVN.SW",
    "PARTNERS": "PGHN.SW",
    "RICHEMONT": "CFR.SW",
    "ROCHE": "ROG.SW",
    "SANDGR": "SDZ.SW",
    "SCHINDLER": "SCHN.SW",
    "SGS": "SGSN.SW",
    "SIKA": "SIKA.SW",
    "PHONAK": "SOON.SW",       # Sonova (historical name in SER)
    "SWISSCOM": "SCMN.SW",
    "SLH": "SLHN.SW",          # Swiss Life
    "BKUBSG": "UBSG.SW",       # UBS Group
    "ZFSZH": "ZURN.SW",        # Zurich Insurance
    "ZFSZHOLS": "ZURN.SW",     # Zurich Insurance (alt ID)
    "SWISSREAG": "SREN.SW",    # Swiss Re
    "GEBERIT": "GEBN.SW",
    "STRAUMANN": "STMN.SW",
    "BAER": "BAER.SW",         # Julius Baer
    # SMIM / SPI extended (verified against issuers.json)
    "ADECCO": "ADEN.SW",
    "ALSO": "ALSN.SW",
    "ARYZ": "ARYN.SW",
    "AUTONEUM": "AUTN.SW",
    "BACHEMHOL": "BANB.SW",
    "BALOISE": "BALN.SW",
    "BARRY": "BARN.SW",
    "BELIMO": "BEAN.SW",
    "BKWAG": "BKW.SW",
    "BOSSARD": "BOSN.SW",
    "BUCHER": "BUCN.SW",
    "CLARIANT": "CLN.SW",
    "MEDIS": "CLTN.SW",        # COLTENE (historical name in SER)
    "DKSH": "DKSH.SW",
    "ZURROSE": "DOCM.SW",      # DocMorris (formerly Zur Rose)
    "EMMI": "EMMN.SW",
    "FLUGHAFEN": "FHZN.SW",
    "GALDERMA": "GALD.SW",
    "GALSAN": "GALE.SW",       # Galenica
    "GF": "GF.SW",             # Georg Fischer
    "HUBER": "HUBN.SW",
    "IMPLENIA": "IMPN.SW",
    "INTERSHOP": "ISN.SW",
    "KARDEX": "KARN.SW",
    "KOMAX": "KOMN.SW",
    "LINDT": "LISP.SW",
    "MEDARTIS": "MED.SW",
    "MOBILEZ": "MOZN.SW",
    "UNAXIS": "OERL.SW",       # Oerlikon (historical name in SER)
    "PHOENIX": "PM.SW",        # Phoenix Mecano
    "SCHWEITER": "SWTQ.SW",
    "SIEGFRIED": "SFZN.SW",
    "STADRA": "SRAIL.SW",      # Stadler Rail
    "TEMENOS": "TEMN.SW",
    "SWATCH": "UHR.SW",
    "YPSOMED": "YPSN.SW",
    "ZEHNDER": "ZEHN.SW",
    "AUTMICROS": "AMS.SW",     # ams-OSRAM
    "KABA": "DOKA.SW",         # dormakaba
    "DUFRY": "AVOL.SW",        # Avolta (formerly Dufry)
    "BKVTH": "VONN.SW",        # Vontobel
    "SULZER": "SUN.SW",
    "SWISSQUOT": "SQN.SW",
    "HELVETIAP": "HELN.SW",    # Helvetia (now Helvetia Baloise)
    "PRIMESITE": "SPSN.SW",    # Swiss Prime Site
    "SCG": "SIGN.SW",          # SIG Group
    "SOFONE": "SWON.SW",       # SoftwareOne
    "TECAN": "TECN.SW",
    "VATGROUP": "VACN.SW",
}

# Cache for issuer list (loaded once per process lifetime)
_issuer_cache: list[dict] | None = None


async def _load_issuers() -> list[dict]:
    """Load issuer list from SIX SER API (cached)."""
    global _issuer_cache
    if _issuer_cache is not None:
        return _issuer_cache

    url = f"{_BASE_URL}/issuers.json"
    try:
        data = await fetch_json(url, timeout=20)
        issuers = data if isinstance(data, list) else data.get("itemList", data.get("data", []))
        _issuer_cache = issuers
        logger.info("SIX SER: loaded %d issuers", len(issuers))

        # Log unmapped issuers for future mapping expansion
        mapped_ids = set(ISSUER_TICKER_MAP.keys())
        for iss in issuers:
            iss_id = iss.get("Id") or iss.get("id") or iss.get("submitterId", "")
            if iss_id and iss_id not in mapped_ids:
                iss_name = iss.get("Name") or iss.get("name") or ""
                logger.debug("SIX SER: unmapped issuer %s (%s)", iss_id, iss_name)

        return issuers
    except Exception as e:
        logger.error("SIX SER: failed to load issuers: %s", e)
        return []


async def _fetch_transactions(days: int) -> list[dict]:
    """Fetch buy transactions from SIX SER with pagination."""
    from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y%m%d")

    all_transactions: list[dict] = []
    page = 1
    page_size = 100

    while True:
        params = {
            "pageSize": page_size,
            "pageNumber": page,
            "sortAttribute": "TransactionDate desc",
            "buySellIndicator": "1",  # buys only
            "fromDate": from_date,
        }

        try:
            data = await fetch_json(f"{_BASE_URL}/overview.json", params=params, timeout=20)
        except Exception as e:
            logger.error("SIX SER: page %d fetch failed: %s", page, e)
            break

        # The API returns either a list directly or a wrapper with "data"/"items"
        items = data if isinstance(data, list) else data.get("itemList", data.get("data", []))

        if not items:
            break

        all_transactions.extend(items)
        logger.debug("SIX SER: fetched page %d (%d items)", page, len(items))

        # If we got fewer items than page_size, we've reached the last page
        if len(items) < page_size:
            break

        page += 1
        await asyncio.sleep(_REQUEST_DELAY)

    logger.info("SIX SER: fetched %d buy transactions (last %d days)", len(all_transactions), days)
    return all_transactions


def _parse_transaction_date(raw: int | str) -> str:
    """Convert SIX date format (YYYYMMDD int) to ISO date string."""
    s = str(raw)
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


async def fetch_six_insider_buys(days: int = 90) -> list[dict]:
    """Fetch recent management transaction buys from SIX SER.

    Returns aggregated list per ticker:
    [
        {
            "ticker": "NESN.SW",
            "company": "Nestle SA",
            "transaction_count": 3,
            "total_amount_chf": 450000.0,
            "latest_date": "2026-04-09",
            "obligor_functions": ["VR-Mitglied", "CEO"],
            "isin": "CH0038863350",
            "issuer_id": "NESTLE",
            "distinct_obligor_count": 2,
        },
        ...
    ]
    """
    # Load issuers in parallel with transactions (for logging unmapped ones)
    issuers_task = asyncio.create_task(_load_issuers())
    transactions = await _fetch_transactions(days)
    await issuers_task

    # Filter: only equity security types
    equity_txns = [
        t for t in transactions
        if str(t.get("securityTypeCode", "")) in _EQUITY_SECURITY_TYPES
    ]
    logger.info("SIX SER: %d of %d transactions are equity", len(equity_txns), len(transactions))

    # Group by issuer
    by_issuer: dict[str, list[dict]] = defaultdict(list)
    unmapped_issuers: set[str] = set()

    for txn in equity_txns:
        issuer_id = txn.get("notificationSubmitterId", "")
        if not issuer_id:
            continue

        ticker = ISSUER_TICKER_MAP.get(issuer_id)
        if not ticker:
            unmapped_issuers.add(issuer_id)
            continue

        by_issuer[issuer_id].append(txn)

    if unmapped_issuers:
        logger.warning(
            "SIX SER: %d unmapped issuers with buy transactions: %s",
            len(unmapped_issuers),
            ", ".join(sorted(unmapped_issuers)),
        )

    # Aggregate per issuer -> one signal per ticker
    results: list[dict] = []
    for issuer_id, txns in by_issuer.items():
        ticker = ISSUER_TICKER_MAP[issuer_id]
        company = txns[0].get("notificationSubmitter", issuer_id)

        total_amount = sum(float(t.get("transactionAmountCHF", 0) or 0) for t in txns)

        # Collect distinct obligor functions
        func_codes = set()
        for t in txns:
            code = str(t.get("obligorFunctionCode", ""))
            if code:
                func_codes.add(code)

        obligor_labels = [
            _OBLIGOR_LABELS.get(c, f"Funktion {c}") for c in sorted(func_codes)
        ]

        # Latest transaction date
        dates = []
        for t in txns:
            raw = t.get("transactionDate")
            if raw:
                dates.append(_parse_transaction_date(raw))
        latest_date = max(dates) if dates else ""

        # ISIN from first transaction (all should be same issuer)
        isin = txns[0].get("ISIN", "")

        results.append({
            "ticker": ticker,
            "company": company,
            "transaction_count": len(txns),
            "total_amount_chf": total_amount,
            "latest_date": latest_date,
            "obligor_functions": obligor_labels,
            "isin": isin,
            "issuer_id": issuer_id,
            "distinct_obligor_count": len(func_codes),
        })

    # Sort by total amount descending
    results.sort(key=lambda r: r["total_amount_chf"], reverse=True)

    logger.info(
        "SIX SER: %d ticker signals from %d equity transactions (%d unmapped issuers skipped)",
        len(results),
        len(equity_txns),
        len(unmapped_issuers),
    )
    return results
