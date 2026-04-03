"""Downloads FINRA short volume data and computes 14-day trend per symbol."""
import asyncio
import logging
from datetime import date, timedelta

from services.api_utils import fetch_text

logger = logging.getLogger(__name__)

BASE_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
LOOKBACK_CALENDAR_DAYS = 22  # ~14 trading days
MIN_TOTAL_VOLUME = 100_000  # ignore illiquid symbols


def _parse_csv(text: str) -> dict[str, tuple[float, float]]:
    """Parse a single FINRA short volume file.

    Returns {symbol: (short_volume, total_volume)}.
    """
    result: dict[str, tuple[float, float]] = {}
    for line in text.strip().split("\n")[1:]:  # skip header
        parts = line.split("|")
        if len(parts) < 5:
            continue
        sym = parts[1]
        try:
            short_vol = float(parts[2])
            total_vol = float(parts[4])
            if total_vol >= MIN_TOTAL_VOLUME:
                result[sym] = (short_vol, total_vol)
        except (ValueError, IndexError):
            continue
    return result


async def _fetch_day(dt: date) -> dict[str, tuple[float, float]]:
    """Fetch and parse one day of FINRA short volume data."""
    url = BASE_URL.format(date=dt.strftime("%Y%m%d"))
    try:
        text = await fetch_text(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return _parse_csv(text)
    except Exception:
        return {}  # weekends / holidays simply return empty


async def fetch_short_trends() -> dict[str, dict]:
    """Fetch 14 trading days of short volume and compute trend per symbol.

    Returns {ticker: {ratio_start, ratio_end, change_pct, avg_total_volume}}.
    """
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(LOOKBACK_CALENDAR_DAYS)]

    # Fetch all days concurrently
    tasks = [_fetch_day(dt) for dt in dates]
    day_results = await asyncio.gather(*tasks)

    # Filter out empty days (weekends/holidays)
    valid_days = [(dates[i], day_results[i]) for i in range(len(dates)) if day_results[i]]
    valid_days.sort(key=lambda x: x[0])  # oldest first

    if len(valid_days) < 5:
        logger.warning("FINRA: only %d valid trading days found", len(valid_days))
        return {}

    logger.info("FINRA short volume: %d trading days loaded", len(valid_days))

    # Split into first half and second half for trend calculation
    mid = len(valid_days) // 2
    first_half = valid_days[:mid]
    second_half = valid_days[mid:]

    # Compute average short ratio for each half
    all_symbols: set[str] = set()
    for _, data in valid_days:
        all_symbols.update(data.keys())

    trends: dict[str, dict] = {}
    for sym in all_symbols:
        # First half average ratio
        first_ratios = []
        for _, data in first_half:
            if sym in data:
                s, t = data[sym]
                if t > 0:
                    first_ratios.append(s / t)

        # Second half average ratio
        second_ratios = []
        total_vols = []
        for _, data in second_half:
            if sym in data:
                s, t = data[sym]
                if t > 0:
                    second_ratios.append(s / t)
                    total_vols.append(t)

        if not first_ratios or not second_ratios:
            continue

        ratio_start = sum(first_ratios) / len(first_ratios)
        ratio_end = sum(second_ratios) / len(second_ratios)

        if ratio_start > 0:
            change_pct = ((ratio_end - ratio_start) / ratio_start) * 100
        else:
            change_pct = 0.0

        avg_vol = sum(total_vols) / len(total_vols) if total_vols else 0

        trends[sym] = {
            "ratio_start": round(ratio_start, 4),
            "ratio_end": round(ratio_end, 4),
            "change_pct": round(change_pct, 1),
            "avg_total_volume": round(avg_vol),
        }

    return trends
