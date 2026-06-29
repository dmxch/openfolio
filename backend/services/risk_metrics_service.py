"""Risiko-Kennzahlen (additiv, read-only) aus der cash-flow-bereinigten Tagesreihe.

Beruehrt KEINE geschuetzte Performance-Berechnung (HEILIGE Regeln 1 & 11). Rechnet
ausschliesslich auf der von history_service.get_portfolio_history() gelieferten
`portfolio_indexed`-Reihe — dieselbe Quelle wie Drawdown + Faktor-Decomposition.

`annualized_return_pct` ist eine zeitgewichtete (TWR-)Annualisierung der Index-Reihe,
die als Zaehler fuer die Risiko-Ratios dient. Sie ist bewusst NICHT die im
TotalReturnCard gezeigte XIRR/MWR-Jahresrendite (HEILIGE Regel 11) — sie wird nur fuer
Sharpe/Sortino/Calmar/Information-Ratio gebraucht, wo der Zaehler zur (TWR-basierten)
Volatilitaet passen muss.

bucket_id (optional) skopiert die Reihe auf die Positionen eines Buckets — selbe
Methodik wie das Gesamtportfolio (cash-flow-bereinigt).
"""
from __future__ import annotations

import logging
import math
import statistics
import uuid
from datetime import date

from config import settings
from services.benchmark_service import get_benchmark_name
from services.history_service import get_portfolio_history

logger = logging.getLogger(__name__)

MIN_OBS = 20  # weniger Tagesrenditen -> Kennzahlen nicht aussagekraeftig
TRADING_DAYS_PER_YEAR = 252

# Trailing-Fenster fuer Rolling-Returns (Handelstage approximiert)
_ROLLING_WINDOWS = {"1m": 21, "3m": 63, "6m": 126, "1y": 252}


def _daily_returns(levels: list[float]) -> list[float]:
    out = []
    for i in range(1, len(levels)):
        prev = levels[i - 1]
        if prev and prev > 0:
            out.append(levels[i] / prev - 1.0)
        else:
            out.append(0.0)
    return out


def _annualized_return(levels: list[float], n_returns: int) -> float:
    """Geometrisch annualisierte TWR aus erstem/letztem Index-Level."""
    if n_returns <= 0 or not levels or levels[0] <= 0:
        return 0.0
    total_factor = levels[-1] / levels[0]
    if total_factor <= 0:
        return -1.0
    return total_factor ** (TRADING_DAYS_PER_YEAR / n_returns) - 1.0


def _max_drawdown(levels: list[float]) -> float:
    """Max Peak-to-Trough Drawdown der Index-Reihe als positiver Bruch (0..1)."""
    peak = float("-inf")
    max_dd = 0.0
    for v in levels:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _downside_deviation(returns: list[float], mar_daily: float = 0.0) -> float:
    """Annualisierte Downside-Deviation (Target = mar_daily, Default 0)."""
    if not returns:
        return 0.0
    sq = [min(r - mar_daily, 0.0) ** 2 for r in returns]
    return math.sqrt(sum(sq) / len(returns)) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _safe_ratio(num: float, den: float) -> float | None:
    if den and den > 0:
        return round(num / den, 2)
    return None


async def _resolve_benchmark(
    db,
    benchmark: str | None,
    user_id: uuid.UUID | None,
    bucket_id: uuid.UUID | None,
) -> str:
    """Benchmark-Ticker aufloesen.

    Explizit gesetzt -> verwenden. Sonst bei bucket_id den pro-Bucket konfigurierten
    `bucket.benchmark` (Core->URTH, Satellite->MTUM, …) — dieselbe Quelle, die auch
    /buckets/{id}/benchmark-comparison nutzt. Fallback ^GSPC.

    Hintergrund: risk-metrics nutzte bisher IMMER ^GSPC, auch mit bucket_id. Damit
    massen Information-Ratio/Tracking-Error den falschen Stil (z.B. ein Momentum-
    Satellite gegen den breiten Markt statt gegen MTUM).
    """
    if benchmark is not None:
        return benchmark
    if bucket_id is not None and db is not None:
        from sqlalchemy import select

        from models.bucket import Bucket

        q = select(Bucket.benchmark).where(Bucket.id == bucket_id)
        if user_id is not None:
            q = q.where(Bucket.user_id == user_id)
        bench_row = (await db.execute(q)).scalar_one_or_none()
        if bench_row:
            return bench_row
    return "^GSPC"


