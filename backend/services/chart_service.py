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
    """Detect historical Donchian-Breakout events with **2-day confirmation**.

    Phase A change: ein Breakout wird erst dann gelistet, wenn er am Folgetag
    bestätigt wurde (Close > 20d-Hoch des Vortags am Tag 2). Verhindert
    False Positives durch 1-Tages-Spikes / Fakeouts. Tag 1 selbst erscheint
    nur als ``status="pending"`` Eintrag, wenn er in den letzten Tagen liegt
    (so kann das Frontend einen Hourglass-Marker rendern).
    """
    cache_key = f"breakouts:{ticker}:{period}:v2"
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
            avg_vol = (
                float(avg_vol_20.iloc[i])
                if i < len(avg_vol_20) and not pd.isna(avg_vol_20.iloc[i])
                else 0
            )

            if ch_high is None:
                continue

            # Tag 1: classical Donchian-Breakout-Trigger
            is_breakout_day1 = price > ch_high and prev_price <= ch_high and avg_vol > 0
            if not is_breakout_day1:
                continue

            vol_ratio = round(vol / avg_vol, 1) if avg_vol > 0 else 0
            if vol_ratio < 1.5:
                continue

            # 2-Tages-Confirm: am Folgetag (i+1) muss Close auch über
            # demselben 20d-Hoch (ch_high) liegen. Wenn i der letzte Tag im
            # Datensatz ist → pending (Tag 2 noch nicht verfügbar).
            if i + 1 >= len(close):
                # Pending: Tag 1 heute, Tag 2 noch nicht beurteilbar
                breakouts.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "type": "breakout",
                    "status": "pending",
                    "price": round(price, 2),
                    "resistance": round(ch_high, 2),
                    "volume_ratio": vol_ratio,
                })
                continue

            day2_close = float(close.iloc[i + 1])
            if day2_close > ch_high:
                # Confirmed: Tag 2 hält das Niveau
                breakouts.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "type": "breakout",
                    "status": "confirmed",
                    "price": round(price, 2),
                    "resistance": round(ch_high, 2),
                    "volume_ratio": vol_ratio,
                    "day2_close": round(day2_close, 2),
                    "day2_date": close.index[i + 1].strftime("%Y-%m-%d"),
                })
            # Sonst: Fakeout — wird nicht im Widget gelistet (Tag 2 fiel zurück)

        cache.set(cache_key, breakouts, ttl=3600)
        return breakouts
    except Exception as e:
        logger.warning(f"Breakout detection failed for {ticker}: {e}")
        return []


def check_breakout_confirmed_today(
    closes: pd.Series, highs: pd.Series, volumes: pd.Series,
) -> dict:
    """Phase A: 4-State-Status für das Score-Kriterium id=8.

    Untersucht den letzten Donchian-Breakout-Versuch im Datenfenster und
    liefert einen Tri-State-Status mit Reason-Code für die UI:

    - ``passed=True, reason=None`` — gestern (Tag 1) Breakout, heute (Tag 2)
      über Resistance gehalten = bestätigt
    - ``passed=None, pending=True, reason="awaiting_day2"`` — heute (Tag 1)
      ist der Breakout, Tag 2 noch nicht beurteilbar (Frühwarn-Effekt
      bleibt im UI sichtbar mit Hourglass-Icon)
    - ``passed=False, reason="fakeout"`` — Breakout in den letzten 5 Tagen
      versucht, aber Tag 2 fiel zurück unter Resistance
    - ``passed=False, reason="no_breakout"`` — kein Ausbruch im Window

    Returns dict für direkte Übernahme ins criteria-Item.
    """
    if closes is None or len(closes) < 22 or highs is None or volumes is None:
        return {"passed": False, "reason": "no_data", "pending": False}

    donchian_high = highs.rolling(20).max().shift(1)
    avg_vol_20 = volumes.rolling(20).mean()

    today_idx = len(closes) - 1
    yesterday_idx = today_idx - 1

    def _is_breakout_at(i: int) -> tuple[bool, float | None, float | None]:
        if i < 21 or i >= len(closes):
            return False, None, None
        ch = donchian_high.iloc[i]
        prev = closes.iloc[i - 1]
        cur = closes.iloc[i]
        v = volumes.iloc[i] if i < len(volumes) else 0
        avg = avg_vol_20.iloc[i] if i < len(avg_vol_20) else 0
        if pd.isna(ch) or pd.isna(avg) or avg <= 0:
            return False, None, None
        if cur <= ch or prev > ch:
            return False, None, None
        vol_ratio = float(v) / float(avg)
        if vol_ratio < 1.5:
            return False, None, None
        return True, float(ch), float(cur)

    # Pending: heute der Tag 1
    is_today_breakout, ch_today, _ = _is_breakout_at(today_idx)
    if is_today_breakout:
        return {
            "passed": None,
            "pending": True,
            "reason": "awaiting_day2",
            "breakout_date": closes.index[today_idx].strftime("%Y-%m-%d"),
            "resistance": round(ch_today, 2) if ch_today else None,
        }

    # Confirmed: gestern Tag 1, heute über Resistance
    is_yesterday_breakout, ch_yesterday, _ = _is_breakout_at(yesterday_idx)
    if is_yesterday_breakout:
        if float(closes.iloc[today_idx]) > ch_yesterday:
            return {
                "passed": True,
                "pending": False,
                "reason": None,
                "breakout_date": closes.index[yesterday_idx].strftime("%Y-%m-%d"),
                "resistance": round(ch_yesterday, 2),
            }
        else:
            return {
                "passed": False,
                "pending": False,
                "reason": "fakeout",
                "breakout_date": closes.index[yesterday_idx].strftime("%Y-%m-%d"),
                "resistance": round(ch_yesterday, 2),
            }

    # Fakeout in den letzten 5 Tagen?
    for i in range(today_idx - 5, today_idx - 1):
        if i < 22:
            continue
        is_brk, ch_b, _ = _is_breakout_at(i)
        if not is_brk:
            continue
        # Day-2 = i+1
        if i + 1 < len(closes) and float(closes.iloc[i + 1]) <= ch_b:
            return {
                "passed": False,
                "pending": False,
                "reason": "fakeout",
                "breakout_date": closes.index[i].strftime("%Y-%m-%d"),
                "resistance": round(ch_b, 2),
            }

    return {"passed": False, "pending": False, "reason": "no_breakout"}


def _winsorized_mean(series: pd.Series, top_n_to_trim: int) -> float:
    """Mean nach Trimmung der Top-N höchsten Werte (Winsorization gegen
    Earnings-Spikes). Wenn Series zu kurz: einfacher Mean ohne Trim."""
    if series is None or len(series) == 0:
        return 0.0
    if len(series) <= top_n_to_trim:
        return float(series.mean())
    sorted_vals = series.sort_values(ascending=False)
    trimmed = sorted_vals.iloc[top_n_to_trim:]
    return float(trimmed.mean())


