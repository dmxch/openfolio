import logging

import pandas as pd
import yfinance as yf
from yf_patch import yf_download
from services import cache

logger = logging.getLogger(__name__)


def _compute_mrs_from_close(stock_close: pd.Series, bench_close: pd.Series, period: int = 13) -> float | None:
    """Compute Mansfield RS from pre-downloaded close series (same algo as utils.py)."""
    try:
        stock_weekly = stock_close.resample("W-FRI").last().dropna()
        bench_weekly = bench_close.resample("W-FRI").last().dropna()

        common_idx = stock_weekly.index.intersection(bench_weekly.index)
        if len(common_idx) < period + 1:
            return None

        stock_weekly = stock_weekly.loc[common_idx]
        bench_weekly = bench_weekly.loc[common_idx]

        rs = stock_weekly / bench_weekly
        rs_ma = rs.ewm(span=period, adjust=False).mean()

        if rs_ma.iloc[-1] == 0 or pd.isna(rs_ma.iloc[-1]):
            return None

        mansfield = ((rs.iloc[-1] / rs_ma.iloc[-1]) - 1) * 100
        return round(float(mansfield), 2)
    except Exception as e:
        logger.debug(f"MRS computation failed: {e}")
        return None


def _download_and_analyze(ticker: str) -> dict:
    """Single 2y download, derive MAs, 52w range, MA200 trend, volume data, and MRS."""
    cache_key = f"scorer_data:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        # Download stock and benchmark in one batch to avoid separate calls
        tickers_to_fetch = f"{ticker} ^GSPC"
        hist_all = yf_download(tickers_to_fetch, period="2y", progress=False, group_by="ticker")
        if hist_all.empty:
            return {}

        # Extract stock data
        try:
            close = hist_all[ticker]["Close"].squeeze().dropna()
            volume = hist_all[ticker]["Volume"].squeeze().dropna()
            high_series = hist_all[ticker]["High"].squeeze().dropna()
        except (KeyError, IndexError) as e:
            logger.debug(f"Could not extract price data for {ticker}: {e}")
            return {}

        if close.empty:
            return {}
        current = float(close.iloc[-1])

        # Moving averages
        mas = {"current": current}
        for p in [50, 100, 150, 200]:
            mas[f"ma{p}"] = float(close.rolling(p).mean().iloc[-1]) if len(close) >= p else None

        # 52w range (last ~252 trading days)
        close_1y = close.iloc[-252:] if len(close) > 252 else close
        high_1y = high_series.iloc[-252:] if len(high_series) > 252 else high_series
        high = float(high_1y.max())
        low = float(close_1y.min())
        pct_from_high = round(((current - high) / high) * 100, 2) if high else None
        range_data = {"high_52w": round(high, 2), "low_52w": round(low, 2), "pct_from_high": pct_from_high}

        # MA200 rising
        ma200_series = close.rolling(200).mean()
        ma200_rising = bool(ma200_series.iloc[-1] > ma200_series.iloc[-20]) if len(ma200_series) > 20 else None
        ma200_1m_ago = float(ma200_series.iloc[-22]) if len(ma200_series) > 22 else None

        # Volume data for breakout trigger
        current_volume = int(volume.iloc[-1]) if len(volume) > 0 else 0
        avg_volume_50 = int(volume.rolling(50).mean().iloc[-1]) if len(volume) >= 50 else 0
        avg_volume_20 = int(volume.rolling(20).mean().iloc[-1]) if len(volume) >= 20 else avg_volume_50

        # Donchian Channel Breakout (20-day lookback)
        donchian = {"breakout": False, "breakdown": False, "channel_high": None, "channel_low": None,
                     "last_breakout_date": None, "last_breakout_price": None}
        try:
            low_series = hist_all[ticker]["Low"].squeeze().dropna()
        except (KeyError, IndexError) as e:
            logger.debug(f"Could not extract Low series for {ticker}, using Close: {e}")
            low_series = close

        if len(high_series) >= 21 and len(low_series) >= 21:
            ch_high = float(high_series.iloc[-21:-1].max())  # Highest high of last 20 days (excl today)
            ch_low = float(low_series.iloc[-21:-1].min())    # Lowest low of last 20 days (excl today)
            donchian["channel_high"] = round(ch_high, 2)
            donchian["channel_low"] = round(ch_low, 2)
            donchian["breakout"] = current > ch_high
            donchian["breakdown"] = current < ch_low

            # Find last breakout event (close > previous 20d high) with volume
            ch_highs = high_series.rolling(20).max().shift(1)
            avg_vol_20 = volume.rolling(20).mean()
            for j in range(len(close) - 1, max(len(close) - 252, 20), -1):
                try:
                    if float(close.iloc[j]) > float(ch_highs.iloc[j]) and float(volume.iloc[j]) >= float(avg_vol_20.iloc[j]) * 1.5:
                        donchian["last_breakout_date"] = close.index[j].strftime("%Y-%m-%d")
                        donchian["last_breakout_price"] = round(float(close.iloc[j]), 2)
                        break
                except (IndexError, ValueError) as e:
                    logger.debug(f"Donchian breakout check at index {j} failed: {e}")
                    continue

        # Mansfield RS — compute from the same batch download
        mrs = None
        try:
            bench_close = hist_all["^GSPC"]["Close"].squeeze().dropna()
            if not bench_close.empty:
                mrs = _compute_mrs_from_close(close, bench_close)
        except (KeyError, IndexError):
            logger.debug(f"Could not extract ^GSPC data for MRS computation of {ticker}")

        # Open-Series für Distribution-Day (Volume-Spike-Down).
        # Wie _close_series wird das nur in-memory zurückgegeben, nicht
        # in den Redis-Cache geschrieben (siehe Kommentar unten).
        try:
            open_series = hist_all[ticker]["Open"].squeeze().dropna()
        except (KeyError, IndexError):
            open_series = None

        result = {
            "mas": mas, "range_data": range_data, "ma200_rising": ma200_rising, "ma200_1m_ago": ma200_1m_ago,
            "current_volume": current_volume, "avg_volume_50": avg_volume_50, "avg_volume_20": avg_volume_20,
            "donchian": donchian,
            "mrs": mrs,
            # _close_series, _volume_series, _open_series, _high_series, _low_series
            # werden bewusst NICHT ins gecachte Dict aufgenommen:
            # cache.set() pruft nur Top-Level-Type (dict = "JSON-safe") und nutzt
            # json.dumps(default=str), wodurch pandas Series in Redis stillschweigend
            # zu einem String konvertiert wird. Bei Cache-Miss im Memory-Layer
            # (fremder Worker / Restart) wuerde der String in detector .iloc-Calls
            # crashen. Daher sind die Series nur zur Laufzeit im return-Value.
        }
        cache.set(cache_key, result, ttl=3600)
        result["_close_series"] = close
        result["_volume_series"] = volume
        result["_open_series"] = open_series
        result["_high_series"] = high_series
        result["_low_series"] = low_series
        return result
    except Exception as e:
        logger.warning(f"Download and analyze failed for {ticker}: {e}")
        return {}


