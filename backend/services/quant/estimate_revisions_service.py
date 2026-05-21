"""Analyst-Estimate-Revisions — FMP Snapshots + 30/60/90d-Delta-Berechnung.

Lean-Probe-Scope (Kill-Gate 2026-08-15):
- Universum = DISTINCT(Portfolio + Watchlist)
- Quelle: FMP /v3/analyst-estimates/{ticker} (per-User Key, _get_any_user_fmp_key)
- Persistenz: estimate_revisions (taegliche Snapshots, UNIQUE(ticker, snapshot_date))
- Signal-Berechnung on-demand: latest vs. 30/60/90d-prior aus History

Decision-Impact: kippt /trade-plan oder /earnings-prep, wenn EPS-FY1-Revision
ueber Schwellwert. Bar: 3 Kippungen bis 2026-08-15.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.estimate_revision import EstimateRevision
from models.user import User
from services.api_utils import fetch_json
from services.screening.universe import resolve_equity_universe

logger = logging.getLogger(__name__)

_FMP_BASE = "https://financialmodelingprep.com/stable"

# Schwellwert ab dem ein Delta als Signal gilt (relative Aenderung)
REVISION_SIGNAL_THRESHOLD_PCT = 2.0  # +/- 2% Konsens-EPS-Revision


# ---------------------------------------------------------------------------
# Key + Universe helpers
# ---------------------------------------------------------------------------

async def _get_any_user_fmp_key(db: AsyncSession) -> str | None:
    """Finde irgendeinen aktiven User mit konfiguriertem FMP-Key.

    Mirror von etf_holdings_service._get_any_user_fmp_key — Estimate-Daten
    sind global, kein Sinn pro User zu iterieren.
    """
    from services.settings_service import get_user_api_key

    result = await db.execute(select(User.id).where(User.is_active.is_(True)))
    user_ids = [row[0] for row in result.all()]
    for uid in user_ids:
        try:
            key = await get_user_api_key(db, uid, "fmp_api_key")
            if key:
                return key
        except Exception:
            continue
    return None


async def _resolve_universe(db: AsyncSession) -> list[str]:
    """DISTINCT(US-Equity-Positions ∪ Watchlist).

    Delegiert an `services.screening.universe.resolve_equity_universe` —
    type=stock-Filter eliminiert die 21 garantierten 404s (Cash, Crypto,
    EU-ETFs, Multi-Listing-Suffixe). FMP-Free-Tier-Paywall (HTTP 402) bleibt
    fuer 6 namentliche Tickers (ASML, PM, RSG, WM, PAAS, TYL) — siehe
    diagnose_universe_audit_2026-05-21.md.
    """
    return await resolve_equity_universe(db)


# ---------------------------------------------------------------------------
# FMP fetch
# ---------------------------------------------------------------------------

def _to_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


async def _fetch_estimate_for_ticker(ticker: str, fmp_key: str) -> dict | None:
    """Hole FMP-Konsens-Estimate fuer einen Ticker.

    FMP `/stable/analyst-estimates?symbol={ticker}&period=annual` liefert
    Liste von Forward-Years. Wir nehmen die erste (FY1) und ggf. zweite (FY2).
    Stable-Endpoint seit 2025-08-31 verbindlich — Legacy `/api/v3/` liefert 403.
    """
    url = f"{_FMP_BASE}/analyst-estimates"
    try:
        data = await fetch_json(
            url,
            params={"symbol": ticker, "period": "annual", "apikey": fmp_key},
            timeout=15,
        )
    except Exception as e:
        logger.debug("FMP estimates fetch failed for %s: %s", ticker, e)
        return None

    if not isinstance(data, list) or not data:
        return None
    today = date.today().isoformat()
    future = [row for row in data if isinstance(row, dict) and (row.get("date") or "") >= today]
    if not future:
        future = data[:2]
    future.sort(key=lambda r: r.get("date") or "")
    fy1 = future[0] if len(future) >= 1 else {}
    fy2 = future[1] if len(future) >= 2 else {}
    return {
        "eps_fy1": _to_decimal(fy1.get("epsAvg")),
        "eps_fy2": _to_decimal(fy2.get("epsAvg")),
        "revenue_fy1": _to_decimal(fy1.get("revenueAvg")),
        "num_analysts": fy1.get("numAnalystsRevenue") or fy1.get("numAnalystsEps"),
    }


# ---------------------------------------------------------------------------
# Refresh pipeline
# ---------------------------------------------------------------------------

async def refresh_estimate_revisions(db: AsyncSession) -> dict[str, Any]:
    """Taeglicher Snapshot fuer Universum. Idempotent durch UNIQUE(ticker, snapshot_date)."""
    fmp_key = await _get_any_user_fmp_key(db)
    if not fmp_key:
        logger.warning("estimate_revisions: kein FMP-Key vorhanden — skip")
        return {"status": "no_key", "tickers_scanned": 0, "snapshots_written": 0}

    tickers = await _resolve_universe(db)
    today = date.today()
    written = 0
    failed: list[str] = []
    for t in tickers:
        try:
            payload = await _fetch_estimate_for_ticker(t, fmp_key)
        except Exception:
            logger.exception("estimate_revisions fetch failed for %s", t)
            failed.append(t)
            continue
        if not payload:
            continue
        stmt = pg_insert(EstimateRevision).values(
            ticker=t,
            snapshot_date=today,
            eps_fy1=payload["eps_fy1"],
            eps_fy2=payload["eps_fy2"],
            revenue_fy1=payload["revenue_fy1"],
            num_analysts=payload["num_analysts"],
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "snapshot_date"],
            set_={
                "eps_fy1": stmt.excluded.eps_fy1,
                "eps_fy2": stmt.excluded.eps_fy2,
                "revenue_fy1": stmt.excluded.revenue_fy1,
                "num_analysts": stmt.excluded.num_analysts,
            },
        )
        result = await db.execute(stmt)
        if result.rowcount:
            written += int(result.rowcount)
    if written:
        await db.commit()
    return {
        "status": "ok",
        "tickers_scanned": len(tickers),
        "snapshots_written": written,
        "fetch_failures": len(failed),
    }


# ---------------------------------------------------------------------------
# Signal computation (used by screening_service)
# ---------------------------------------------------------------------------

def _pct_delta(latest: Decimal | None, prior: Decimal | None) -> float | None:
    if latest is None or prior is None:
        return None
    if prior == 0:
        return None
    try:
        return float((latest - prior) / abs(prior) * 100)
    except Exception:
        return None


async def compute_revision_signals(db: AsyncSession) -> list[dict]:
    """Pro Ticker: aktueller Snapshot + 30/60/90d-Delta auf eps_fy1.

    Signal wird zurueckgegeben, wenn |delta_30d| ODER |delta_60d| ODER
    |delta_90d| >= REVISION_SIGNAL_THRESHOLD_PCT.
    """
    today = date.today()
    horizons = [30, 60, 90]

    q = (
        select(EstimateRevision)
        .where(EstimateRevision.snapshot_date >= today - timedelta(days=120))
        .order_by(EstimateRevision.ticker, EstimateRevision.snapshot_date.desc())
    )
    rows = (await db.execute(q)).scalars().all()
    if not rows:
        return []

    by_ticker: dict[str, list[EstimateRevision]] = {}
    for r in rows:
        by_ticker.setdefault(r.ticker, []).append(r)

    signals: list[dict] = []
    for ticker, snapshots in by_ticker.items():
        snapshots.sort(key=lambda s: s.snapshot_date, reverse=True)
        latest = snapshots[0]
        if latest.eps_fy1 is None:
            continue

        deltas: dict[str, float | None] = {}
        for h in horizons:
            target = today - timedelta(days=h)
            prior = next(
                (s for s in snapshots if s.snapshot_date <= target),
                None,
            )
            deltas[f"delta_{h}d"] = _pct_delta(
                latest.eps_fy1, prior.eps_fy1 if prior else None
            )

        # Trigger nur wenn mind. ein Horizon ueber Schwellwert
        triggered = any(
            d is not None and abs(d) >= REVISION_SIGNAL_THRESHOLD_PCT
            for d in deltas.values()
        )
        if not triggered:
            continue

        signals.append({
            "ticker": ticker,
            "snapshot_date": latest.snapshot_date.isoformat(),
            "eps_fy1": float(latest.eps_fy1) if latest.eps_fy1 is not None else None,
            "num_analysts": latest.num_analysts,
            **{k: (round(v, 2) if v is not None else None) for k, v in deltas.items()},
        })
    return signals
