"""Core-Overlap-Service: indirekte Aktien-Exposure via User-ETFs.

Wenn der User eine Direkt-Aktie (z.B. NVDA) prüft, zeigt dieser Service
die ETFs aus seinem aktiven Portfolio, die NVDA mit Gewicht ≥2% halten.
Daraus ergibt sich:

  - pro Overlap: indirekte CHF-Exposure (ETF-Position × Gewicht)
  - Banner-Text mit konkreten Zahlen (statt "wäre erhöhte Konzentration")
  - Watchlist-Spalte: max-Gewicht über alle User-ETFs für jeden Ticker

User-Scope: nur User-eigene ETFs zählen. Score-Endpoint ist Wrapper —
``get_overlap_for_ticker`` wird dort aufgerufen, damit ``score_stock``
selbst user-agnostisch bleibt (Architektur-Disziplin aus Phase A).
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.etf_holding import EtfHolding
from models.position import Position
from services.analysis_config import CORE_OVERLAP_MIN_WEIGHT_PCT

logger = logging.getLogger(__name__)


async def _get_user_etf_positions_with_values(
    db: AsyncSession, user_id: UUID,
) -> dict[str, dict]:
    """Returns dict[etf_ticker, {position_id, name, market_value_chf}].

    Nutzt portfolio_service als Single-Source-of-Truth für market_value_chf
    (FX-Konvertierung, Live-Preise, Stale-Handling sind dort gekapselt).
    """
    from services.portfolio_service import get_portfolio_summary

    portfolio = await get_portfolio_summary(db, user_id)
    etf_map: dict[str, dict] = {}
    for p in portfolio.get("positions", []):
        if p.get("type") == "etf" and p.get("market_value_chf") and p["market_value_chf"] > 0:
            ticker = p.get("ticker", "")
            if ticker:
                etf_map[ticker.upper()] = {
                    "name": p.get("name", ticker),
                    "market_value_chf": float(p["market_value_chf"]),
                }
    return etf_map


async def get_overlap_for_ticker(
    db: AsyncSession, ticker: str, user_id: UUID,
) -> list[dict]:
    """Per-Ticker Overlap mit konkreter CHF-Exposure-Berechnung.

    Returns sortierte Liste (höchstes Gewicht zuerst):
        [{etf_ticker, etf_name, weight_pct, etf_position_chf,
          indirect_exposure_chf, holdings_as_of}]

    Filter: nur Overlaps mit weight_pct >= CORE_OVERLAP_MIN_WEIGHT_PCT
    UND nur ETFs, die der User aktiv im Portfolio hat. Leere Liste wenn
    Ticker nicht in einem User-ETF mit Threshold-Erfüllung.
    """
    ticker_upper = ticker.upper()

    user_etfs = await _get_user_etf_positions_with_values(db, user_id)
    if not user_etfs:
        return []

    # Reverse-Lookup: alle ETFs in der DB die diesen Ticker mit ≥2% halten
    rows = (
        await db.execute(
            select(
                EtfHolding.etf_ticker,
                EtfHolding.holding_name,
                EtfHolding.weight_pct,
                EtfHolding.as_of,
            ).where(
                EtfHolding.holding_ticker == ticker_upper,
                EtfHolding.weight_pct >= CORE_OVERLAP_MIN_WEIGHT_PCT,
                EtfHolding.etf_ticker.in_(list(user_etfs.keys())),
            )
        )
    ).all()

    overlaps: list[dict] = []
    for etf_ticker, holding_name, weight_pct, as_of in rows:
        user_etf = user_etfs.get(etf_ticker)
        if user_etf is None:
            continue
        weight = float(weight_pct)
        etf_position_chf = user_etf["market_value_chf"]
        indirect_exposure_chf = etf_position_chf * weight / 100.0
        overlaps.append({
            "etf_ticker": etf_ticker,
            "etf_name": user_etf["name"],
            "weight_pct": round(weight, 2),
            "etf_position_chf": round(etf_position_chf, 2),
            "indirect_exposure_chf": round(indirect_exposure_chf, 2),
            "holdings_as_of": as_of.isoformat() if as_of else None,
        })

    overlaps.sort(key=lambda x: -x["weight_pct"])
    return overlaps


async def get_overlap_max_weight_for_tickers(
    db: AsyncSession, tickers: list[str], user_id: UUID,
) -> dict[str, float]:
    """Bulk-Lookup für Watchlist: ticker → max weight_pct über User-ETFs.

    Eine SQL-Query mit IN-Clause statt N+1. Returns leeres Dict für
    Tickers ohne Overlap. Threshold ≥2% wird hier auch angewendet, damit
    die Watchlist-Spalte nur "echte" Overlaps zeigt.
    """
    if not tickers:
        return {}

    user_etfs = await _get_user_etf_positions_with_values(db, user_id)
    if not user_etfs:
        return {}

    upper_tickers = [t.upper() for t in tickers if t]
    if not upper_tickers:
        return {}

    rows = (
        await db.execute(
            select(
                EtfHolding.holding_ticker,
                EtfHolding.weight_pct,
            ).where(
                EtfHolding.holding_ticker.in_(upper_tickers),
                EtfHolding.weight_pct >= CORE_OVERLAP_MIN_WEIGHT_PCT,
                EtfHolding.etf_ticker.in_(list(user_etfs.keys())),
            )
        )
    ).all()

    max_weights: dict[str, float] = {}
    for holding_ticker, weight_pct in rows:
        weight = float(weight_pct)
        cur = max_weights.get(holding_ticker)
        if cur is None or weight > cur:
            max_weights[holding_ticker] = round(weight, 2)
    return max_weights