def check_breakout_trigger(ticker: str, analysis: dict, manual_resistance: float | None = None) -> dict:
    """
    Check if a Donchian Channel breakout is present.
    A) Price breaks above 20-day Donchian Channel high (or manual resistance)
    B) Volume >= 1.5x 20-day average
    """
    mas = analysis.get("mas", {})
    donchian = analysis.get("donchian", {})
    range_data = analysis.get("range_data", {})
    current_price = mas.get("current")

    if current_price is None:
        return {"triggered": False, "reason": "Keine Daten"}

    # Resistance: manual override > Donchian channel high > 52W high
    if manual_resistance:
        resistance = manual_resistance
        resistance_source = "manual"
    elif donchian.get("channel_high"):
        resistance = donchian["channel_high"]
        resistance_source = "donchian_20d"
    else:
        resistance = range_data.get("high_52w")
        resistance_source = "52w_high"

    if not resistance:
        return {"triggered": False, "reason": "Kein Widerstandslevel"}

    # Condition A: Price must be above resistance (no tolerance)
    breakout_price = current_price > resistance
    distance_pct = round(((current_price / resistance) - 1) * 100, 2) if resistance else 0

    # Condition B: Volume >= 1.5x 20-day average
    current_volume = analysis.get("current_volume", 0)
    avg_volume_20 = analysis.get("avg_volume_20", analysis.get("avg_volume_50", 0))
    volume_ratio = round(current_volume / avg_volume_20, 2) if avg_volume_20 > 0 else 0
    volume_confirmation = current_volume >= (avg_volume_20 * 1.5) if avg_volume_20 > 0 else False

    triggered = breakout_price and volume_confirmation

    return {
        "triggered": triggered,
        "breakout_price": breakout_price,
        "volume_confirmation": volume_confirmation,
        "current_price": round(current_price, 2),
        "resistance": round(resistance, 2),
        "resistance_source": resistance_source,
        "distance_to_resistance_pct": distance_pct,
        "current_volume": current_volume,
        "avg_volume": avg_volume_20,
        "volume_ratio": volume_ratio,
        "donchian_high": donchian.get("channel_high"),
        "donchian_low": donchian.get("channel_low"),
        "last_breakout_date": donchian.get("last_breakout_date"),
        "last_breakout_price": donchian.get("last_breakout_price"),
    }


def determine_signal(setup_score: int, setup_max: int, breakout: dict) -> dict:
    """Determine trading signal from setup quality + breakout trigger."""
    pct = round(setup_score / setup_max * 100) if setup_max > 0 else 0

    if pct >= 70:
        quality = "STARK"
    elif pct >= 45:
        quality = "MODERAT"
    else:
        quality = "SCHWACH"

    if quality == "STARK" and breakout.get("triggered"):
        return {"signal": "KAUFSIGNAL", "signal_label": "Kaufkriterien erfüllt (Breakout bestätigt)", "quality": quality}
    elif quality == "STARK":
        return {"signal": "WATCHLIST", "signal_label": "Warten auf Breakout", "quality": quality}
    elif quality == "MODERAT":
        return {"signal": "BEOBACHTEN", "signal_label": "Setup noch nicht stark genug", "quality": quality}
    else:
        return {"signal": "KEIN SETUP", "signal_label": "Kriterien nicht erfüllt", "quality": quality}