def detect_volume_confirmation(
    closes: pd.Series,
    volumes: pd.Series,
    current_mcap: float | None = None,
    mcap_history_avg_90d: float | None = None,
) -> dict:
    """Phase A: Volume-Confirmation als asymmetrischer Modifier (-1/0/+1).

    Misst Divergenz zwischen Preis-Trend und Volumen-Trend über dasselbe
    Zeitfenster ("Volume Confirmation" — Wyckoff/O'Neil-Tradition).

    - PriceSlope: Linear-Regression der letzten 20 Closes, normalisiert auf
      ``closes[-20]``, in Prozent. Eliminiert Endpunkt-Verzerrung im Vergleich
      zu ``(close[-1] - close[-20]) / close[-20]``.
    - VolRatio: Winsorized-Mean(volumes_20d) / Winsorized-Mean(volumes_60d).
      Top-3-Volume-Tage in jedem Fenster getrimmt, damit ein Earnings-Spike
      das Verhältnis nicht wochenlang verzerrt.
    - Mega-Cap-Cap (mcap_history_avg_90d > 500B): Schwellen verschärft auf
      0.75/1.25 statt 0.85/1.15, weil Mega-Cap-VolRatio strukturell näher
      an 1.0 klebt (institutionelle Liquidität, Index-Rebalancing).

    Returns dict mit ``score_modifier``, ``slope_pct``, ``vol_ratio``,
    ``regime`` ("standard"|"megacap"), ``reason`` (für UI-Detail).
    """
    from services.analysis_config import (
        VOLUME_CONFIRM_MEGACAP_RATIO_HIGH,
        VOLUME_CONFIRM_MEGACAP_RATIO_LOW,
        VOLUME_CONFIRM_MEGACAP_THRESHOLD_USD,
        VOLUME_CONFIRM_RATIO_HIGH,
        VOLUME_CONFIRM_RATIO_LOW,
        VOLUME_CONFIRM_SLOPE_THRESHOLD_PCT,
        VOLUME_CONFIRM_WINSORIZATION_TOP_N,
    )

    base = {
        "score_modifier": None,
        "slope_pct": None,
        "vol_ratio": None,
        "regime": "standard",
        "reason": "no_data",
    }

    if closes is None or volumes is None or len(closes) < 60 or len(volumes) < 60:
        return base

    closes = closes.dropna()
    volumes = volumes.dropna()
    if len(closes) < 60 or len(volumes) < 60:
        return base

    # PriceSlope via Linear-Regression (OLS) über 20 Closes — numpy-only
    # (scipy ist im Container nicht installiert; OLS-Slope ist trivial).
    last20 = closes.iloc[-20:].values
    if len(last20) < 20 or last20[0] <= 0:
        return base
    try:
        x = np.arange(20, dtype=float)
        y = last20.astype(float)
        x_mean = float(x.mean())
        y_mean = float(y.mean())
        denom = float(((x - x_mean) ** 2).sum())
        if denom == 0:
            return base
        slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
    except Exception as e:
        logger.debug(f"slope computation failed in volume_confirmation: {e}")
        return base

    slope_pct = (slope * 20) / float(last20[0]) * 100  # 20-Tage-Performance laut Trendlinie

    # VolRatio via Winsorized-Mean (Top-3 trimmen)
    avg20 = _winsorized_mean(volumes.iloc[-20:], VOLUME_CONFIRM_WINSORIZATION_TOP_N)
    avg60 = _winsorized_mean(volumes.iloc[-60:], VOLUME_CONFIRM_WINSORIZATION_TOP_N)
    if avg60 <= 0:
        return {**base, "slope_pct": round(slope_pct, 2)}
    vol_ratio = avg20 / avg60

    # Regime: Mega-Cap wenn 90d-smoothed MCap > 500B
    is_megacap = (
        mcap_history_avg_90d is not None
        and mcap_history_avg_90d > VOLUME_CONFIRM_MEGACAP_THRESHOLD_USD
    )
    regime = "megacap" if is_megacap else "standard"

    if is_megacap:
        ratio_low = VOLUME_CONFIRM_MEGACAP_RATIO_LOW
        ratio_high = VOLUME_CONFIRM_MEGACAP_RATIO_HIGH
    else:
        ratio_low = VOLUME_CONFIRM_RATIO_LOW
        ratio_high = VOLUME_CONFIRM_RATIO_HIGH

    # Slope-Grauzone: |slope| ≤ 3% → modifier=0
    threshold = VOLUME_CONFIRM_SLOPE_THRESHOLD_PCT
    if abs(slope_pct) <= threshold:
        modifier = 0
        reason = "neutral_trend"
    elif slope_pct > threshold:
        # Aufwärtstrend
        if vol_ratio < ratio_low:
            modifier, reason = -1, "bearish_divergence"
        elif vol_ratio > ratio_high:
            modifier, reason = 1, "healthy_confirmation"
        else:
            modifier, reason = 0, "neutral_volume"
    else:
        # Abwärtstrend (slope_pct < -threshold)
        if vol_ratio > ratio_high:
            modifier, reason = -1, "distribution_selling"
        elif vol_ratio < ratio_low:
            modifier, reason = 0, "healthy_pullback"
        else:
            modifier, reason = 0, "neutral_volume"

    return {
        "score_modifier": modifier,
        "slope_pct": round(slope_pct, 2),
        "vol_ratio": round(vol_ratio, 3),
        "regime": regime,
        "reason": reason,
    }


