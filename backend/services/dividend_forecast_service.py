"""Dividenden-Forecast: projiziertes Einkommen der naechsten 12 Monate.

Run-Rate pro AKTUELL gehaltener Position: Trailing-12M-Dividende-pro-Aktie
(yfinance via ``dividend_service.fetch_dividends``) x current shares x FX.
BEWUSST NICHT aus dem Ledger gerechnet — der ist nach vorn kontaminiert
(verkaufte Zahler noch drin, neu gekaufte fehlen, Stueckzahl-Aenderungen).

Worker-populiert + Redis-gecacht: ``compute_dividend_forecast`` laeuft im
gedrosselten Worker (taeglich, an die Dividenden-Detection angehaengt) und
schreibt das Ergebnis in den Cache; ``get_dividend_forecast`` (API-Pfad) liest
NUR den Cache — kein yfinance pro Request (sonst Burst-429, siehe
``feedback_yfinance_burst_429``). Ehrliche Run-Rate: keine Wachstums-/Erhoehungs-
Annahme, keine Forward-Schaetzung; "was die letzten 12 Monate gezahlt haetten,
auf die heutige Position angewandt".
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position
from services import cache
from services.dividend_service import fetch_dividends

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "dividend_forecast:"
_CACHE_TTL = 90_000   # ~25 h: ueberlebt bis zum naechsten taeglichen Worker-Lauf
_WINDOW_DAYS = 365
_CONCURRENCY = 3      # gedrosselt wie die Dividenden-Detection (yfinance-Schonung)


def _cache_key(user_id: uuid.UUID) -> str:
    return f"{_CACHE_PREFIX}{user_id}"


def _empty() -> dict:
    return {
        "has_data": False,
        "forecast_12m_chf": 0.0,
        "as_of": None,
        "eligible_count": 0,
        "payer_count": 0,
        "by_holding": [],
    }


async def get_dividend_forecast(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """API-Pfad: liefert ausschliesslich den vom Worker befuellten Cache.

    Kein yfinance hier — ist der Cache leer (noch nie berechnet), kommt
    ``has_data=False`` zurueck (die UI zeigt einen Hinweis auf den naechsten Lauf).
    """
    cached = cache.get(_cache_key(user_id))
    if isinstance(cached, dict) and cached.get("has_data"):
        return cached
    return _empty()


async def compute_dividend_forecast(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Worker-Pfad: rechnet die Forward-Run-Rate pro aktueller Position, gedrosselt,
    und cached das Ergebnis. Best-effort pro Holding (ein Fetch-Fehler -> 0 fuer
    dieses Holding, kippt nicht den ganzen Forecast)."""
    rows = (await db.execute(
        select(
            Position.ticker, Position.yfinance_ticker, Position.currency,
            Position.shares, Position.name,
        ).where(
            Position.user_id == user_id,
            Position.is_active.is_(True),
            Position.type.in_([AssetType.stock, AssetType.etf]),
            Position.shares > 0,
            Position.count_as_cash.is_(False),
        )
    )).all()

    if not rows:
        result = _empty()
        result["has_data"] = True
        result["as_of"] = date.today().isoformat()
        cache.set(_cache_key(user_id), result, ttl=_CACHE_TTL)
        return result

    since = date.today() - timedelta(days=_WINDOW_DAYS)
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _one(r) -> dict:
        tkr = r.yfinance_ticker or r.ticker
        shares = float(r.shares)
        try:
            async with sem:
                events = await asyncio.to_thread(
                    fetch_dividends, tkr, since, shares, r.currency or "USD"
                )
        except Exception as e:  # best-effort pro Holding
            logger.warning("dividend_forecast_fetch_failed ticker=%s error=%s", tkr, e)
            events = []
        total = round(sum(float(e["total_chf"]) for e in events), 2)
        dps = round(sum(float(e["dividend_per_share"]) for e in events), 4)
        return {
            "ticker": r.ticker,
            "name": r.name,
            "forecast_chf": total,
            "dps_12m": dps,
            "payments": len(events),
        }

    holdings = await asyncio.gather(*[_one(r) for r in rows])
    payers = sorted(
        [h for h in holdings if h["forecast_chf"] > 0],
        key=lambda h: -h["forecast_chf"],
    )
    result = {
        "has_data": True,
        "forecast_12m_chf": round(sum(h["forecast_chf"] for h in payers), 2),
        "as_of": date.today().isoformat(),
        "eligible_count": len(rows),
        "payer_count": len(payers),
        "by_holding": payers,
    }
    cache.set(_cache_key(user_id), result, ttl=_CACHE_TTL)
    return result


async def refresh_dividend_forecasts(db: AsyncSession) -> dict:
    """Worker-Entry-Point: rechnet den Forecast fuer alle User mit aktiven
    stock/etf-Holdings (an die taegliche Dividenden-Detection angehaengt)."""
    user_ids = [row[0] for row in (await db.execute(
        select(Position.user_id).where(
            Position.is_active.is_(True),
            Position.type.in_([AssetType.stock, AssetType.etf]),
            Position.shares > 0,
        ).distinct()
    )).all()]

    ok = 0
    for uid in user_ids:
        try:
            await compute_dividend_forecast(db, uid)
            ok += 1
        except Exception:
            logger.exception("dividend_forecast_user_failed user=%s", uid)
            # Session nach einem (transienten) DB-Fehler bereinigen — sonst bleibt
            # sie im failed-transaction-state und ALLE Folge-User werfen
            # PendingRollbackError (gleiches Muster wie worker.py M8-Review).
            try:
                await db.rollback()
            except Exception:
                logger.exception("dividend_forecast_rollback_failed user=%s", uid)
    logger.info("dividend_forecast_refresh users=%s ok=%s", len(user_ids), ok)
    return {"users": len(user_ids), "ok": ok}