def score_stock(ticker: str, manual_resistance: float | None = None) -> dict:
    """19-point buying checklist for stock analysis with breakout trigger."""
    t = yf.Ticker(ticker)

    # Single download for all price-based analysis
    analysis = _download_and_analyze(ticker)
    if not analysis or not analysis.get("mas", {}).get("current"):
        logger.warning(
            f"score_stock({ticker}): _download_and_analyze returned no usable price data "
            f"(empty={not analysis}, has_mas={bool(analysis.get('mas')) if analysis else False}). "
            f"Score will contain N/A for all MA criteria."
        )
    mas = analysis.get("mas", {})
    range_data = analysis.get("range_data", {"high_52w": None, "low_52w": None, "pct_from_high": None})
    ma200_rising = analysis.get("ma200_rising")
    ma200_1m_ago = analysis.get("ma200_1m_ago")
    mrs = analysis.get("mrs")  # Computed in _download_and_analyze from batch download

    current = mas.get("current")
    ma50 = mas.get("ma50")
    ma150 = mas.get("ma150")
    ma200 = mas.get("ma200")
    donchian = analysis.get("donchian", {})
    avg_vol_20 = analysis.get("avg_volume_20", 0)

    info_cache_key = f"info:{ticker}"
    info = cache.get(info_cache_key)
    if info is None:
        try:
            info = t.info or {}
        except Exception as e:
            logger.debug(f"Could not fetch yfinance info for {ticker}: {e}")
            info = {}
        if info:
            cache.set(info_cache_key, info, ttl=86400)  # 24h — fundamentals change at most daily

    high_52w = range_data.get("high_52w")
    low_52w = range_data.get("low_52w")
    pct_from_high = range_data.get("pct_from_high")
    pct_above_low = round(((current - low_52w) / low_52w * 100), 2) if current and low_52w and low_52w > 0 else None

    # Volume ratio for Donchian breakout
    current_vol = analysis.get("current_volume", 0)
    vol_ratio_20 = round(current_vol / avg_vol_20, 1) if avg_vol_20 > 0 else 0
    donchian_breakout = donchian.get("breakout", False)
    ch_high = donchian.get("channel_high")

    # 3-Point Reversal (only relevant when below 150-DMA)
    below_150dma = current < ma150 if current and ma150 else False
    reversal_data = {"detected": False}
    close_series = analysis.get("_close_series")
    # Defensive: nur wenn es wirklich eine pandas Series ist — ein alter
    # Cache-Eintrag koennte einen String halten (siehe Kommentar oben).
    has_close_series = isinstance(close_series, pd.Series) and len(close_series) >= 30
    if below_150dma and has_close_series:
        from services.chart_service import detect_three_point_reversal
        reversal_data = detect_three_point_reversal(close_series, window=60)

    # MA-Cross 50/150 — Bullish-Cross (Trendbestätigung) + Death-Cross (Risiken)
    ma_cross = {"detected": False, "type": None, "whipsaw": False, "reason": "no_data"}
    if has_close_series:
        from services.chart_service import detect_ma_cross_50_150
        ma_cross = detect_ma_cross_50_150(close_series)

    # Distribution Day — Risiken (volume-spike-down). Pulls OHLC from the
    # in-memory return of _download_and_analyze (no extra HTTP, no Redis
    # round-trip — pandas Series can't survive json.dumps).
    distro = {"detected": False, "reason": "no_data"}
    distro_assessable = False
    open_series = analysis.get("_open_series")
    volume_series = analysis.get("_volume_series")
    if (
        isinstance(close_series, pd.Series)
        and isinstance(open_series, pd.Series)
        and isinstance(volume_series, pd.Series)
    ):
        try:
            from services.chart_service import detect_distribution_day
            distro = detect_distribution_day(close_series, volume_series, open_series)
            distro_assessable = distro.get("reason") not in ("no_data", "insufficient_history")
        except Exception as e:
            logger.debug(f"Distribution day detection failed for {ticker}: {e}")

    # --- Tri-state derivation for new criteria ---
    # Bullish-Cross (Trendbestätigung)
    bullish_cross_passed = (
        bool(ma_cross.get("detected") and ma_cross.get("type") == "bullish")
        if has_close_series else None
    )

    # Death-Cross (Risiken) — explicit None when not assessable
    death_cross_active = bool(ma_cross.get("detected") and ma_cross.get("type") == "bearish")
    death_cross_assessable = (
        has_close_series
        and ma_cross.get("type") in ("bullish", "bearish", None)
        and not ma_cross.get("whipsaw")
        and ma_cross.get("reason") not in ("failed_cross", "whipsaw", "no_data")
    )
    if death_cross_active:
        death_cross_passed = False
    elif death_cross_assessable:
        death_cross_passed = True
    else:
        death_cross_passed = None

    # Distribution-Day (Risiken)
    if distro.get("detected"):
        distro_passed = False
    elif distro_assessable:
        distro_passed = True
    else:
        distro_passed = None

    # --- Phase A computations ---
    from datetime import date as _date

    # 2-Tages-Confirm für Donchian-Breakout (id=8 4-State)
    breakout_status = {"passed": None, "pending": False, "reason": "no_data"}
    high_series_for_confirm = analysis.get("_high_series")
    volume_series_for_confirm = analysis.get("_volume_series")
    if (
        isinstance(close_series, pd.Series)
        and isinstance(high_series_for_confirm, pd.Series)
        and isinstance(volume_series_for_confirm, pd.Series)
    ):
        try:
            from services.chart_service import check_breakout_confirmed_today
            breakout_status = check_breakout_confirmed_today(
                close_series, high_series_for_confirm, volume_series_for_confirm,
            )
        except Exception as e:
            logger.debug(f"check_breakout_confirmed_today failed for {ticker}: {e}")

    # Earnings-Proximity (id=19, Risiken)
    earnings_dt = None
    earnings_active = False
    earnings_passed = None
    days_until_earnings: int | None = None
    try:
        from services.earnings_service import get_next_earnings_date
        from services.analysis_config import EARNINGS_PROXIMITY_DAYS
        earnings_dt = get_next_earnings_date(ticker)
        if earnings_dt is not None:
            today = _date.today()
            ed = earnings_dt.date() if hasattr(earnings_dt, "date") else earnings_dt
            days_until_earnings = (ed - today).days
            if days_until_earnings < EARNINGS_PROXIMITY_DAYS:
                earnings_passed, earnings_active = False, True
            else:
                earnings_passed, earnings_active = True, False
    except Exception as e:
        logger.debug(f"earnings_service lookup failed for {ticker}: {e}")

    # Distance-from-MA50 (id=20, Modifier)
    ma50_modifier: int | None = None
    ma50_distance_pct: float | None = None
    if current and ma50 and current > ma50 and ma50 > 0:
        ma50_distance_pct = (current - ma50) / ma50
        from services.analysis_config import (
            MA50_DISTANCE_HEALTHY_PCT,
            MA50_DISTANCE_OVEREXTENDED_PCT,
        )
        if ma50_distance_pct < MA50_DISTANCE_HEALTHY_PCT:
            ma50_modifier = 1
        elif ma50_distance_pct > MA50_DISTANCE_OVEREXTENDED_PCT:
            ma50_modifier = -1
        else:
            ma50_modifier = 0
    # Wenn close ≤ ma50 → ma50_modifier = None (id=3 prüft das schon klassisch)

    # Volume-Confirmation (id=21, Modifier) — braucht 90d MCap-History
    vol_conf = {"score_modifier": None, "regime": "standard", "reason": "no_data"}
    if (
        isinstance(close_series, pd.Series)
        and isinstance(volume_series_for_confirm, pd.Series)
        and len(close_series) >= 90
    ):
        try:
            from services.chart_service import detect_volume_confirmation
            current_mcap = info.get("marketCap")
            shares_outstanding = info.get("sharesOutstanding")
            mcap_history_avg_90d = None
            if shares_outstanding and len(close_series) >= 90:
                mcap_history_avg_90d = float(close_series.iloc[-90:].mean()) * float(shares_outstanding)
            vol_conf = detect_volume_confirmation(
                close_series, volume_series_for_confirm,
                current_mcap=current_mcap,
                mcap_history_avg_90d=mcap_history_avg_90d,
            )
        except Exception as e:
            logger.debug(f"detect_volume_confirmation failed for {ticker}: {e}")

    # Industry-MRS (id=22, Industry-Stärke)
    industry_mrs = {"passed": None, "industry_name": None, "reason": "not_computed"}
    try:
        from services.chart_service import compute_industry_mrs_simple
        industry_mrs = compute_industry_mrs_simple(None, ticker)
    except Exception as e:
        logger.debug(f"compute_industry_mrs_simple failed for {ticker}: {e}")

    criteria = [
        # --- Moving Averages ---
        {
            "id": 1, "group": "Moving Averages",
            "name": "Preis > MA200",
            "passed": current > ma200 if current and ma200 else None,
            "detail": f"Preis: {current:.2f}, MA200: {ma200:.2f}" if current and ma200 else "N/A",
        },
        {
            "id": 2, "group": "Moving Averages",
            "name": "Preis > MA150",
            "passed": current > ma150 if current and ma150 else None,
            "detail": f"Preis: {current:.2f}, MA150: {ma150:.2f}" if current and ma150 else "N/A",
        },
        {
            "id": 3, "group": "Moving Averages",
            "name": "Preis > MA50",
            "passed": current > ma50 if current and ma50 else None,
            "detail": f"Preis: {current:.2f}, MA50: {ma50:.2f}" if current and ma50 else "N/A",
        },
        {
            "id": 4, "group": "Moving Averages",
            "name": "MA50 > MA150",
            "passed": ma50 > ma150 if ma50 and ma150 else None,
            "detail": f"MA50: {ma50:.2f}, MA150: {ma150:.2f}" if ma50 and ma150 else "N/A",
        },
        {
            "id": 5, "group": "Moving Averages",
            "name": "MA50 > MA200",
            "passed": ma50 > ma200 if ma50 and ma200 else None,
            "detail": f"MA50: {ma50:.2f}, MA200: {ma200:.2f}" if ma50 and ma200 else "N/A",
        },
        {
            "id": 6, "group": "Moving Averages",
            "name": "MA150 > MA200",
            "passed": ma150 > ma200 if ma150 and ma200 else None,
            "detail": f"MA150: {ma150:.2f}, MA200: {ma200:.2f}" if ma150 and ma200 else "N/A",
        },
        {
            "id": 7, "group": "Moving Averages",
            "name": "MA200 steigend (1 Monat)",
            "passed": ma200_rising,
            "detail": f"MA200 jetzt vs vor 1M: {ma200:.2f} vs {ma200_1m_ago:.2f}" if ma200 and ma200_1m_ago else "N/A",
        },
        # --- Breakout (Donchian Channel mit 2-Tages-Confirm) ---
        {
            "id": 8, "group": "Breakout",
            "name": "Donchian 20d Breakout (Tag 2 bestätigt)",
            "passed": breakout_status.get("passed"),
            "pending": breakout_status.get("pending", False),
            "reason": breakout_status.get("reason"),
            "detail": _format_breakout_status_detail(breakout_status, current, ch_high),
            "weight": 2,
        },
        {
            "id": 9, "group": "Breakout",
            "name": "Volumen >= 1.5× Avg",
            "passed": (vol_ratio_20 >= 1.5 and donchian_breakout) if donchian_breakout and avg_vol_20 > 0 else None,
            "detail": f"Vol: {vol_ratio_20}× (braucht >= 1.5×)" if avg_vol_20 > 0 else "N/A",
        },
        {
            "id": 91, "group": "Breakout",
            "name": "Über 150-DMA (Schwur 1)",
            "passed": current > ma150 if current and ma150 else None,
            "detail": f"Kurs {current:.2f} vs MA150 {ma150:.2f}" if current and ma150 else "N/A",
        },
        {
            "id": 92, "group": "Breakout",
            "name": "Max 25% unter 52W-Hoch",
            "passed": pct_from_high >= -25 if pct_from_high is not None else None,
            "detail": f"{pct_from_high:.1f}% vom Hoch ({high_52w})" if pct_from_high is not None else "N/A",
        },
        {
            "id": 93, "group": "Breakout",
            "name": ">= 30% über 52W-Tief",
            "passed": pct_above_low >= 30 if pct_above_low is not None else None,
            "detail": f"{pct_above_low:.1f}% über Tief ({low_52w})" if pct_above_low is not None else "N/A",
        },
        # --- Relative Stärke ---
        {
            "id": 10, "group": "Relative Stärke",
            "name": "Mansfield RS > 0",
            "passed": mrs > 0 if mrs is not None else None,
            "detail": f"MRS: {mrs}" if mrs is not None else "N/A",
        },
        {
            "id": 11, "group": "Relative Stärke",
            "name": "Mansfield RS > 0.5 (stark)",
            "passed": mrs > 0.5 if mrs is not None else None,
            "detail": f"MRS: {mrs}" if mrs is not None else "N/A",
        },
        {
            "id": 12, "group": "Relative Stärke",
            "name": "Sektor führend (MRS > 1.0)",
            "passed": mrs > 1.0 if mrs is not None else None,
            "detail": f"MRS: {mrs} (>1.0 = Sektor-Leader)" if mrs is not None else "N/A",
        },
        # --- Volumen & Liquidität ---
        {
            "id": 13, "group": "Volumen & Liquidität",
            "name": "Marktkapitalisierung > 2 Mrd",
            "passed": info.get("marketCap", 0) > 2_000_000_000 if info.get("marketCap") else None,
            "detail": f"MCap: {_fmt_large(info.get('marketCap'))}",
        },
        {
            "id": 14, "group": "Volumen & Liquidität",
            "name": "Avg Volume > 200k",
            "passed": info.get("averageVolume", 0) > 200_000 if info.get("averageVolume") else None,
            "detail": f"Volume: {_fmt_large(info.get('averageVolume'))}",
        },
        # --- Trendbestätigung ---
        {
            "id": 16, "group": "Trendbestätigung",
            "name": "Bullish MA-Cross 50/150 (20 Tage)",
            "passed": bullish_cross_passed,
            "detail": _format_ma_cross_detail(ma_cross, "bullish"),
        },
        # --- Trendwende ---
        {
            "id": 15, "group": "Trendwende",
            "name": "3-Punkt-Umkehr erkannt",
            "passed": reversal_data["detected"] if below_150dma else None,
            "detail": (
                f"LL1: {reversal_data.get('ll1')}, LL2: {reversal_data.get('ll2')}, "
                f"LL3: {reversal_data.get('ll3')}, HL: {reversal_data.get('hl')}"
            ) if reversal_data["detected"] else (
                "Nur relevant unter 150-DMA" if not below_150dma else "Kein Muster erkannt"
            ),
        },
        # --- Risiken ---
        {
            "id": 17, "group": "Risiken",
            "name": "Death-Cross 50/150 (20 Tage)",
            "passed": death_cross_passed,
            "warning": death_cross_active,
            "detail": _format_ma_cross_detail(ma_cross, "bearish"),
        },
        {
            "id": 18, "group": "Risiken",
            "name": "Distribution Day (Volumen-Spike-Down)",
            "passed": distro_passed,
            "warning": distro.get("detected", False),
            "detail": _format_distro_detail(distro),
        },
        # --- Phase A: Earnings-Proximity (Risiken) ---
        {
            "id": 19, "group": "Risiken",
            "name": "Earnings-Proximity (>= 7 Tage)",
            "passed": earnings_passed,
            "warning": earnings_active,
            "detail": _format_earnings_detail(earnings_dt, days_until_earnings, earnings_active),
        },
        # --- Phase A: Modifier-Gruppe ---
        {
            "id": 20, "group": "Modifier",
            "name": "Distance from MA50",
            "passed": None,
            "score_modifier": ma50_modifier,
            "detail": _format_ma50_distance_detail(ma50_distance_pct, ma50_modifier),
        },
        {
            "id": 21, "group": "Modifier",
            "name": "Volume-Confirmation (Slope vs Vol-Ratio)",
            "passed": None,
            "score_modifier": vol_conf.get("score_modifier"),
            "detail": _format_volume_confirmation_detail(vol_conf),
        },
        # --- Phase A: Industry-Stärke (TradingView-basiert) ---
        {
            "id": 22, "group": "Industry-Stärke",
            "name": "Industry-MRS (perf_3m vs S&P, ±2pp Buffer)",
            "passed": industry_mrs.get("passed"),
            "detail": _format_industry_mrs_detail(industry_mrs),
        },
    ]

    # --- Phase A: asymmetrische Modifier-Aggregation (Risk-First) ---
    # Klassische passed-Items: bestimmen Quality (binär).
    # Modifier-Items: positive UND negative wirken auf display_pct (kosmetisch);
    # NUR negative wirken auf quality_pct (degradieren). So kann ein 16/18-Setup
    # mit Distribution-Verdacht tatsächlich auf BEOBACHTEN fallen, statt nur
    # kosmetisch -3% zu bekommen.
    from services.analysis_config import (
        MODIFIER_WEIGHT_PCT_DISPLAY,
        MODIFIER_WEIGHT_PCT_QUALITY,
    )

    passed_items = [c for c in criteria if c.get("passed") is not None]
    passed_count = sum(1 for c in passed_items if c["passed"] is True)
    total_passed = len(passed_items) if passed_items else len(criteria)
    base_pct = round(passed_count / total_passed * 100) if total_passed > 0 else 0

    modifier_items = [c for c in criteria if c.get("score_modifier") is not None]
    modifier_values = [c["score_modifier"] for c in modifier_items]
    modifier_sum = sum(modifier_values)
    negative_modifier_sum = sum(m for m in modifier_values if m < 0)

    # Display-pct: voller Modifier-Effekt (kosmetisch)
    display_pct = max(0, min(100, round(base_pct + modifier_sum * MODIFIER_WEIGHT_PCT_DISPLAY)))

    # Quality-pct: NUR negative Modifier wirken (Risk-First)
    quality_pct = base_pct + negative_modifier_sum * MODIFIER_WEIGHT_PCT_QUALITY

    # Legacy-pct für 4-Wochen-Migration-Validation parallel loggen
    legacy_assessable = [c for c in criteria if c.get("passed") is not None]
    legacy_passed = sum(1 for c in legacy_assessable if c["passed"] is True)
    legacy_total = len(legacy_assessable) if legacy_assessable else len(criteria)
    pct_legacy = round(legacy_passed / legacy_total * 100) if legacy_total > 0 else 0

    pct = display_pct
    passed = passed_count
    total = total_passed

    # Build alerts
    alerts = []
    if mrs is not None and mrs < -1:
        alerts.append({"type": "danger", "text": f"Mansfield RS sehr schwach ({mrs}) — Finger weg!"})
    elif mrs is not None and mrs < 0:
        alerts.append({"type": "warning", "text": f"Mansfield RS negativ ({mrs}) — relative Schwäche"})
    if pct_from_high is not None and pct_from_high < -20:
        alerts.append({"type": "warning", "text": f"{pct_from_high:.0f}% unter 52W-Hoch — möglicher Abwärtstrend"})
    if current and ma200 and current < ma200:
        alerts.append({"type": "danger", "text": "Preis unter MA200 — bearishes Signal"})
    if quality_pct >= 70:
        alerts.append({"type": "success", "text": f"Score {passed}/{total} ({display_pct}%) — starkes Setup"})

    # Rating: über quality_pct, NICHT über display_pct (Risk-First)
    if quality_pct >= 70:
        rating = "STARK"
    elif quality_pct >= 45:
        rating = "MODERAT"
    else:
        rating = "SCHWACH"

    # Breakout trigger check
    breakout = check_breakout_trigger(ticker, analysis, manual_resistance)
    # determine_signal nimmt passed/total und Breakout — nutzt das Quality-Pattern.
    # Wir füttern es mit (quality-effective) passed-Count, indem wir das
    # quality_pct-Verhältnis auf total normalisieren — so bleibt determine_signal
    # untouched und die Quality-Klassifikation folgt der asymmetrischen Logik.
    quality_effective_passed = round(quality_pct / 100 * total) if total > 0 else 0
    signal_data = determine_signal(quality_effective_passed, total, breakout)

    setup_quality_label = signal_data["quality"]
    signal_label = signal_data["signal_label"]
    signal_value = signal_data["signal"]

    # --- Phase A: Earnings-Quality-Cap (immer aktiv, Banner kommuniziert Eligibility) ---
    if earnings_active:
        if setup_quality_label == "STARK":
            setup_quality_label = "BEOBACHTEN"
            # WATCHLIST = Original-Label für Setup_quality=BEOBACHTEN (siehe scoring_service.py)
            signal_value = "WATCHLIST"
        split_entry_eligible = (
            passed_count >= 15
            and mrs is not None and mrs > 1.0
            and industry_mrs.get("passed") is True
            and negative_modifier_sum == 0
        )
        if split_entry_eligible:
            signal_label = (
                f"Earnings in {days_until_earnings} Tagen — Quality auf BEOBACHTEN gecapt. "
                f"Split-Entry-Eligibility erfüllt (Score≥15 + MRS>1.0 + Industry-MRS+ + keine Risk-Modifier): "
                f"halbe Position vor Earnings möglich."
            )
        else:
            signal_label = f"Earnings in {days_until_earnings} Tagen — Setup blockiert"

    return {
        "ticker": ticker,
        "name": info.get("shortName", ticker),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "price": current,
        "currency": info.get("currency", ""),
        "market_cap": info.get("marketCap"),
        "score": passed,
        "max_score": total,
        "pct": pct,
        "pct_legacy": pct_legacy,        # 4-Wochen-Migration-Logging
        "base_pct": base_pct,            # Diagnostic: Quality-Bestimmungs-Basis
        "quality_pct": round(quality_pct), # Diagnostic: nach Negative-Modifier-Cap
        "rating": rating,
        "criteria": criteria,
        "alerts": alerts,
        "mansfield_rs": mrs,
        "range_52w": range_data,
        "breakout": breakout,
        "signal": signal_value,
        "signal_label": signal_label,
        "setup_quality": setup_quality_label,
        "three_point_reversal": reversal_data if reversal_data["detected"] else None,
        "earnings_proximity_active": earnings_active,
        "earnings_date": earnings_dt.isoformat() if earnings_dt else None,
        "days_until_earnings": days_until_earnings,
    }