def compute_industry_mrs_simple(db, ticker: str) -> dict:
    """Phase A: Industry-MRS (perf_3m direkt vs S&P-perf_3m).

    Lookup-Reihenfolge: ``INDUSTRY_OVERRIDES`` (Phase-A-Falsch-Mapping-Korrektur,
    Vorrang) → ``ticker_industries.industry_name`` → market_industries.perf_3m.
    Vergleich gegen S&P-Benchmark mit ±2pp Buffer-Zone gegen Endpunkt-Sensitivität.

    Synchron (kein async/await), weil das aus dem synchronen score_stock-Pfad
    aufgerufen wird. ``db`` ist eine SQLAlchemy synchronous Connection oder
    Engine. In Phase A nutzen wir keinen DB-Lookup über Async-Session — wir
    nehmen direkt die ``MarketIndustry``-Snapshots via gleichem Pattern wie
    ``get_three_point_reversal``.
    """
    from services.analysis_config import (
        INDUSTRY_MRS_BENCHMARK,
        INDUSTRY_MRS_BUFFER_PCT,
        INDUSTRY_OVERRIDES,
    )

    base = {
        "passed": None,
        "industry_name": None,
        "industry_perf_3m": None,
        "benchmark_perf_3m": None,
        "diff_pp": None,
        "reason": None,
    }

    ticker_upper = ticker.upper()

    # 1. Override hat Vorrang
    industry_name = INDUSTRY_OVERRIDES.get(ticker_upper)

    # 2. Falls kein Override → DB-Lookup über synchronous engine
    if industry_name is None:
        try:
            from db import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                row = conn.execute(
                    text("SELECT industry_name FROM ticker_industries WHERE ticker = :t"),
                    {"t": ticker_upper},
                ).first()
                if row is None:
                    return {**base, "reason": "ticker_not_in_mapping"}
                industry_name = row[0]
        except Exception as e:
            logger.debug(f"industry_name lookup failed for {ticker}: {e}")
            return {**base, "reason": "db_lookup_failed"}

    base["industry_name"] = industry_name

    # 3. Latest market_industries-Row für diese Industry
    try:
        from db import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT perf_3m FROM market_industries "
                    "WHERE name = :n "
                    "ORDER BY scraped_at DESC LIMIT 1"
                ),
                {"n": industry_name},
            ).first()
            if row is None or row[0] is None:
                return {**base, "reason": "no_industry_snapshot"}
            industry_perf_3m = float(row[0])
    except Exception as e:
        logger.debug(f"market_industries lookup failed for {industry_name}: {e}")
        return {**base, "reason": "db_lookup_failed"}

    # 4. Benchmark perf_3m aus Cache oder yfinance
    cache_key = f"benchmark_perf_3m:{INDUSTRY_MRS_BENCHMARK}"
    benchmark_perf_3m = cache.get(cache_key)
    if benchmark_perf_3m is None:
        try:
            bench_close = _get_close_series(INDUSTRY_MRS_BENCHMARK, "6m")
            if bench_close is None or len(bench_close) < 60:
                return {**base, "industry_perf_3m": industry_perf_3m, "reason": "no_benchmark"}
            close_now = float(bench_close.iloc[-1])
            close_60d_ago = float(bench_close.iloc[-60])
            benchmark_perf_3m = ((close_now - close_60d_ago) / close_60d_ago) * 100
            cache.set(cache_key, benchmark_perf_3m, ttl=3600)
        except Exception as e:
            logger.debug(f"benchmark perf_3m computation failed: {e}")
            return {**base, "industry_perf_3m": industry_perf_3m, "reason": "benchmark_error"}

    diff_pp = industry_perf_3m - benchmark_perf_3m
    buffer_pp = INDUSTRY_MRS_BUFFER_PCT * 100  # 0.02 → 2.0 Prozentpunkte

    if diff_pp > buffer_pp:
        passed = True
    elif diff_pp < -buffer_pp:
        passed = False
    else:
        passed = None  # neutrale Buffer-Zone

    return {
        "passed": passed,
        "industry_name": industry_name,
        "industry_perf_3m": round(industry_perf_3m, 2),
        "benchmark_perf_3m": round(benchmark_perf_3m, 2),
        "diff_pp": round(diff_pp, 2),
        "reason": None,
    }


def compute_industry_mrs_rolling(db, ticker: str) -> dict:
    """Phase 2 (NICHT in Phase A implementiert): Mansfield-Stil Industry-MRS.

    Plan: aus den täglichen MarketIndustry-Snapshots eine Industry-Close-
    Approximation bauen (perf_1w kumulativ aggregiert), wöchentlich
    sampeln, gegen ^GSPC-Wochen-Closes verhältnis bilden, EMA-13 darauf,
    Mansfield-Formel ((rs/rs_ma) - 1) * 100. Braucht 90+ Tage Snapshot-
    Historie, die heute noch nicht vorliegt.

    Drop-in-Replacement-fähig: Caller in stock_scorer kann einfach den
    Import wechseln.
    """
    return {
        "passed": None,
        "industry_name": None,
        "industry_perf_3m": None,
        "benchmark_perf_3m": None,
        "diff_pp": None,
        "reason": "phase_2_not_implemented",
    }


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


def _find_swing_highs(closes: pd.Series, lookback: int = 5) -> list[tuple[str, float]]:
    """Find local maxima (swing highs), symmetric counterpart of ``_find_swing_lows``.

    A point is a swing high if it is the maximum within
    ``[i-lookback, i+lookback]``. Returns list of (date_str, price) tuples.
    """
    if len(closes) < lookback * 2 + 1:
        return []

    values = closes.values
    swing_highs: list[tuple[str, float]] = []

    for i in range(lookback, len(values) - lookback):
        window = values[i - lookback:i + lookback + 1]
        if values[i] == np.max(window):
            dt = closes.index[i]
            swing_highs.append((dt.strftime("%Y-%m-%d"), float(values[i])))

    return swing_highs


