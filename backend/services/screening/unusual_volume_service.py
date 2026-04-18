"""Checks candidate tickers for unusual volume spikes using yfinance.

Liefert gleichzeitig den Close-Preis des letzten Handelstags zurueck, weil der
gleiche Batch-Download ohnehin OHLC+Volume enthaelt. Das fuellt `price_usd` auf
den Screening-Results ohne zusaetzliche API-Calls.

Wichtig: yfinance ist NICHT thread-safe — concurrent `asyncio.to_thread`-Calls
mit je einem Ticker teilen internen State (`yfdata.YfData._instances`) und
koennen Volumen/Preis-Werte eines Tickers auf andere uebertragen. Wir nutzen
daher einen einzigen Batch-Call `yf.download([t1, t2, ...])`, der die Daten
in einem HTTP-Request abholt und pro Ticker sauber in MultiIndex-Columns
zurueckliefert.
"""
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
# Hard cap for batch size (yfinance akzeptiert viele, aber wir splitten zur Sicherheit)
MAX_TICKERS = 500
BATCH_SIZE = 50


def _min_volume(ticker: str) -> int:
    return MIN_ABSOLUTE_VOLUME_CH if ticker.endswith(".SW") else MIN_ABSOLUTE_VOLUME


def _analyze_ticker_df(ticker: str, vols, closes) -> tuple[dict | None, float | None]:
    """Analysiert die Volumen-/Preis-Serie eines einzelnen Tickers.

    Gibt zurueck: (unusual_volume_payload_oder_None, latest_close_oder_None).
    """
    vols = vols.dropna()
    closes = closes.dropna()
    if len(vols) < 5:
        return None, (float(closes.iloc[-1]) if len(closes) > 0 else None)

    latest_vol = float(vols.iloc[-1])
    avg_vol = float(vols.iloc[:-1].tail(20).mean())
    latest_close = float(closes.iloc[-1]) if len(closes) > 0 else None

    if avg_vol <= 0 or latest_vol < _min_volume(ticker):
        return None, latest_close

    ratio = latest_vol / avg_vol
    if ratio >= VOLUME_MULTIPLIER:
        return {
            "latest_volume": int(latest_vol),
            "avg_volume_20d": int(avg_vol),
            "ratio": round(ratio, 1),
        }, latest_close
    return None, latest_close


def _batch_download_sync(tickers: list[str]) -> tuple[dict[str, dict], dict[str, float]]:
    """Ein Batch-Download fuer N Tickers. Gibt (unusual_volume_dict, price_dict) zurueck."""
    if not tickers:
        return {}, {}
    uv_signals: dict[str, dict] = {}
    prices: dict[str, float] = {}
    try:
        df = yf_download(tickers, period="1mo", progress=False, group_by="ticker")
        if df is None or df.empty:
            return {}, {}
    except Exception as e:
        logger.warning("Batch yf_download failed for %d tickers: %s", len(tickers), e)
        return {}, {}

    for ticker in tickers:
        try:
            # yf.download(list, group_by='ticker') liefert MultiIndex columns.
            # Single-Ticker-Sonderfall: flat columns.
            if (ticker,) in df.columns or ticker in df.columns.get_level_values(0):
                sub = df[ticker]
            else:
                continue
            if "Volume" not in sub.columns or "Close" not in sub.columns:
                continue
            uv, price = _analyze_ticker_df(ticker, sub["Volume"], sub["Close"])
            if uv:
                uv_signals[ticker] = uv
            if price is not None and price > 0:
                prices[ticker] = round(price, 4)
        except Exception as e:
            logger.debug("Ticker %s batch-parse failed: %s", ticker, e)
            continue
    return uv_signals, prices


async def enrich_scored_tickers(tickers: list[str]) -> tuple[dict[str, dict], dict[str, float]]:
    """Check scored tickers for unusual volume + collect latest close price.

    Returns:
        (volume_signals, prices) where
        - volume_signals: {ticker: {latest_volume, avg_volume_20d, ratio}}
          only for tickers >= 3x average
        - prices: {ticker: latest_close_usd} for all tickers with valid data
    """
    check_tickers = tickers[:MAX_TICKERS]
    if not check_tickers:
        return {}, {}

    logger.info("Unusual volume + price: checking %d tickers (batched)", len(check_tickers))

    uv_signals: dict[str, dict] = {}
    prices: dict[str, float] = {}

    # Batches serialisiert (kein concurrent yfinance), weil Thread-Safety-Issues bleiben.
    for i in range(0, len(check_tickers), BATCH_SIZE):
        batch = check_tickers[i:i + BATCH_SIZE]
        batch_uv, batch_prices = await asyncio.to_thread(_batch_download_sync, batch)
        uv_signals.update(batch_uv)
        prices.update(batch_prices)

    logger.info(
        "Unusual volume: %d/%d flagged. Prices collected for %d tickers.",
        len(uv_signals), len(check_tickers), len(prices),
    )
    return uv_signals, prices


# Backward-compatibility alias — alter Name, neue Implementation
async def enrich_unusual_volume(tickers: list[str]) -> dict[str, dict]:
    """Legacy signature — only returns UV signals. Prefer enrich_scored_tickers()."""
    uv, _ = await enrich_scored_tickers(tickers)
    return uv