def _fmt_large(val) -> str:
    if val is None:
        return "N/A"
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:.1f} Mrd"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f} Mio"
    if val >= 1_000:
        return f"{val / 1_000:.0f}k"
    return str(val)


def _fmt_pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{val * 100:.1f}%"


def _format_ma_cross_detail(ma_cross: dict, expected_type: str) -> str:
    """Build the detail string for a MA-Cross criterion.

    ``expected_type`` is "bullish" for the Trendbestätigung-criterion or
    "bearish" for the Death-Cross-criterion. Same ma_cross dict is used
    for both, but each criterion describes the perspective of its own
    expectation.
    """
    if ma_cross.get("whipsaw"):
        return "Whipsaw — keine klare Trendrichtung (≥2 Crosses im Window)"

    reason = ma_cross.get("reason")
    if reason == "no_data" or reason == "no_cross":
        return "Kein 50/150-Cross in den letzten 20 Tagen"
    if reason == "failed_cross":
        pct = ma_cross.get("pct_since_cross")
        cross_date = ma_cross.get("cross_date")
        return f"Cross am {cross_date}, Setup invalidiert ({pct:+.1f}% seitdem)" if pct is not None else "Failed Cross"

    actual_type = ma_cross.get("type")
    cross_date = ma_cross.get("cross_date")
    cross_price = ma_cross.get("cross_price")
    pct = ma_cross.get("pct_since_cross")
    if actual_type == expected_type and ma_cross.get("detected"):
        direction = "Bullish-Cross" if actual_type == "bullish" else "Death-Cross"
        return f"{direction} am {cross_date} bei {cross_price} ({pct:+.1f}% seitdem)"

    if actual_type and actual_type != expected_type:
        # Cross gefunden, aber andere Richtung als das Kriterium fragt
        other = "Bullish-Cross" if actual_type == "bullish" else "Death-Cross"
        return f"Kein {('Bullish' if expected_type == 'bullish' else 'Death')}-Cross — stattdessen {other} am {cross_date}"

    return "Kein Cross im Lookback-Window"