def detect_ma_cross_50_150(closes: pd.Series) -> dict:
    """Detect a 50/150 MA cross within the lookback window.

    Returns a tri-state result that distinguishes a clean bullish cross,
    a clean death cross, a whipsaw (both directions in the window), a
    "failed" cross (price has moved >MA_CROSS_FAILED_PCT against the
    direction since the cross — setup invalidated), and "no cross".
    Callers in the score pipeline should treat ``passed`` as None when
    ``reason in ("failed_cross", "whipsaw", "no_data")`` so the
    aggregation does not compensate risk through data scarcity.
    """
    from services.analysis_config import (
        MA_CROSS_FAST,
        MA_CROSS_SLOW,
        MA_CROSS_LOOKBACK_DAYS,
        MA_CROSS_FAILED_PCT,
    )

    empty = {
        "detected": False,
        "type": None,
        "cross_date": None,
        "cross_price": None,
        "current_price": None,
        "pct_since_cross": None,
        "whipsaw": False,
        "reason": "no_data",
        "ma_fast_now": None,
        "ma_slow_now": None,
    }

    if closes is None or len(closes) < MA_CROSS_SLOW + 2:
        return empty

    ma_fast = closes.rolling(MA_CROSS_FAST).mean()
    ma_slow = closes.rolling(MA_CROSS_SLOW).mean()
    diff = ma_fast - ma_slow

    # Restrict to days where both MAs are non-NaN. Without this,
    # the first MA_CROSS_SLOW-1 indices are NaN and "diff" comparisons
    # would be undefined.
    valid_mask = diff.notna()
    if not valid_mask.any():
        return empty

    valid_diff = diff[valid_mask]
    if len(valid_diff) < 2:
        return empty

    # Slice to the lookback window (last N valid trading days).
    lookback_diff = valid_diff.iloc[-MA_CROSS_LOOKBACK_DAYS - 1:]  # +1 to include "yesterday" of first window day
    if len(lookback_diff) < 2:
        return empty

    current_price = float(closes.iloc[-1])
    ma_fast_now = float(ma_fast.iloc[-1]) if not pd.isna(ma_fast.iloc[-1]) else None
    ma_slow_now = float(ma_slow.iloc[-1]) if not pd.isna(ma_slow.iloc[-1]) else None

    # Find sign changes of (ma_fast - ma_slow) in the window.
    crosses: list[tuple[pd.Timestamp, str]] = []  # (date, "bullish"|"bearish")
    prev = lookback_diff.iloc[0]
    for i in range(1, len(lookback_diff)):
        cur = lookback_diff.iloc[i]
        if prev <= 0 < cur:
            crosses.append((lookback_diff.index[i], "bullish"))
        elif prev >= 0 > cur:
            crosses.append((lookback_diff.index[i], "bearish"))
        prev = cur

    if not crosses:
        return {
            **empty,
            "current_price": current_price,
            "ma_fast_now": ma_fast_now,
            "ma_slow_now": ma_slow_now,
            "reason": "no_cross",
        }

    # Whipsaw: ≥2 crosses of different directions in the window → no clear trend
    if len(crosses) >= 2 and len({c[1] for c in crosses}) > 1:
        return {
            **empty,
            "current_price": current_price,
            "ma_fast_now": ma_fast_now,
            "ma_slow_now": ma_slow_now,
            "whipsaw": True,
            "reason": "whipsaw",
        }

    # Single cross (or multiple of same direction — take the most recent).
    cross_ts, cross_type = crosses[-1]
    cross_price = float(closes.loc[cross_ts])
    pct_since_cross = (current_price - cross_price) / cross_price if cross_price else 0.0

    # Failed-cross filter: price moved against the direction by more than threshold
    if cross_type == "bullish" and pct_since_cross < -MA_CROSS_FAILED_PCT:
        return {
            **empty,
            "type": "bullish",
            "cross_date": cross_ts.strftime("%Y-%m-%d"),
            "cross_price": round(cross_price, 2),
            "current_price": current_price,
            "pct_since_cross": round(pct_since_cross * 100, 2),
            "ma_fast_now": ma_fast_now,
            "ma_slow_now": ma_slow_now,
            "reason": "failed_cross",
        }
    if cross_type == "bearish" and pct_since_cross > MA_CROSS_FAILED_PCT:
        return {
            **empty,
            "type": "bearish",
            "cross_date": cross_ts.strftime("%Y-%m-%d"),
            "cross_price": round(cross_price, 2),
            "current_price": current_price,
            "pct_since_cross": round(pct_since_cross * 100, 2),
            "ma_fast_now": ma_fast_now,
            "ma_slow_now": ma_slow_now,
            "reason": "failed_cross",
        }

    return {
        "detected": True,
        "type": cross_type,
        "cross_date": cross_ts.strftime("%Y-%m-%d"),
        "cross_price": round(cross_price, 2),
        "current_price": current_price,
        "pct_since_cross": round(pct_since_cross * 100, 2),
        "whipsaw": False,
        "reason": None,
        "ma_fast_now": ma_fast_now,
        "ma_slow_now": ma_slow_now,
    }