async def compute_risk_metrics(
    db,
    start_date: date,
    end_date: date,
    benchmark: str | None = None,
    user_id: uuid.UUID | None = None,
    bucket_id: uuid.UUID | None = None,
) -> dict:
    """Sharpe/Sortino/Calmar/Volatilitaet/Information-Ratio + Rolling-Returns.

    `benchmark=None` (Default) loest den Massstab kontextabhaengig auf: pro Bucket
    den konfigurierten `bucket.benchmark`, sonst ^GSPC (siehe `_resolve_benchmark`).
    Ein explizit uebergebener Ticker hat Vorrang.

    Returns dict mit Kennzahlen oder {"error": "insufficient_history", "n_obs": N}.
    """
    benchmark = await _resolve_benchmark(db, benchmark, user_id, bucket_id)
    hist = await get_portfolio_history(
        db,
        start_date,
        end_date,
        benchmark=benchmark,
        user_id=user_id,
        downsample=False,  # rohe Tagesreihe
        liquid=True,       # Rendite-Risikobuch (ohne Cash/Vorsorge/PE/Immobilien)
        bucket_id=bucket_id,
    )
    points = hist.get("data", [])
    if len(points) < MIN_OBS + 1:
        return {"error": "insufficient_history", "n_obs": max(len(points) - 1, 0)}

    levels = [float(p["portfolio_indexed"]) for p in points]
    returns = _daily_returns(levels)
    n = len(returns)

    rf_pct = float(settings.risk_free_rate_pct)
    rf_decimal = rf_pct / 100.0

    ann_return = _annualized_return(levels, n)
    vol = statistics.stdev(returns) * math.sqrt(TRADING_DAYS_PER_YEAR) if n >= 2 else 0.0
    downside_vol = _downside_deviation(returns)
    max_dd = _max_drawdown(levels)

    # Degenerierte (konstante / null-varianz) Reihe: Vola == 0 trotz ausreichender
    # Beobachtungen. Tritt auf, wenn die zugrundeliegende Wert-Reihe flach ist (z.B.
    # ein Asset, das nicht markiert wird). Sharpe/Sortino/IR sind dann nicht definiert
    # (None via _safe_ratio); wir signalisieren das explizit statt stiller Nullen,
    # damit die UI eine Warnung zeigen kann (kein 422 — die Reihe ist nicht "zu kurz").
    degenerate = vol == 0.0

    excess_ann = ann_return - rf_decimal
    sharpe = _safe_ratio(excess_ann, vol)
    sortino = _safe_ratio(excess_ann, downside_vol)
    calmar = _safe_ratio(ann_return, max_dd)

    # Information Ratio (nur wenn Benchmark-Serie vorhanden)
    info_ratio = None
    bench_ann_return = None
    tracking_error = None
    bench_levels = [
        float(p["benchmark_indexed"]) for p in points if "benchmark_indexed" in p
    ]
    if len(bench_levels) == len(levels) and len(bench_levels) >= 2:
        bench_returns = _daily_returns(bench_levels)
        bench_ann_return = _annualized_return(bench_levels, len(bench_returns))
        excess_daily = [returns[i] - bench_returns[i] for i in range(n)]
        if len(excess_daily) >= 2:
            tracking_error = statistics.stdev(excess_daily) * math.sqrt(TRADING_DAYS_PER_YEAR)
            info_ratio = _safe_ratio(ann_return - bench_ann_return, tracking_error)

    # Rolling Trailing-Returns
    rolling: dict[str, float | None] = {}
    for label, w in _ROLLING_WINDOWS.items():
        if len(levels) > w and levels[-1 - w] > 0:
            rolling[label] = round((levels[-1] / levels[-1 - w] - 1.0) * 100.0, 2)
        else:
            rolling[label] = None

    return {
        "n_obs": n,
        "degenerate": degenerate,
        "window": {
            "start": points[0]["date"],
            "end": points[-1]["date"],
        },
        "risk_free_rate_pct": round(rf_pct, 2),
        "annualized_return_pct": round(ann_return * 100, 2),
        "volatility_pct": round(vol * 100, 2),
        "downside_volatility_pct": round(downside_vol * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "information_ratio": info_ratio,
        "tracking_error_pct": (
            round(tracking_error * 100, 2) if tracking_error is not None else None
        ),
        "benchmark": benchmark,
        "benchmark_name": get_benchmark_name(benchmark),
        "benchmark_annualized_return_pct": (
            round(bench_ann_return * 100, 2) if bench_ann_return is not None else None
        ),
        "rolling_returns": rolling,
        "method": (
            "TWR-Index (cash-flow-bereinigt, liquid=True, raw=true); "
            "Annualisierung 252 Handelstage; rf via RISK_FREE_RATE_PCT"
        ),
    }