def _format_distro_detail(distro: dict) -> str:
    """Build the detail string for the Distribution-Day criterion."""
    if distro.get("detected"):
        return (
            f"Distribution Day am {distro['spike_date']}: "
            f"Volume {distro['volume_ratio']:.1f}× Avg ({distro['close']:.2f} < {distro['open']:.2f})"
        )
    reason = distro.get("reason")
    if reason == "no_data":
        return "Volumen-/Open-Daten nicht verfügbar"
    if reason == "insufficient_history":
        return "Zu wenig Historie für Distribution-Day-Detection"
    return "Kein Distribution Day in den letzten 20 Tagen"


def _format_breakout_status_detail(status: dict, current: float | None, ch_high: float | None) -> str:
    """Detail-String für das 4-State Donchian-Breakout-Kriterium id=8."""
    reason = status.get("reason")
    breakout_date = status.get("breakout_date")
    resistance = status.get("resistance")
    if status.get("passed") is True:
        return f"Bestätigt: Ausbruch {breakout_date} bei {resistance}, Tag 2 hat Niveau gehalten"
    if status.get("pending"):
        return f"Pending: Ausbruch heute bei {resistance} — Tag-2-Bestätigung steht noch aus"
    if reason == "fakeout":
        return f"Fakeout: Ausbruch am {breakout_date} bei {resistance} — Tag 2 zurück unter Resistance"
    if reason == "no_breakout":
        if current is not None and ch_high is not None:
            return f"Kein Ausbruch — Kurs {current:.2f} vs 20d-Hoch {ch_high}"
        return "Kein Donchian-Breakout in den letzten Tagen"
    if reason == "no_data":
        return "Daten nicht verfügbar"
    return "Status unbekannt"


