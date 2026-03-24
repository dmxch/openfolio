"""Chart data services: MRS history, breakout detection, support/resistance levels, 3-point reversal."""

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
from yf_patch import yf_download

from services import cache
from services.utils import _get_close_series

logger = logging.getLogger(__name__)

PERIOD_DAYS = {"3m": 90, "6m": 180, "1y": 365, "2y": 730}


def get_mrs_history(ticker: str, period: str = "1y", benchmark: str = "^GSPC") -> list[dict]:
    """Compute weekly Mansfield Relative Strength time series."""
    cache_key = f"mrs_history:{ticker}:{period}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    stock_close = _get_close_series(ticker, "2y")
    bench_close = _get_close_series(benchmark, "2y")

    if stock_close is None or bench_close is None:
        return []

    try:
        stock_weekly = stock_close.resample("W-FRI").last().dropna()
        bench_weekly = bench_close.resample("W-FRI").last().dropna()

        common_idx = stock_weekly.index.intersection(bench_weekly.index)
        if len(common_idx) < 14:
            return []

        stock_weekly = stock_weekly.loc[common_idx]
        bench_weekly = bench_weekly.loc[common_idx]

        rs = stock_weekly / bench_weekly
        rs_ma = rs.ewm(span=13, adjust=False).mean()

        mrs = ((rs / rs_ma) - 1) * 100

        # Filter to requested period
        days = PERIOD_DAYS.get(period, 365)
        cutoff = pd.Timestamp(date.today() - timedelta(days=days))
        mrs = mrs[mrs.index >= cutoff]

        result = [
            {"date": dt.strftime("%Y-%m-%d"), "mrs": round(float(val), 2)}
            for dt, val in mrs.items()
            if not pd.isna(val)
        ]

        cache.set(cache_key, result, ttl=3600)
        return result
    except Exception as e:
        logger.warning(f"MRS history failed for {ticker}: {e}")
        return []


def get_breakout_events(ticker: str, period: str = "1y") -> list[dict]:
    """Detect historical Donchian Channel breakout events (20-day lookback)."""
    cache_key = f"breakouts:{ticker}:{period}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        days = PERIOD_DAYS.get(period, 365)
        data = yf_download(ticker, period="2y", progress=False)
        if data.empty:
            return []

        close = data["Close"]
        high = data["High"]
        volume = data["Volume"]
        for s in [close, high, volume]:
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]

        close = close.squeeze().dropna()
        high = high.squeeze().dropna()
        volume = volume.squeeze().dropna()

        if len(close) < 25:
            return []

        # Donchian Channel: 20-day highest high (shifted by 1 to exclude today)
        donchian_high = high.rolling(20).max().shift(1)
        avg_vol_20 = volume.rolling(20).mean()

        cutoff = pd.Timestamp(date.today() - timedelta(days=days))
        breakouts = []

        for i in range(21, len(close)):
            dt = close.index[i]
            if dt < cutoff:
                continue

            price = float(close.iloc[i])
            prev_price = float(close.iloc[i - 1])
            ch_high = float(donchian_high.iloc[i]) if not pd.isna(donchian_high.iloc[i]) else None
            vol = float(volume.iloc[i]) if i < len(volume) else 0
            avg_vol = float(avg_vol_20.iloc[i]) if i < len(avg_vol_20) and not pd.isna(avg_vol_20.iloc[i]) else 0

            if ch_high is None:
                continue

            # Donchian breakout: close crosses above 20-day channel high
            if price > ch_high and prev_price <= ch_high and avg_vol > 0:
                vol_ratio = round(vol / avg_vol, 1) if avg_vol > 0 else 0
                if vol_ratio >= 1.5:
                    breakouts.append({
                        "date": dt.strftime("%Y-%m-%d"),
                        "type": "breakout",
                        "price": round(price, 2),
                        "resistance": round(ch_high, 2),
                        "volume_ratio": vol_ratio,
                    })

        cache.set(cache_key, breakouts, ttl=3600)
        return breakouts
    except Exception as e:
        logger.warning(f"Breakout detection failed for {ticker}: {e}")
        return []


