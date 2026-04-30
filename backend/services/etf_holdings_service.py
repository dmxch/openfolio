"""ETF-Holdings-Refresh via FMP für Core-Overlap-Flag (Phase B).

Phase 1 deckt nur US-ETFs ab — FMP `/api/v3/etf-holder/{ticker}` hat
zuverlässige Coverage für US-Listings. Non-US-ETFs (`.SW`, `.L`, `.TO`,
generell ticker mit Punkt) werden mit Log-Info geskipped.

Refresh-Cadence: wöchentlich (Mo 04:30 CET, siehe worker.py). Idempotent
durch TTL-Check pro ETF — wenn letzter Pull < 30 Tage zurückliegt, wird
der ETF übersprungen. So verzeiht der Job einzelne Cron-Failures, ohne
unnötig FMP-Calls zu machen.

FMP-Key kommt aus user_settings (verschlüsselt). Phase 1: nimm den ersten
User mit fmp_api_key — pragmatisch für Single-User-System. Multi-User-
Iteration wäre überengineered, da ETF-Holdings global sind.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dateutils import utcnow
from models.etf_holding import EtfHolding
from models.position import Position
from services import cache
from services.analysis_config import CORE_OVERLAP_HOLDINGS_TTL_DAYS
from services.api_utils import fetch_json

logger = logging.getLogger(__name__)


_FMP_BASE = "https://financialmodelingprep.com/stable"


def is_us_etf(ticker: str) -> bool:
    """US-ETF-Detection: ticker enthält keinen Punkt.

    OEF, SPY, VOO, IVV → US. CHSPI.SW, SWDA.L, JPNA.L, SSV.TO → Non-US.
    Diese Heuristik ist FMP-konform: alle FMP-coverten ETFs haben
    Suffix-freie Ticker; Listings auf .SW/.L/.TO sind separate
    Wertpapiere, die FMP typischerweise nicht im Holdings-Endpoint hat.
    """
    return "." not in ticker


async def _get_any_user_fmp_key(db: AsyncSession) -> str | None:
    """Finde irgendeinen User mit einem konfigurierten FMP-Key.

    Phase 1 nutzt einen einzigen Key für alle ETF-Refreshes (ETF-Holdings
    sind globale Daten, nicht user-spezifisch). Multi-User-Iteration mit
    User-spezifischen Keys wäre überengineered.
    """
    from services.settings_service import get_user_api_key
    from models.user import User

    # Versuche alle User mit aktiven Positionen
    result = await db.execute(
        select(User.id).where(User.is_active.is_(True))
    )
    user_ids = [row[0] for row in result.all()]
    for uid in user_ids:
        try:
            key = await get_user_api_key(db, uid, "fmp_api_key")
            if key:
                return key
        except Exception as e:
            logger.debug(f"FMP-key lookup for user {uid} failed: {e}")
    return None


async def _get_distinct_active_etf_tickers(db: AsyncSession) -> list[str]:
    """Pulle alle distinct ETF-Ticker aus aktiven User-Positionen."""
    result = await db.execute(
        select(Position.ticker)
        .where(Position.type == "etf", Position.is_active.is_(True))
        .distinct()
    )
    return [row[0] for row in result.all() if row[0]]


def _parse_fmp_holding(row: dict) -> dict | None:
    """Normalisiere ein FMP-Holding-Row.

    FMP-Schema (typisch):
      {
        "asset": "NVDA",
        "name": "NVIDIA Corporation",
        "weightPercentage": 7.5,
        "sharesNumber": 12345678,
        "marketValue": 1234567890,
        "updated": "2026-02-28"  # optional, je nach FMP-Tier
      }
    """
    asset = row.get("asset") or row.get("symbol")
    if not asset:
        return None
    weight = row.get("weightPercentage")
    if weight is None or weight == 0:
        return None

    as_of_str = row.get("updated") or row.get("date")
    as_of_date: date | None = None
    if as_of_str:
        try:
            as_of_date = datetime.strptime(as_of_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            as_of_date = None

    return {
        "asset": str(asset).upper().strip(),
        "name": (row.get("name") or "")[:200],
        "weight_pct": float(weight),
        "as_of": as_of_date,
    }


async def refresh_etf_holdings(
    db: AsyncSession, etf_ticker: str, api_key: str,
) -> dict:
    """Refresh die Holdings eines einzelnen ETFs aus FMP.

    Skip wenn nicht-US (Log-Info, kein Error). Skip wenn der letzte Pull
    < CORE_OVERLAP_HOLDINGS_TTL_DAYS zurückliegt (idempotent für den
    wöchentlichen Cron). UPSERT pro Holding-Row.
    """
    if not is_us_etf(etf_ticker):
        logger.info("etf_holdings_refresh: skip non-US ETF %s", etf_ticker)
        return {"etf_ticker": etf_ticker, "skipped": True, "reason": "non_us_etf"}

    # TTL-Check: wann wurde dieser ETF zuletzt aktualisiert?
    cutoff = utcnow() - timedelta(days=CORE_OVERLAP_HOLDINGS_TTL_DAYS)
    last_updated = (
        await db.execute(
            select(EtfHolding.updated_at)
            .where(EtfHolding.etf_ticker == etf_ticker)
            .order_by(EtfHolding.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_updated is not None and last_updated > cutoff:
        logger.info(
            "etf_holdings_refresh: skip %s (still fresh, updated_at=%s)",
            etf_ticker, last_updated,
        )
        return {"etf_ticker": etf_ticker, "skipped": True, "reason": "still_fresh"}

    # FMP-Call (Stable-API — funktioniert in den OpenFolio-User-Tiers, der
    # v3 /etf-holder Endpoint gibt 403 zurück. Stable nutzt symbol als Param
    # statt Path-Variable.)
    url = f"{_FMP_BASE}/etf/holdings"
    params = {"symbol": etf_ticker, "apikey": api_key}
    try:
        data = await fetch_json(url, params=params, timeout=15)
    except Exception as e:
        logger.warning("etf_holdings_refresh: FMP-call failed for %s: %s", etf_ticker, e)
        return {"etf_ticker": etf_ticker, "error": "fmp_call_failed"}

    if not isinstance(data, list) or not data:
        logger.warning("etf_holdings_refresh: empty response for %s", etf_ticker)
        return {"etf_ticker": etf_ticker, "error": "empty_response"}

    # Parse + dedup (FMP gibt Cash-Buckets mit asset == etf_ticker zurück,
    # mehrfach unter gleichem Composite-PK — die filtern wir raus, plus
    # Dedup-Map gegen weitere Duplikat-Möglichkeiten).
    now = utcnow()
    rows_map: dict[tuple[str, str], dict] = {}
    for raw in data:
        if not isinstance(raw, dict):
            continue
        parsed = _parse_fmp_holding(raw)
        if parsed is None:
            continue
        # Self-Reference (Cash-Buckets) skippen — keine echten Holdings
        if parsed["asset"] == etf_ticker:
            continue
        key = (etf_ticker, parsed["asset"])
        # Last-wins falls FMP-Quirk dieselbe Position mehrfach liefert
        rows_map[key] = {
            "etf_ticker": etf_ticker,
            "holding_ticker": parsed["asset"],
            "holding_name": parsed["name"],
            "weight_pct": parsed["weight_pct"],
            "as_of": parsed["as_of"],
            "updated_at": now,
        }
    rows = list(rows_map.values())

    if not rows:
        return {"etf_ticker": etf_ticker, "error": "no_parseable_rows"}

    # UPSERT in chunks (FMP gibt typisch 100-500 Holdings, eine SQL reicht)
    stmt = pg_insert(EtfHolding).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["etf_ticker", "holding_ticker"],
        set_={
            "holding_name": stmt.excluded.holding_name,
            "weight_pct": stmt.excluded.weight_pct,
            "as_of": stmt.excluded.as_of,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await db.execute(stmt)
    await db.commit()

    # Cache-Invalidation: Score-Caches die overlap-Daten enthalten könnten
    # werden bei nächstem score-Aufruf neu berechnet. Kein expliziter Pattern-
    # Delete nötig, weil Score-Endpoint overlap immer frisch joined.

    logger.info(
        "etf_holdings_refresh: %s persisted %d holdings (as_of=%s)",
        etf_ticker, len(rows), rows[0]["as_of"] if rows else None,
    )
    return {
        "etf_ticker": etf_ticker,
        "count": len(rows),
        "as_of": rows[0]["as_of"].isoformat() if rows[0].get("as_of") else None,
    }


async def refresh_all_user_etfs(db: AsyncSession) -> dict:
    """Refresh alle aktiven User-ETFs in einem Durchgang.

    Robust: per-ETF-Failures werden geloggt, andere ETFs laufen weiter.
    Wenn kein User einen FMP-Key konfiguriert hat, abort früh.
    """
    api_key = await _get_any_user_fmp_key(db)
    if not api_key:
        logger.warning("etf_holdings_refresh: no FMP key configured — skipping all")
        return {"error": "no_fmp_key", "refreshed": [], "skipped": []}

    etfs = await _get_distinct_active_etf_tickers(db)
    if not etfs:
        return {"refreshed": [], "skipped": [], "etf_count": 0}

    refreshed: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for etf_ticker in etfs:
        try:
            result = await refresh_etf_holdings(db, etf_ticker, api_key)
            if result.get("skipped"):
                skipped.append(result)
            elif result.get("error"):
                errors.append(result)
            else:
                refreshed.append(result)
        except Exception as e:
            logger.exception("etf_holdings_refresh: unexpected error for %s", etf_ticker)
            errors.append({"etf_ticker": etf_ticker, "error": str(e)})

    return {
        "refreshed": refreshed,
        "skipped": skipped,
        "errors": errors,
        "etf_count": len(etfs),
    }