def _compute_atr(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series:
    """Compute the Average True Range as a rolling mean of the True Range.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    Returns a Series aligned to closes. NaN for the first ``period`` rows.
    """
    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _greedy_modal_cluster(
    points: list[tuple[str, float]],
    tolerance: float,
) -> list[list[tuple[str, float]]]:
    """1D greedy clustering on price.

    Sort points by price. Walk through them: a point joins the current
    cluster if its relative distance to the running median is ≤ tolerance,
    otherwise it starts a new cluster. Returns list of clusters
    (each a list of (date_str, price)).
    """
    if not points:
        return []
    sorted_pts = sorted(points, key=lambda p: p[1])
    clusters: list[list[tuple[str, float]]] = [[sorted_pts[0]]]
    for date_str, price in sorted_pts[1:]:
        cur_median = float(np.median([p for _, p in clusters[-1]]))
        if cur_median > 0 and abs(price - cur_median) / cur_median <= tolerance:
            clusters[-1].append((date_str, price))
        else:
            clusters.append([(date_str, price)])
    return clusters


def _pick_dominant_cluster(
    clusters: list[list[tuple[str, float]]],
) -> list[tuple[str, float]] | None:
    """Choose the cluster with most members. Tie-break: chronologically
    most recent last touch (frischere Resistance/Support ist relevanter
    als eine alte gleich starke)."""
    if not clusters:
        return None
    return max(
        clusters,
        key=lambda c: (len(c), max(d for d, _ in c)),
    )


def _wyckoff_empty(reason: str) -> dict:
    """Return a wyckoff sub-dict shaped like the success-case but empty.

    Keeps the public schema stable for frontend consumers regardless of
    whether volumes were available, the range was too short, or the
    pattern was not detected at all.
    """
    return {
        "score": None,
        "label": None,
        "volume_slope_pct_per_day": None,
        "spring_detected": None,
        "spring_date": None,
        "spring_volume_ratio": None,
        "reason": reason,
    }


def _assess_wyckoff_volume(
    volumes: pd.Series,
    first_touch_date: pd.Timestamp,
    last_touch_date: pd.Timestamp,
    support_level: float,
    lows: pd.Series,
) -> dict:
    """Assess Wyckoff-Volumen-Profil over a confirmed Heartbeat range.

    Pure helper — no I/O, no caching. Computes a 3-tier quality-score
    (-1/0/+1) on the log-volume slope across the range, plus a separate
    Spring-Marker bonus when the highest-volume day penetrates support
    by at most ``HEARTBEAT_WYCKOFF_SPRING_PENETRATION_FLOOR_PCT``.

    Returns the wyckoff sub-dict described in the v0.29.1 spec. Never
    raises — degenerate inputs map to ``score=None`` with a reason.
    """
    from services.analysis_config import (
        HEARTBEAT_WYCKOFF_MIN_RANGE_VOLUME_DAYS,
        HEARTBEAT_WYCKOFF_SPRING_PENETRATION_FLOOR_PCT,
        HEARTBEAT_WYCKOFF_VOLUME_SLOPE_RISING_PCT,
        HEARTBEAT_WYCKOFF_VOLUME_SLOPE_SHRINKING_PCT,
    )

    if volumes is None or len(volumes) == 0:
        return _wyckoff_empty("no_volume_data")

    try:
        range_vol = volumes.loc[first_touch_date:last_touch_date].dropna()
    except Exception as e:  # noqa: BLE001 - defensive: idx mismatches must not crash
        logger.debug(f"Wyckoff range slice failed: {e}")
        return _wyckoff_empty("no_volume_data")

    range_vol = range_vol[range_vol > 0]  # drop halt-days where volume == 0
    if len(range_vol) < HEARTBEAT_WYCKOFF_MIN_RANGE_VOLUME_DAYS:
        return _wyckoff_empty("range_too_short_for_slope")

    # 1. Linear regression slope on log(volumes), normalised to median.
    log_vol = np.log(range_vol.values.astype(float))
    x = np.arange(len(log_vol), dtype=float)
    try:
        slope, _intercept = np.polyfit(x, log_vol, 1)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Wyckoff slope fit failed: {e}")
        return _wyckoff_empty("slope_fit_failed")

    median_vol = float(np.median(range_vol.values))
    if median_vol > 1.0 and np.log(median_vol) != 0.0:
        slope_pct_per_day = float((slope / np.log(median_vol)) * 100.0)
    else:
        slope_pct_per_day = 0.0

    # 2. Spring-Marker: highest-volume day penetrates support but stays
    #    within the floor (max 2% below support by default).
    spring_detected = False
    spring_date: str | None = None
    spring_volume_ratio: float | None = None
    try:
        vol_max_idx = range_vol.idxmax()
        spring_vol = float(range_vol.loc[vol_max_idx])
        range_lows = lows.loc[first_touch_date:last_touch_date].dropna()
        if vol_max_idx in range_lows.index:
            low_at_vol_max = float(range_lows.loc[vol_max_idx])
            floor_level = support_level * (1.0 - HEARTBEAT_WYCKOFF_SPRING_PENETRATION_FLOOR_PCT)
            if low_at_vol_max <= support_level and low_at_vol_max >= floor_level:
                spring_detected = True
                spring_date = pd.Timestamp(vol_max_idx).strftime("%Y-%m-%d")
                if median_vol > 0:
                    spring_volume_ratio = round(spring_vol / median_vol, 2)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Wyckoff spring detection failed: {e}")
        spring_detected = False

    # 3. Score: volume-trend alone decides. Spring is a separate bonus
    #    that only upgrades the LABEL, never the score (see plan).
    if slope_pct_per_day >= HEARTBEAT_WYCKOFF_VOLUME_SLOPE_RISING_PCT:
        score = -1
        label = "atypisch"  # Spring im Distributions-Kontext irrelevant
    elif slope_pct_per_day <= HEARTBEAT_WYCKOFF_VOLUME_SLOPE_SHRINKING_PCT:
        score = 1
        label = "bestätigt mit Spring" if spring_detected else "bestätigt"
    else:
        score = 0
        label = "neutral, Spring erkannt" if spring_detected else "neutral"

    return {
        "score": score,
        "label": label,
        "volume_slope_pct_per_day": round(slope_pct_per_day, 3),
        "spring_detected": spring_detected,
        "spring_date": spring_date,
        "spring_volume_ratio": spring_volume_ratio,
        "reason": None,
    }


def detect_heartbeat_pattern(
    closes: pd.Series,
    highs: pd.Series | None = None,
    lows: pd.Series | None = None,
    volumes: pd.Series | None = None,
) -> dict:
    """Detect a horizontal range pattern (Felix Prinz "Heartbeat").

    Phase 1 with ATR-Compression filter (percentile-based, not
    differenz-based — see analysis_config). Phase 2 (v0.29.1) adds an
    additive Wyckoff-Volumen-Profil sub-dict when ``volumes`` is
    provided — purely informational, never invalidates the pattern.

    Args:
        closes: Daily close series (DatetimeIndex).
        highs/lows: Daily high/low series for ATR. If None, ATR-filter
            is skipped and ``reason="no_ohlc_for_atr"`` returned when
            the result is otherwise undecided — never crash.
        volumes: Daily volume series. If None, the wyckoff sub-dict is
            populated with ``score=None`` and ``reason="no_volume_data"``.
    """
    from services.analysis_config import (
        HEARTBEAT_ATR_HISTORY_DAYS,
        HEARTBEAT_ATR_PERCENTILE,
        HEARTBEAT_ATR_PERIOD,
        HEARTBEAT_LOOKBACK_DAYS,
        HEARTBEAT_MIN_DURATION_DAYS,
        HEARTBEAT_MIN_RANGE_PCT,
        HEARTBEAT_RANGE_TOLERANCE,
        HEARTBEAT_SWING_LOOKBACK,
    )

    base = {
        "detected": False,
        "resistance_level": None,
        "support_level": None,
        "range_pct": None,
        "touches": [],
        "duration_days": None,
        "current_price": None,
        "position_in_range": None,
        "atr_compression_ratio": None,
        "reason": None,
    }

    if closes is None or len(closes) < 60:
        return {**base, "reason": "insufficient_history"}

    closes = closes.dropna()
    current_price = float(closes.iloc[-1])
    base["current_price"] = current_price

    # 1. ATR-Compression filter (cheap; do it first so we exit early)
    atr_compression_ratio = None
    if highs is not None and lows is not None:
        try:
            atr_series = _compute_atr(highs, lows, closes, period=HEARTBEAT_ATR_PERIOD).dropna()
            if len(atr_series) >= HEARTBEAT_ATR_HISTORY_DAYS:
                atr_history = atr_series.iloc[-HEARTBEAT_ATR_HISTORY_DAYS:]
                threshold = float(np.percentile(atr_history.values, HEARTBEAT_ATR_PERCENTILE))
                atr_now = float(atr_series.iloc[-1])
                atr_compression_ratio = round(atr_now / threshold, 3) if threshold > 0 else None
                base["atr_compression_ratio"] = atr_compression_ratio
                if atr_now > threshold:
                    return {**base, "reason": "no_compression"}
            else:
                # Not enough history for percentile — be permissive but flag
                base["atr_compression_ratio"] = None
        except Exception as e:
            logger.debug(f"ATR compression check failed: {e}")
            base["atr_compression_ratio"] = None
    else:
        # No OHLC available → skip ATR filter (caller may not have it,
        # e.g. when only closes are passed). Mark in reason if we end
        # up not detecting anything for transparency.
        pass

    # 2. Trim to lookback window for swing-detection
    window = closes.iloc[-HEARTBEAT_LOOKBACK_DAYS:] if len(closes) > HEARTBEAT_LOOKBACK_DAYS else closes
    swing_highs = _find_swing_highs(window, lookback=HEARTBEAT_SWING_LOOKBACK)
    swing_lows = _find_swing_lows(window, lookback=HEARTBEAT_SWING_LOOKBACK)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {**base, "reason": "too_few_swings"}

    # 3. Modal-cluster the highs and lows independently
    high_clusters = _greedy_modal_cluster(swing_highs, HEARTBEAT_RANGE_TOLERANCE)
    low_clusters = _greedy_modal_cluster(swing_lows, HEARTBEAT_RANGE_TOLERANCE)

    resistance_cluster = _pick_dominant_cluster(high_clusters)
    support_cluster = _pick_dominant_cluster(low_clusters)
    if resistance_cluster is None or support_cluster is None:
        return {**base, "reason": "no_cluster"}

    n_high = len(resistance_cluster)
    n_low = len(support_cluster)

    # 4. Touch-count requirement: 3+2 or 2+3
    if not ((n_high >= 3 and n_low >= 2) or (n_high >= 2 and n_low >= 3)):
        return {**base, "reason": "insufficient_touches"}

    resistance_level = float(np.median([p for _, p in resistance_cluster]))
    support_level = float(np.median([p for _, p in support_cluster]))

    # 5. Range-width check
    if support_level <= 0:
        return {**base, "reason": "invalid_support"}
    range_pct = (resistance_level - support_level) / support_level
    if range_pct < HEARTBEAT_MIN_RANGE_PCT:
        return {**base, "reason": "range_too_narrow", "range_pct": round(range_pct, 4)}

    # 6. Build chronological touch list and validate duration + alternation
    touches: list[dict] = []
    for d, p in resistance_cluster:
        touches.append({"date": d, "price": round(p, 2), "type": "high"})
    for d, p in support_cluster:
        touches.append({"date": d, "price": round(p, 2), "type": "low"})
    touches.sort(key=lambda t: t["date"])

    first_date = pd.Timestamp(touches[0]["date"])
    last_date = pd.Timestamp(touches[-1]["date"])
    duration_days = (last_date - first_date).days
    if duration_days < HEARTBEAT_MIN_DURATION_DAYS:
        return {**base, "reason": "duration_too_short", "duration_days": duration_days}

    # Alternation: between any two same-type touches, at least one
    # opposite touch must lie. Collapse to the type-sequence and
    # require that no type appears more than twice in a row.
    type_seq = [t["type"] for t in touches]
    streak = 1
    for i in range(1, len(type_seq)):
        if type_seq[i] == type_seq[i - 1]:
            streak += 1
            if streak > 2:  # 3 same-type touches in a row → no oscillation
                return {**base, "reason": "no_alternation", "duration_days": duration_days, "range_pct": round(range_pct, 4)}
        else:
            streak = 1

    # 7. Position in range
    if current_price >= resistance_level * (1 - HEARTBEAT_RANGE_TOLERANCE):
        position = "near_resistance"
    elif current_price <= support_level * (1 + HEARTBEAT_RANGE_TOLERANCE):
        position = "near_support"
    else:
        position = "middle"

    # 8. Wyckoff-Volumen-Profil (additive Phase-2-Erweiterung).
    #    Falls keine Volumen-Reihe oder zu kurz → score=None, Pattern bleibt
    #    valide. Spring/Slope nutzen die Range-Grenzen (first/last touch).
    if volumes is not None and lows is not None:
        first_touch_date = pd.Timestamp(touches[0]["date"])
        last_touch_date = pd.Timestamp(touches[-1]["date"])
        wyckoff = _assess_wyckoff_volume(
            volumes=volumes,
            first_touch_date=first_touch_date,
            last_touch_date=last_touch_date,
            support_level=support_level,
            lows=lows,
        )
    else:
        wyckoff = _wyckoff_empty("no_volume_data")

    return {
        "detected": True,
        "resistance_level": round(resistance_level, 2),
        "support_level": round(support_level, 2),
        "range_pct": round(range_pct * 100, 2),
        "touches": touches,
        "duration_days": duration_days,
        "current_price": current_price,
        "position_in_range": position,
        "atr_compression_ratio": atr_compression_ratio,
        "reason": None,
        "wyckoff": wyckoff,
    }


def get_heartbeat_pattern(ticker: str) -> dict:
    """Service-wrapper for ``detect_heartbeat_pattern`` with 24h cache.

    Heartbeat-Patterns ändern sich über Tage, nicht Stunden — Intraday-
    Detection wäre eh unsauber (man prüft am Tagesschluss). 24h-TTL
    spart Rechenzeit ohne Frische-Verlust.
    """
    # v2 cache-key bump for the additive `wyckoff` sub-dict (v0.29.1).
    # Old v1 entries cannot be returned — they would crash optional-
    # chaining-less consumers and cause cross-ticker UI inconsistency.
    cache_key = f"heartbeat:v2:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        # Pull full OHLC for ATR. yf_download returns a DataFrame with
        # Close/High/Low/Volume columns when given a single ticker.
        data = yf_download(ticker, period="1y", progress=False)
        if data is None or data.empty:
            result = {"detected": False, "reason": "no_data"}
        else:
            close = data["Close"].squeeze().dropna() if "Close" in data else None
            high = data["High"].squeeze().dropna() if "High" in data else None
            low = data["Low"].squeeze().dropna() if "Low" in data else None
            volume = data["Volume"].squeeze().dropna() if "Volume" in data else None
            if close is None or len(close) < 60:
                result = {"detected": False, "reason": "insufficient_history"}
            else:
                result = detect_heartbeat_pattern(close, high, low, volumes=volume)
                result["ticker"] = ticker

        cache.set(cache_key, result, ttl=86400)  # 24h
        return result
    except Exception as e:
        logger.warning(f"Heartbeat detection failed for {ticker}: {e}")
        return {"detected": False, "reason": "error"}


# --- v0.30 Long-Accumulation-Detector ------------------------------------

def _percentile_rank_mean(history: np.ndarray, score: float) -> float:
    """Numpy-only Aequivalent zu scipy.stats.percentileofscore (kind='mean').

    Gibt den Prozentsatz der Werte in ``history`` zurueck, die kleiner oder
    gleich ``score`` sind, mit der "mean"-Konvention: Mittel aus strict-less
    und less-or-equal. Entspricht 1:1 dem Helper in
    ``scripts/wyckoff_textbook_check.py`` — bewusst dupliziert statt
    importiert (keine Abhaengigkeit Service -> Script).
    """
    if history.size == 0:
        return float("nan")
    strict = float(np.sum(history < score)) / history.size
    weak = float(np.sum(history <= score)) / history.size
    return ((strict + weak) / 2.0) * 100.0


def detect_long_accumulation_pattern(
    closes: pd.Series,
    highs: pd.Series | None = None,
    lows: pd.Series | None = None,
    volumes: pd.Series | None = None,
) -> dict:
    """Detect a long-accumulation horizontal range (v0.30 variant of Heartbeat).

    FORSCHUNGS-CODE v0.30 — NICHT PRODUKTIV.

    Held-Out-Validation (LONG_ACCUMULATION_HELD_OUT_RESULTS.md, 2026-05-02):
    Recall 0/3 ("Reichweite zu eng"), Precision 1/9 ("Precision-validiert").
    Bail-out aktiviert: Heartbeat-Geometrie (Touch-Cluster + ATR-Compression)
    ist strukturell nicht das richtige Pattern-Modell für Long-Accumulations.

    Code bleibt als Baseline für v0.31.x mit anderem Methoden-Approach (z.B.
    Linear-Regression-Slope auf Closes statt Touch-Cluster, Bollinger-Width-
    Squeeze als Compression-Mass, Pre-Range-Direction als Precision-Co-Filter).

    Pflichtlektüre vor v0.31.x: LONG_ACCUMULATION_HELD_OUT_RESULTS.md plus
    Step-1b Pin-Sweep-Sektion in WYCKOFF_TEXTBOOK_RESULTS.md.

    Eigenständige Variante mit gelockerten Schwellen für langwierige
    Akkumulationen (Lookback 180d statt 120d, Min-Duration 60d statt 30d,
    Min-Range 5% statt 3%, Touches 3+3 symmetrisch). Wyckoff-Sub-Layer
    wird unverändert wiederverwendet.

    Methodischer Unterschied zu ``detect_heartbeat_pattern``: ATR-
    Compression-Filter nutzt **Rolling-Median-Percentile-Rank** über das
    ``LONG_ACCUMULATION_ATR_RANK_WINDOW`` (= MIN_DURATION_DAYS) statt
    Spot-ATR am letzten Tag. Begründung Phase 1.5: Spot-ATR-Window-End-
    Bias verwarf Akku-Cases kurz vor Breakout (AMD/NVDA bei Percentile
    99/83). Median über das Range-Fenster ist robust gegen Edge-Spikes.
    """
    from services.analysis_config import (
        LONG_ACCUMULATION_ATR_HISTORY_DAYS,
        LONG_ACCUMULATION_ATR_PERCENTILE,
        LONG_ACCUMULATION_ATR_PERIOD,
        LONG_ACCUMULATION_ATR_RANK_WINDOW,
        LONG_ACCUMULATION_LOOKBACK_DAYS,
        LONG_ACCUMULATION_MIN_DURATION_DAYS,
        LONG_ACCUMULATION_MIN_HIGH_TOUCHES,
        LONG_ACCUMULATION_MIN_LOW_TOUCHES,
        LONG_ACCUMULATION_MIN_RANGE_PCT,
        LONG_ACCUMULATION_RANGE_TOLERANCE,
        LONG_ACCUMULATION_SWING_LOOKBACK,
    )

    # Schwellen-Snapshot für das spätere Logging (Phase 4) und als
    # transparenter Output an die Frontend-Seite. 1:1 in parameters_json.
    parameters_snapshot = {
        "atr_percentile_threshold": LONG_ACCUMULATION_ATR_PERCENTILE,
        "min_duration_days": LONG_ACCUMULATION_MIN_DURATION_DAYS,
        "lookback_days": LONG_ACCUMULATION_LOOKBACK_DAYS,
        "min_high_touches": LONG_ACCUMULATION_MIN_HIGH_TOUCHES,
        "min_low_touches": LONG_ACCUMULATION_MIN_LOW_TOUCHES,
        "min_range_pct": LONG_ACCUMULATION_MIN_RANGE_PCT,
        "range_tolerance": LONG_ACCUMULATION_RANGE_TOLERANCE,
        "atr_rank_window": LONG_ACCUMULATION_ATR_RANK_WINDOW,
    }

    base = {
        "detected": False,
        "detector_variant": "long_accumulation",
        "resistance_level": None,
        "support_level": None,
        "range_pct": None,
        "touches": [],
        "duration_days": None,
        "current_price": None,
        "position_in_range": None,
        "atr_compression_ratio": None,
        "atr_compression_metric": None,
        "parameters": parameters_snapshot,
        "reason": None,
    }

    if closes is None or len(closes) < 60:
        return {**base, "reason": "insufficient_history"}

    closes = closes.dropna()
    current_price = float(closes.iloc[-1])
    base["current_price"] = current_price

    # 1. ATR-Compression-Filter via Rolling-Median-Percentile-Rank.
    #    Pro Tag im RANK_WINDOW: percentileofscore(history, atr_t) berechnen,
    #    dann Median über diese Ranks. Wenn Median über Schwelle: kein
    #    Compression-Match.
    atr_compression_metric: float | None = None
    atr_compression_ratio: float | None = None
    if highs is not None and lows is not None:
        try:
            atr_series = _compute_atr(
                highs, lows, closes, period=LONG_ACCUMULATION_ATR_PERIOD,
            ).dropna()
            if (
                len(atr_series) >= LONG_ACCUMULATION_ATR_HISTORY_DAYS
                and len(atr_series) >= LONG_ACCUMULATION_ATR_RANK_WINDOW
            ):
                atr_history = atr_series.iloc[-LONG_ACCUMULATION_ATR_HISTORY_DAYS:]
                threshold = float(np.percentile(
                    atr_history.values, LONG_ACCUMULATION_ATR_PERCENTILE,
                ))
                atr_recent_window = atr_series.iloc[-LONG_ACCUMULATION_ATR_RANK_WINDOW:]
                ranks = [
                    _percentile_rank_mean(atr_history.values, float(x))
                    for x in atr_recent_window.values
                ]
                median_rank = float(np.median(ranks))
                atr_compression_metric = round(median_rank, 2)
                # Ratio-Pendant: Verhältnis median_rank / Schwelle. <1.0 heisst
                # "Median liegt unter der Schwelle" (komprimiert), >1.0 nicht.
                # Im selben Sinn-Vorzeichen wie Heartbeats atr_now/threshold.
                if LONG_ACCUMULATION_ATR_PERCENTILE > 0:
                    atr_compression_ratio = round(
                        median_rank / float(LONG_ACCUMULATION_ATR_PERCENTILE), 3,
                    )
                base["atr_compression_metric"] = atr_compression_metric
                base["atr_compression_ratio"] = atr_compression_ratio
                if median_rank > LONG_ACCUMULATION_ATR_PERCENTILE:
                    return {**base, "reason": "no_compression"}
            else:
                # ATR-History oder RANK_WINDOW zu kurz — permissiv weiter,
                # Reason wird unten gesetzt falls die Geometrie auch nicht
                # erkennt. Kein hard-fail wegen kurzer History.
                pass
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Long-accumulation ATR compression check failed: {e}")
            base["atr_compression_metric"] = None
            base["atr_compression_ratio"] = None
    # Falls keine OHLC-Daten: ATR-Filter wird übersprungen (analog Heartbeat).

    # 2. Trim auf Long-Acc-Lookback (180d) für Swing-Detection.
    window = (
        closes.iloc[-LONG_ACCUMULATION_LOOKBACK_DAYS:]
        if len(closes) > LONG_ACCUMULATION_LOOKBACK_DAYS
        else closes
    )
    swing_highs = _find_swing_highs(window, lookback=LONG_ACCUMULATION_SWING_LOOKBACK)
    swing_lows = _find_swing_lows(window, lookback=LONG_ACCUMULATION_SWING_LOOKBACK)

    if (
        len(swing_highs) < LONG_ACCUMULATION_MIN_HIGH_TOUCHES
        or len(swing_lows) < LONG_ACCUMULATION_MIN_LOW_TOUCHES
    ):
        return {**base, "reason": "too_few_swings"}

    # 3. Modal-cluster (gleiche Helper wie Heartbeat).
    high_clusters = _greedy_modal_cluster(swing_highs, LONG_ACCUMULATION_RANGE_TOLERANCE)
    low_clusters = _greedy_modal_cluster(swing_lows, LONG_ACCUMULATION_RANGE_TOLERANCE)

    resistance_cluster = _pick_dominant_cluster(high_clusters)
    support_cluster = _pick_dominant_cluster(low_clusters)
    if resistance_cluster is None or support_cluster is None:
        return {**base, "reason": "no_cluster"}

    n_high = len(resistance_cluster)
    n_low = len(support_cluster)

    # 4. Touch-Count: 3+3 symmetrisch (gegen 3+2/2+3 des Heartbeats).
    if not (
        n_high >= LONG_ACCUMULATION_MIN_HIGH_TOUCHES
        and n_low >= LONG_ACCUMULATION_MIN_LOW_TOUCHES
    ):
        return {**base, "reason": "insufficient_touches"}

    resistance_level = float(np.median([p for _, p in resistance_cluster]))
    support_level = float(np.median([p for _, p in support_cluster]))

    # 5. Range-Width-Check (≥5%).
    if support_level <= 0:
        return {**base, "reason": "invalid_support"}
    range_pct = (resistance_level - support_level) / support_level
    if range_pct < LONG_ACCUMULATION_MIN_RANGE_PCT:
        return {**base, "reason": "range_too_narrow", "range_pct": round(range_pct, 4)}

    # 6. Chronologische Touch-Liste + Duration + Alternation.
    touches: list[dict] = []
    for d, p in resistance_cluster:
        touches.append({"date": d, "price": round(p, 2), "type": "high"})
    for d, p in support_cluster:
        touches.append({"date": d, "price": round(p, 2), "type": "low"})
    touches.sort(key=lambda t: t["date"])

    first_date = pd.Timestamp(touches[0]["date"])
    last_date = pd.Timestamp(touches[-1]["date"])
    duration_days = (last_date - first_date).days
    if duration_days < LONG_ACCUMULATION_MIN_DURATION_DAYS:
        return {**base, "reason": "duration_too_short", "duration_days": duration_days}

    # Alternations-Check: keine drei gleichartigen Touches in Folge.
    type_seq = [t["type"] for t in touches]
    streak = 1
    for i in range(1, len(type_seq)):
        if type_seq[i] == type_seq[i - 1]:
            streak += 1
            if streak > 2:
                return {
                    **base,
                    "reason": "no_alternation",
                    "duration_days": duration_days,
                    "range_pct": round(range_pct, 4),
                }
        else:
            streak = 1

    # 7. Position in Range.
    if current_price >= resistance_level * (1 - LONG_ACCUMULATION_RANGE_TOLERANCE):
        position = "near_resistance"
    elif current_price <= support_level * (1 + LONG_ACCUMULATION_RANGE_TOLERANCE):
        position = "near_support"
    else:
        position = "middle"

    # 8. Wyckoff-Sub-Layer (1:1 wiederverwendet — geometrieagnostisch).
    if volumes is not None and lows is not None:
        first_touch_date = pd.Timestamp(touches[0]["date"])
        last_touch_date = pd.Timestamp(touches[-1]["date"])
        wyckoff = _assess_wyckoff_volume(
            volumes=volumes,
            first_touch_date=first_touch_date,
            last_touch_date=last_touch_date,
            support_level=support_level,
            lows=lows,
        )
    else:
        wyckoff = _wyckoff_empty("no_volume_data")

    return {
        "detected": True,
        "detector_variant": "long_accumulation",
        "resistance_level": round(resistance_level, 2),
        "support_level": round(support_level, 2),
        "range_pct": round(range_pct * 100, 2),
        "touches": touches,
        "duration_days": duration_days,
        "current_price": current_price,
        "position_in_range": position,
        "atr_compression_ratio": atr_compression_ratio,
        "atr_compression_metric": atr_compression_metric,
        "wyckoff": wyckoff,
        "parameters": parameters_snapshot,
        "reason": None,
    }


def detect_distribution_day(
    closes: pd.Series,
    volumes: pd.Series,
    opens: pd.Series,
) -> dict:
    """Detect a "distribution day" in the recent lookback window.

    Pattern: a single trading day with ``volume > N × avg(volume_20d)``
    AND ``close < open`` (heavy selling pressure on a down day). Used
    as a Risiken-criterion in the score pipeline.

    Returns the most recent qualifying day if any, otherwise
    ``detected=False`` with a reason.
    """
    from services.analysis_config import (
        VOLUME_SPIKE_AVG_WINDOW,
        VOLUME_SPIKE_LOOKBACK_DAYS,
        VOLUME_SPIKE_MULTIPLIER,
    )

    base = {
        "detected": False,
        "spike_date": None,
        "spike_volume": None,
        "avg_volume": None,
        "volume_ratio": None,
        "open": None,
        "close": None,
        "reason": None,
    }

    if closes is None or volumes is None or opens is None:
        return {**base, "reason": "no_data"}

    # Align series on common index to avoid lookup mismatches
    df = pd.DataFrame({"close": closes, "open": opens, "volume": volumes}).dropna()
    if len(df) < VOLUME_SPIKE_AVG_WINDOW + 5:
        return {**base, "reason": "insufficient_history"}

    avg_vol = df["volume"].rolling(VOLUME_SPIKE_AVG_WINDOW).mean()

    # Walk the last LOOKBACK days backwards, return the most recent
    # qualifying day so the user sees the freshest distribution event.
    lookback_slice = df.iloc[-VOLUME_SPIKE_LOOKBACK_DAYS:]
    avg_slice = avg_vol.iloc[-VOLUME_SPIKE_LOOKBACK_DAYS:]

    for ts in lookback_slice.index[::-1]:
        avg_v = avg_slice.loc[ts]
        if pd.isna(avg_v) or avg_v <= 0:
            continue
        v = float(lookback_slice.loc[ts, "volume"])
        c = float(lookback_slice.loc[ts, "close"])
        o = float(lookback_slice.loc[ts, "open"])
        ratio = v / avg_v
        if ratio >= VOLUME_SPIKE_MULTIPLIER and c < o:
            return {
                "detected": True,
                "spike_date": ts.strftime("%Y-%m-%d"),
                "spike_volume": int(v),
                "avg_volume": int(avg_v),
                "volume_ratio": round(ratio, 2),
                "open": round(o, 2),
                "close": round(c, 2),
                "reason": None,
            }

    return {**base, "reason": "no_spike_in_window"}