def _format_earnings_detail(earnings_dt, days_until: int | None, active: bool) -> str:
    if earnings_dt is None:
        return "Earnings-Datum unbekannt — nicht in die Score-Bewertung einbezogen"
    iso = earnings_dt.isoformat() if hasattr(earnings_dt, "isoformat") else str(earnings_dt)
    if active:
        return f"⚠ Earnings am {iso} (in {days_until} Tagen) — aktives Risiko, Setup blockiert"
    return f"Earnings am {iso} (in {days_until} Tagen) — kein aktives Risiko"


def _format_ma50_distance_detail(distance_pct: float | None, modifier: int | None) -> str:
    if modifier is None:
        if distance_pct is None:
            return "Kurs ≤ MA50 oder MA50 nicht verfügbar — Modifier nicht bewertbar"
        return "Modifier nicht bewertbar"
    pct = distance_pct * 100 if distance_pct is not None else 0
    if modifier == 1:
        return f"Gesund: {pct:.1f}% über MA50 (< 15%) — +1 Modifier"
    if modifier == -1:
        return f"Überstreckt: {pct:.1f}% über MA50 (> 25%) — -1 Modifier (Mean-Reversion-Risiko)"
    return f"Neutral: {pct:.1f}% über MA50 (15–25%) — etwas gestreckt, kein Modifier"


