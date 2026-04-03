"""Downloads SEC Fails-to-Deliver data and flags tickers with high FTD counts."""
import io
import logging
import zipfile
from datetime import date

from services.api_utils import get_async_client

logger = logging.getLogger(__name__)

SEC_UA = "OpenFolio/1.0 screening@openfolio.dev"
# FTD files are published in half-month chunks: {YYYYMM}a (1st-15th) and {YYYYMM}b (16th-end)
FTD_URL = "https://www.sec.gov/files/data/fails-deliver-data/cnsfails{period}.zip"

# Minimum total FTD shares across the half-month to flag as significant
MIN_FTD_SHARES = 500_000


def _get_latest_periods() -> list[str]:
    """Return the two most recent FTD period codes (e.g. '202603b', '202603a')."""
    today = date.today()
    y, m = today.year, today.month

    periods = []
    if today.day > 20:
        # Second half of current month might be available
        periods.append(f"{y}{m:02d}b")
    periods.append(f"{y}{m:02d}a")

    # Previous month
    pm = m - 1 if m > 1 else 12
    py = y if m > 1 else y - 1
    periods.append(f"{py}{pm:02d}b")
    periods.append(f"{py}{pm:02d}a")

    return periods


def _parse_ftd_text(text: str) -> dict[str, int]:
    """Parse FTD pipe-delimited data into {symbol: total_ftd_shares}."""
    ftd_by_sym: dict[str, int] = {}
    for line in text.strip().split("\n")[1:]:  # skip header
        parts = line.split("|")
        if len(parts) < 4:
            continue
        sym = parts[2].strip()
        if not sym:
            continue
        try:
            qty = int(parts[3])
            ftd_by_sym[sym] = ftd_by_sym.get(sym, 0) + qty
        except (ValueError, IndexError):
            continue
    return ftd_by_sym


async def fetch_ftd_data() -> dict[str, dict]:
    """Fetch the latest available FTD data from SEC.

    Returns {ticker: {total_shares, period}}.
    """
    client = get_async_client()
    periods = _get_latest_periods()

    for period in periods:
        url = FTD_URL.format(period=period)
        try:
            resp = await client.get(url, headers={"User-Agent": SEC_UA}, timeout=20)
            if resp.status_code != 200:
                continue

            zip_bytes = resp.content
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for name in zf.namelist():
                    with zf.open(name) as f:
                        text = f.read().decode("utf-8", errors="replace")
                        ftd_by_sym = _parse_ftd_text(text)

                        # Filter to significant FTDs only
                        results: dict[str, dict] = {}
                        for sym, total in ftd_by_sym.items():
                            if total >= MIN_FTD_SHARES:
                                results[sym] = {
                                    "total_shares": total,
                                    "period": period,
                                }

                        logger.info(
                            "SEC FTD (%s): %d total symbols, %d with >= %d shares",
                            period, len(ftd_by_sym), len(results), MIN_FTD_SHARES,
                        )
                        return results

        except Exception:
            logger.warning("FTD period %s not available", period)
            continue

    logger.warning("No FTD data available from any period")
    return {}
