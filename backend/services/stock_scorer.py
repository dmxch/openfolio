import logging

import pandas as pd
import yfinance as yf
from yf_patch import yf_download
from services.utils import compute_mansfield_rs
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

        result = {
            "mas": mas, "range_data": range_data, "ma200_rising": ma200_rising, "ma200_1m_ago": ma200_1m_ago,
            "current_volume": current_volume, "avg_volume_50": avg_volume_50, "avg_volume_20": avg_volume_20,
            "donchian": donchian,
            "mrs": mrs,
        }
        cache.set(cache_key, result)
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
    """18-point buying checklist for stock analysis with breakout trigger."""
    t = yf.Ticker(ticker)

    # Single download for all price-based analysis
    analysis = _download_and_analyze(ticker)
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

    try:
        info = t.info
    except Exception as e:
        logger.debug(f"Could not fetch yfinance info for {ticker}: {e}")
        info = {}

    high_52w = range_data.get("high_52w")
    low_52w = range_data.get("low_52w")
    pct_from_high = range_data.get("pct_from_high")
    pct_above_low = round(((current - low_52w) / low_52w * 100), 2) if current and low_52w and low_52w > 0 else None

    # Volume ratio for Donchian breakout
    current_vol = analysis.get("current_volume", 0)
    vol_ratio_20 = round(current_vol / avg_vol_20, 1) if avg_vol_20 > 0 else 0
    donchian_breakout = donchian.get("breakout", False)
    ch_high = donchian.get("channel_high")

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
        # --- Breakout (Donchian Channel) ---
        {
            "id": 8, "group": "Breakout",
            "name": "Donchian 20d Breakout",
            "passed": donchian_breakout if ch_high is not None else None,
            "detail": f"Kurs {current:.2f} {'>' if donchian_breakout else '<'} 20d-Hoch {ch_high}" if ch_high and current else "N/A",
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
        # --- Fundamentals ---
        {
            "id": 15, "group": "Fundamentals",
            "name": "Umsatz steigend (YoY)",
            "passed": _revenue_growing(info),
            "detail": f"Revenue Growth: {_fmt_pct(info.get('revenueGrowth'))}",
        },
        {
            "id": 16, "group": "Fundamentals",
            "name": "EPS steigend (YoY)",
            "passed": _eps_growing(info),
            "detail": f"Earnings Growth: {_fmt_pct(info.get('earningsGrowth'))}",
        },
        {
            "id": 17, "group": "Fundamentals",
            "name": "ROE > 15%",
            "passed": info.get("returnOnEquity", 0) > 0.15 if info.get("returnOnEquity") else None,
            "detail": f"ROE: {_fmt_pct(info.get('returnOnEquity'))}",
        },
        {
            "id": 18, "group": "Fundamentals",
            "name": f"D/E unter Branche Ø ({_industry_de_label(info)})",
            "passed": _de_vs_industry(info),
            "detail": f"D/E: {info.get('debtToEquity', 0) / 100:.2f}" if info.get("debtToEquity") is not None else "N/A",
        },
    ]

    passed = sum(1 for c in criteria if c["passed"] is True)
    total = len(criteria)  # Always 18 — missing data counts as not passed
    pct = round(passed / total * 100) if total > 0 else 0

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
    if pct >= 70:
        alerts.append({"type": "success", "text": f"Score {passed}/{total} ({pct}%) — starkes Setup"})

    # Rating
    if pct >= 70:
        rating = "STARK"
    elif pct >= 45:
        rating = "MODERAT"
    else:
        rating = "SCHWACH"

    # Breakout trigger check
    breakout = check_breakout_trigger(ticker, analysis, manual_resistance)
    signal_data = determine_signal(passed, total, breakout)

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
        "rating": rating,
        "criteria": criteria,
        "alerts": alerts,
        "mansfield_rs": mrs,
        "range_52w": range_data,
        "breakout": breakout,
        "signal": signal_data["signal"],
        "signal_label": signal_data["signal_label"],
        "setup_quality": signal_data["quality"],
    }


def _get_industry_de(info: dict) -> float:
    """Get industry average D/E ratio (yfinance %-format, e.g. 250 = 2.50)."""
    from services.industry_averages import get_industry_averages
    avg = get_industry_averages(info.get("industry"), info.get("sector"))
    if avg and avg.get("de_ratio") is not None:
        return avg["de_ratio"] * 100  # Convert to yfinance format
    return 150  # Fallback: 1.5


def _de_vs_industry(info: dict) -> bool | None:
    """Check if D/E is at or below industry average (with 20% tolerance)."""
    de = info.get("debtToEquity")
    if de is None:
        return None
    threshold = _get_industry_de(info) * 1.2
    return de <= threshold


def _industry_de_label(info: dict) -> str:
    """Format industry D/E average for display."""
    avg_de = _get_industry_de(info) / 100
    return f"{avg_de:.2f}"


def _revenue_growing(info: dict) -> bool | None:
    growth = info.get("revenueGrowth")
    if growth is None:
        return None
    return growth > 0


def _eps_growing(info: dict) -> bool | None:
    growth = info.get("earningsGrowth")
    if growth is None:
        return None
    return growth > 0


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