def get_support_resistance_levels(ticker: str) -> dict:
    """Calculate current support and resistance levels."""
    cache_key = f"levels:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        close = _get_close_series(ticker, "1y")
        if close is None or len(close) < 20:
            return {"resistance": None, "support": None, "resistance_historical": [], "support_historical": []}

        current = float(close.iloc[-1])
        high_52w = float(close.max())
        low_52w = float(close.min())

        # Simple pivot-based support/resistance
        # Resistance: 52W high and recent swing highs
        # Support: recent swing lows
        resistance_levels = []
        support_levels = []

        # Use rolling 20-day windows to find local peaks/troughs
        for i in range(20, len(close) - 5, 5):
            window = close.iloc[max(0, i - 10):i + 10]
            val = float(close.iloc[i])
            if val == float(window.max()) and val > current:
                resistance_levels.append(round(val, 2))
            elif val == float(window.min()) and val < current:
                support_levels.append(round(val, 2))

        # Deduplicate nearby levels (within 2%)
        def dedup(levels, threshold=0.02):
            if not levels:
                return []
            levels = sorted(set(levels))
            result = [levels[0]]
            for l in levels[1:]:
                if abs(l - result[-1]) / result[-1] > threshold:
                    result.append(l)
            return result

        resistance_levels = dedup(resistance_levels)[:5]
        support_levels = dedup(support_levels)[:5]

        result = {
            "ticker": ticker,
            "current_price": round(current, 2),
            "resistance": round(high_52w, 2),
            "support": round(low_52w, 2),
            "resistance_historical": resistance_levels,
            "support_historical": sorted(support_levels, reverse=True),
        }

        cache.set(cache_key, result, ttl=3600)
        return result
    except Exception as e:
        logger.warning(f"Level calculation failed for {ticker}: {e}")
        return {"resistance": None, "support": None, "resistance_historical": [], "support_historical": []}


def _find_swing_lows(closes: pd.Series, lookback: int = 5) -> list[tuple[str, float]]:
    """Find local minima (swing lows) using a symmetric lookback window.

    A point is a swing low if it is the minimum within [i-lookback, i+lookback].
    Returns list of (date_str, price) tuples.
    """
    if len(closes) < lookback * 2 + 1:
        return []

    values = closes.values
    swing_lows: list[tuple[str, float]] = []

    for i in range(lookback, len(values) - lookback):
        window = values[i - lookback:i + lookback + 1]
        if values[i] == np.min(window):
            dt = closes.index[i]
            swing_lows.append((dt.strftime("%Y-%m-%d"), float(values[i])))

    return swing_lows


def detect_three_point_reversal(closes: pd.Series, window: int = 60) -> dict:
    """Detect a 3-point reversal pattern in price data.

    Pattern: Three descending swing lows (LL1 > LL2 > LL3) followed by a
    higher low (HL > LL3), signalling a potential trend reversal from
    downtrend to uptrend.

    Args:
        closes: Daily close price series (DatetimeIndex).
        window: Number of trailing trading days to analyze (default 60).

    Returns:
        dict with "detected" bool and, if True, the pattern points.
    """
    empty = {"detected": False}

    if closes is None or len(closes) < 30:
        return empty

    # Trim to analysis window
    trimmed = closes.iloc[-window:] if len(closes) > window else closes

    swing_lows = _find_swing_lows(trimmed, lookback=5)

    if len(swing_lows) < 4:
        return empty

    # Check last 4 swing lows: first 3 must be descending, 4th must be higher than 3rd
    recent = swing_lows[-4:]
    ll1_date, ll1 = recent[0]
    ll2_date, ll2 = recent[1]
    ll3_date, ll3 = recent[2]
    hl_date, hl = recent[3]

    # Three descending lows
    if not (ll1 > ll2 > ll3):
        return empty

    # Higher low confirms reversal
    if not (hl > ll3):
        return empty

    return {
        "detected": True,
        "ll1": round(ll1, 2),
        "ll1_date": ll1_date,
        "ll2": round(ll2, 2),
        "ll2_date": ll2_date,
        "ll3": round(ll3, 2),
        "ll3_date": ll3_date,
        "hl": round(hl, 2),
        "hl_date": hl_date,
    }


def get_three_point_reversal(ticker: str) -> dict:
    """Check if a ticker shows a 3-point reversal pattern (cached)."""
    cache_key = f"reversal_3pt:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        close = _get_close_series(ticker, "6m")
        if close is None or len(close) < 30:
            return {"detected": False}

        result = detect_three_point_reversal(close, window=60)
        cache.set(cache_key, result, ttl=3600)
        return result
    except Exception as e:
        logger.warning(f"3-point reversal detection failed for {ticker}: {e}")
        return {"detected": False}
