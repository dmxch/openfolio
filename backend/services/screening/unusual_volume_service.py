"""Checks candidate tickers for unusual volume spikes using yfinance."""
import asyncio
import logging

from yf_patch import yf_download

logger = logging.getLogger(__name__)

# Volume must be at least 3x the 20-day average to be "unusual"
VOLUME_MULTIPLIER = 3.0
# Minimum absolute volume to avoid micro-cap noise
MIN_ABSOLUTE_VOLUME = 200_000
# Swiss (.SW) tickers have structurally lower volume than US equities
MIN_ABSOLUTE_VOLUME_CH = 5_000
# Max tickers to check (yfinance is per-ticker, so we limit)
MAX_TICKERS = 150


def _check_volume_sync(ticker: str) -> dict | None:
    """Check if a ticker has unusual volume (synchronous, for use with asyncio.to_thread)."""
    try:
        df = yf_download(ticker, period="25d", progress=False)
        if df is None or df.empty or len(df) < 5:
            return None

        # Handle multi-level columns from yf_download
        vol_col = None
        for col in df.columns:
            col_name = col[0] if isinstance(col, tuple) else col
            if col_name.lower() == "volume":
                vol_col = col
                break
        if vol_col is None:
            return None

        volumes = df[vol_col].dropna()
        if len(volumes) < 5:
            return None

        latest_vol = float(volumes.iloc[-1])
        avg_vol = float(volumes.iloc[:-1].tail(20).mean())

        # Use lower threshold for Swiss tickers
        min_vol = MIN_ABSOLUTE_VOLUME_CH if ticker.endswith(".SW") else MIN_ABSOLUTE_VOLUME

        if avg_vol <= 0 or latest_vol < min_vol:
            return None

        ratio = latest_vol / avg_vol
        if ratio >= VOLUME_MULTIPLIER:
            return {
                "latest_volume": int(latest_vol),
                "avg_volume_20d": int(avg_vol),
                "ratio": round(ratio, 1),
            }
    except Exception:
        pass
    return None


async def enrich_unusual_volume(tickers: list[str]) -> dict[str, dict]:
    """Check a list of candidate tickers for unusual volume.

    Only checks up to MAX_TICKERS to keep scan time reasonable.
    Returns {ticker: {latest_volume, avg_volume_20d, ratio}}.
    """
    check_tickers = tickers[:MAX_TICKERS]
    if not check_tickers:
        return {}

    logger.info("Unusual volume: checking %d tickers", len(check_tickers))

    # Run in batches of 10 to avoid overwhelming yfinance
    results: dict[str, dict] = {}
    batch_size = 10

    for i in range(0, len(check_tickers), batch_size):
        batch = check_tickers[i:i + batch_size]
        tasks = [asyncio.to_thread(_check_volume_sync, t) for t in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for ticker, result in zip(batch, batch_results):
            if isinstance(result, dict) and result is not None:
                results[ticker] = result

    logger.info("Unusual volume: %d of %d tickers flagged", len(results), len(check_tickers))
    return results
