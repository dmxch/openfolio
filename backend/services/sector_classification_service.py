"""Sektor-Klassifikation für Konzentrations-Aggregation (Phase 1.1).

Drei-stufige Cascade pro Ticker:
  1. SECTOR_OVERRIDES (manuell, in Git, reviewbar)
  2. ticker_industries.industry_name → INDUSTRY_TO_SECTOR Mapping
  3. None ("Unclassified")

Bulk-Primary-API gegen N+1: Sektor-Anteil eines ETFs braucht ~100
Klassifikationen — pro Score-Endpoint-Aufruf wären 100 sync-DB-Roundtrips
ein Event-Loop-Block. ``classify_tickers_bulk`` macht eine SQL-Query
unabhängig von len(tickers); ``classify_ticker_sector`` ist ein dünner
Wrapper für Single-Lookups.

Synchron weil die Caller (concentration_service, sector_coverage_check.py)
in unterschiedlichen Kontexten laufen. FastAPI führt sync-Calls in
Threadpool aus, was bei einem Roundtrip kein Problem ist (im Gegensatz
zu N Roundtrips).
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import text

from services.analysis_config import SECTOR_OVERRIDES
from services.sector_mapping import INDUSTRY_TO_SECTOR, TRADINGVIEW_INDUSTRY_TO_SECTOR

logger = logging.getLogger(__name__)


def classify_tickers_bulk(
    tickers: Iterable[str],
    db_conn=None,
) -> dict[str, str | None]:
    """Klassifiziere viele Tickers in einem einzigen DB-Roundtrip.

    1. SECTOR_OVERRIDES (in-memory) — höchste Priorität, manuelle Korrekturen
    2. SELECT ticker, industry_name FROM ticker_industries WHERE ticker IN (...)
       → INDUSTRY_TO_SECTOR (in-memory) Mapping
    3. None ("Unclassified") für Rest

    Args:
        tickers: Liste/Iterable von Tickern, beliebig groß.
        db_conn: Optional. Wenn None, wird eine eigene Connection
            via sync_engine geöffnet — sonst die übergebene benutzt
            (für Tests / nested calls in Sweeps).

    Returns:
        dict mapping ticker (uppercase) → sector_name | None.
        Tickers ohne Klassifikation sind explizit None (nicht missing).
    """
    upper_tickers = [t.upper() for t in tickers if t]
    if not upper_tickers:
        return {}

    # Initialisiere alle als None (Default-Fallback).
    result: dict[str, str | None] = {t: None for t in upper_tickers}

    # 1. SECTOR_OVERRIDES (in-memory, kein DB-Hit)
    for t in upper_tickers:
        if t in SECTOR_OVERRIDES:
            result[t] = SECTOR_OVERRIDES[t]

    # 2. ticker_industries-Lookup für alle, die noch None sind
    needs_db_lookup = [t for t in upper_tickers if result[t] is None]
    if not needs_db_lookup:
        return result

    own_conn = False
    if db_conn is None:
        from db import sync_engine
        db_conn = sync_engine.connect()
        own_conn = True

    try:
        rows = db_conn.execute(
            text("SELECT ticker, industry_name FROM ticker_industries WHERE ticker IN :tickers"),
            {"tickers": tuple(needs_db_lookup)},
        ).all()
        for ticker, industry_name in rows:
            if industry_name is None:
                continue
            # ticker_industries.industry_name ist TradingView-Klassifikation,
            # nicht Finviz. Erst TRADINGVIEW_INDUSTRY_TO_SECTOR probieren,
            # dann fallback auf INDUSTRY_TO_SECTOR (Finviz-Style) für Edge-
            # Cases wo manuelles Pflegen mit Finviz-Strings vorkommt.
            sector = (
                TRADINGVIEW_INDUSTRY_TO_SECTOR.get(industry_name)
                or INDUSTRY_TO_SECTOR.get(industry_name)
            )
            if sector is not None:
                result[ticker] = sector
            # Wenn Industry in keinem Mapping → bleibt None
    except Exception as e:
        logger.warning(f"classify_tickers_bulk DB-lookup failed: {e}")
    finally:
        if own_conn:
            db_conn.close()

    return result


def classify_ticker_sector(ticker: str, db_conn=None) -> str | None:
    """Single-Ticker-Wrapper um classify_tickers_bulk.

    Convenience für callers die nur einen Ticker klassifizieren.
    Performance: identisch zu Bulk mit 1-Element-Liste — eine SQL-Query.
    """
    return classify_tickers_bulk([ticker], db_conn).get(ticker.upper())