def _format_volume_confirmation_detail(vol_conf: dict) -> str:
    modifier = vol_conf.get("score_modifier")
    if modifier is None:
        return "Zu wenig Daten für Volume-Confirmation"
    slope = vol_conf.get("slope_pct")
    ratio = vol_conf.get("vol_ratio")
    regime = vol_conf.get("regime")
    reason = vol_conf.get("reason")
    regime_marker = " (Mega-Cap-Schwellen 0.75/1.25)" if regime == "megacap" else ""
    reason_labels = {
        "neutral_trend": "Seitwärts/unklar — kein Signal",
        "bearish_divergence": "Bearish Divergence: Kurs steigt, Volumen schwächt sich ab",
        "healthy_confirmation": "Healthy Confirmation: Kurs steigt, Volumen bestätigt",
        "distribution_selling": "Distribution: Kurs fällt mit erhöhtem Volumen",
        "healthy_pullback": "Pullback auf niedrigem Volumen — gesund",
        "neutral_volume": "Volumen neutral",
    }
    label = reason_labels.get(reason, reason or "?")
    return f"Slope {slope}%, VolRatio {ratio}{regime_marker} — {label} (Modifier {modifier:+d})"


def _format_industry_mrs_detail(industry_mrs: dict) -> str:
    if industry_mrs.get("passed") is None:
        reason = industry_mrs.get("reason")
        if reason == "ticker_not_in_mapping":
            return "Ticker nicht in TradingView-Industry-Mapping (Non-US oder neues Listing)"
        if reason == "no_industry_snapshot":
            return f"Industry {industry_mrs.get('industry_name')} hat keinen aktuellen Snapshot"
        if reason == "no_benchmark":
            return f"S&P-Benchmark nicht verfügbar (Industry: {industry_mrs.get('industry_name')})"
        if reason == "phase_2_not_implemented":
            return "Industry-MRS rolling-Variante in Phase 2"
        # Buffer-Zone (passed=None und alle Daten da)
        diff = industry_mrs.get("diff_pp")
        if diff is not None:
            return f"Industry {industry_mrs.get('industry_name')}: {diff:+.1f}pp vs S&P (in ±2pp-Buffer-Zone)"
        return industry_mrs.get("reason") or "Industry-MRS nicht bewertbar"
    diff = industry_mrs.get("diff_pp")
    industry_name = industry_mrs.get("industry_name")
    if industry_mrs["passed"]:
        return f"Industry {industry_name} läuft +{diff}pp über S&P (3M)"
    return f"Industry {industry_name} läuft {diff}pp gegen S&P (3M)"
