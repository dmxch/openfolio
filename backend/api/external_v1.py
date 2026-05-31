"""External REST API — versioned, X-API-Key authenticated.

Alle Endpoints unter ``/api/v1/external/*`` sprechen denselben Service-Layer
wie das interne UI an, exponieren aber einen **stabilen Vertrag** (Whitelist-
Filter in ``external_v1_schemas.py``).

Wichtige Vertragsentscheidungen (v0.38+):

- PII gehört dem Token-Besitzer und wird ausgeliefert (bank_name, address,
  notes, mortgage.bank, income.tenant).  Einzige Ausnahme: **IBAN ist immer
  maskiert** über ``decrypt_and_mask_iban`` — identisch zum internen UI.
- Schreib-Endpoints sind hinter ``require_scope(request, "write")`` und
  hinterlassen einen ``ApiWriteLog``-Eintrag.
- HEILIGE Performance-Berechnungen werden nur read-only aufgerufen, nie
  modifiziert.
"""

import asyncio
import datetime
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from api.external_v1_schemas import (
    ExternalAlertCreate,
    ExternalAlertUpdate,
    ExternalNotesUpdate,
    ExternalPendingOrderCreate,
    ExternalPendingOrderFill,
    ExternalPendingOrderUpdate,
    ExternalStopLossBatchRequest,
    ExternalStopLossUpdate,
    ExternalWatchlistAdd,
    NOTES_MAX_LEN,
    ReportPatch,
    ReportPrune,
    ReportUpload,
    STOP_LOSS_BATCH_MAX_ITEMS,
    filter_pension_position,
    filter_position,
    filter_property,
    filter_settings,
)
from constants.limits import (
    MAX_PENDING_ORDERS_PER_USER,
    MAX_REPORTS_PER_USER,
    MAX_TAGS_PER_REPORT,
    MAX_WATCHLIST_PER_USER,
)
from auth import get_api_user, require_scope
from dateutils import utcnow
from db import get_db
from models.api_write_log import ApiWriteLog
from models.pending_order import PendingOrder
from models.position import AssetType, Position
from models.report import Report
from models.price_alert import PriceAlert
from models.screening import ScreeningResult, ScreeningScan
from models.transaction import Transaction, TransactionType
from models.user import User
from models.watchlist import WatchlistItem
from services import cache
from services.encryption_helpers import (
    decrypt_and_mask_iban,
    decrypt_field,
    encrypt_field,
)
from services.ch_macro_service import get_ch_macro_snapshot
from services.sector_analyzer import get_sector_rotation
from services.correlation_service import compute_correlation_matrix
from services.earnings_service import get_upcoming_earnings_for_portfolio
from services.portfolio_service import get_portfolio_summary
from services.property_service import get_properties_summary, get_property_detail
from services.tradingview_industries_service import (
    get_latest_industries,
    fetch_industry_members,
    get_industry_name_for_slug,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/external", tags=["external"])

# Stricter rate-limit than internal API — external consumers should cache.
RATE_LIMIT = "30/minute"


async def _enrich_positions_with_pii(
    db: AsyncSession, user_id: uuid.UUID, positions: list[dict]
) -> None:
    """In-place: ergänzt jede Position um bank_name (decrypt), iban (mask),
    notes (decrypt), active_alerts und change_pct_24h.

    Spiegel der internen Anreicherung in ``api/portfolio.py`` (Zeilen 40-71).
    Wird vom externen UI-Mirror genutzt, damit der API-Konsument denselben
    Datenstand sieht wie der eingeloggte User im Browser.  Idempotent: ohne
    Positionen ist es ein No-Op.
    """
    if not positions:
        return
    # IDs aus dem Service-Dict sind Strings — explizit zu UUID konvertieren,
    # weil ``Position.id`` (UUID-Spalte) sonst beim Compile auf ``.hex`` zugreift.
    pos_ids = []
    for p in positions:
        pid = p["id"]
        if isinstance(pid, uuid.UUID):
            pos_ids.append(pid)
        else:
            try:
                pos_ids.append(uuid.UUID(pid))
            except (ValueError, AttributeError):
                # Sollte nicht vorkommen, aber defensiv: ungültige ID überspringen
                continue
    if not pos_ids:
        return
    rows = await db.execute(
        select(
            Position.id, Position.bank_name, Position.iban, Position.notes,
            Position.coingecko_id, Position.yfinance_ticker, Position.ticker,
        ).where(Position.id.in_(pos_ids))
    )
    extra = {str(r.id): r for r in rows}

    alert_rows = await db.execute(
        select(PriceAlert.ticker, func.count())
        .where(PriceAlert.user_id == user_id, PriceAlert.is_active == True)
        .group_by(PriceAlert.ticker)
    )
    alerts_by_ticker = {row[0]: row[1] for row in alert_rows.all()}

    for p in positions:
        e = extra.get(p["id"])
        if not e:
            continue
        p["bank_name"] = decrypt_field(e.bank_name)
        p["iban"] = decrypt_and_mask_iban(e.iban)
        p["notes"] = decrypt_field(e.notes)
        p["active_alerts"] = alerts_by_ticker.get(p["ticker"], 0)
        if e.coingecko_id:
            crypto_data = cache.get(f"crypto:{e.coingecko_id}")
            p["change_pct_24h"] = crypto_data.get("change_pct") if crypto_data else None
        else:
            yf_ticker = e.yfinance_ticker or e.ticker
            price_data = cache.get(f"price:{yf_ticker}")
            p["change_pct_24h"] = price_data.get("change_pct") if price_data else None


def _filter_summary(summary: dict) -> dict:
    """Whitelist-Filter über das Summary-Dict — PII bleibt drin (per Whitelist),
    IBAN ist bereits via ``_enrich_positions_with_pii`` maskiert."""
    return {
        "total_invested_chf": summary.get("total_invested_chf"),
        "total_market_value_chf": summary.get("total_market_value_chf"),
        "total_pnl_chf": summary.get("total_pnl_chf"),
        "total_pnl_pct": summary.get("total_pnl_pct"),
        "total_fees_chf": summary.get("total_fees_chf"),
        "positions": [filter_position(p) for p in summary.get("positions", [])],
        "allocations": summary.get("allocations", {}),
        "fx_rates": summary.get("fx_rates"),
    }


# --- Health (no auth) ---

@router.get("/health")
async def external_health() -> dict:
    """Liveness probe — no authentication required."""
    return {"status": "ok", "api_version": "v1"}


# --- Portfolio ---

@router.get("/portfolio/summary")
@limiter.limit(RATE_LIMIT)
async def portfolio_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Portfolio summary inkl. PII des Token-Eigentümers (IBAN maskiert)."""
    summary = await get_portfolio_summary(db, user.id)
    await _enrich_positions_with_pii(db, user.id, summary.get("positions") or [])
    return _filter_summary(summary)


@router.get("/portfolio/upcoming-earnings")
@limiter.limit(RATE_LIMIT)
async def upcoming_earnings(
    request: Request,
    days: int = Query(default=7, ge=1, le=60),
    include_etfs: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Naechste Earnings-Termine fuer alle aktiven Stock/ETF-Positionen.

    Quelle: Finnhub (primaer) mit yfinance-Fallback. Response-Cache 12h.
    """
    cache_key = (
        f"external:upcoming_earnings:{user.id}:{days}:{int(include_etfs)}:v1"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = await get_upcoming_earnings_for_portfolio(
            db, user.id, days=days, include_etfs=include_etfs,
        )
    except Exception:
        logger.exception("upcoming-earnings failed")
        raise HTTPException(status_code=503, detail="upcoming_earnings_unavailable")
    cache.set(cache_key, data, ttl=43200)  # 12h
    return data


@router.get("/positions")
@limiter.limit(RATE_LIMIT)
async def list_positions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Alle Positionen des Users — angereichert mit Bank/IBAN/Notes/Stop-Loss."""
    summary = await get_portfolio_summary(db, user.id)
    positions = summary.get("positions") or []
    await _enrich_positions_with_pii(db, user.id, positions)
    return {"positions": [filter_position(p) for p in positions]}


# Wichtig: Statische Pfade unter ``/positions/...`` MÜSSEN vor der parameter-
# isierten ``/positions/{ticker}``-Route registriert sein. Starlette evaluiert
# Routen in Registrierungsreihenfolge — sonst matcht ``/positions/without-type``
# das ticker-Pattern und landet im 404-Pfad (siehe Audit v0.38.0 Finding #1).


# Phase 3 (v0.40): /positions/without-type entfernt. Alle Positionen sind
# einem Bucket zugeordnet (positions.bucket_id NOT NULL seit Migration 064).
# Drittparteien koennen via GET /buckets + GET /positions die Bucket-
# Zuordnung jeder Position einsehen.


@router.get("/positions/{ticker}")
@limiter.limit(RATE_LIMIT)
async def get_position(
    request: Request,
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Einzelne Position nach Ticker."""
    summary = await get_portfolio_summary(db, user.id)
    positions = summary.get("positions") or []
    await _enrich_positions_with_pii(db, user.id, positions)
    upper = ticker.upper()
    for p in positions:
        if (p.get("ticker") or "").upper() == upper:
            return filter_position(p)
    raise HTTPException(status_code=404, detail="Position nicht gefunden")


# --- Performance ---

@router.get("/performance/history")
@limiter.limit(RATE_LIMIT)
async def performance_history(
    request: Request,
    period: str = Query(default="1y", pattern="^(1m|3m|ytd|1y|all)$"),
    benchmark: str = Query(default="^GSPC", pattern=r"^[\^A-Z0-9.\-=]{1,20}$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Portfolio history snapshots over the requested period."""
    from services.history_service import get_portfolio_history

    today = datetime.date.today()
    if period == "1m":
        start = today - datetime.timedelta(days=30)
    elif period == "3m":
        start = today - datetime.timedelta(days=90)
    elif period == "ytd":
        start = datetime.date(today.year, 1, 1)
    elif period == "1y":
        start = today - datetime.timedelta(days=365)
    else:  # all
        start = datetime.date(2000, 1, 1)

    return await get_portfolio_history(db, start, today, benchmark, user_id=user.id)


@router.get("/performance/monthly-returns")
@limiter.limit(RATE_LIMIT)
async def performance_monthly_returns(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Modified-Dietz monthly returns."""
    from services.performance_history_service import get_monthly_returns
    return await get_monthly_returns(db, user_id=user.id)


@router.get("/performance/total-return")
@limiter.limit(RATE_LIMIT)
async def performance_total_return(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Total return (XIRR-based)."""
    from services.total_return_service import get_total_return
    return await get_total_return(db, user_id=user.id)


@router.get("/performance/drawdown")
@limiter.limit(RATE_LIMIT)
async def performance_drawdown(
    request: Request,
    period: str = Query(default="ytd", pattern="^(ytd|1m|3m|6m|1y|all)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Peak-to-Trough Max-Drawdown ueber die Periode + Drawdown-Bremse-Flag (>= 6%)."""
    from services.drawdown_service import get_max_drawdown
    return await get_max_drawdown(db, user.id, period=period)


@router.get("/performance/realized-gains")
@limiter.limit(RATE_LIMIT)
async def performance_realized_gains(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Realised gains from sell transactions."""
    from services.total_return_service import get_realized_gains
    return await get_realized_gains(db, user_id=user.id)


@router.get("/performance/daily-change")
@limiter.limit(RATE_LIMIT)
async def performance_daily_change(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Today's portfolio change."""
    from services.performance_service import calculate_daily_change
    return await calculate_daily_change(db, user.id)


# --- Analysis ---

@router.get("/analysis/score/{ticker}")
@limiter.limit(RATE_LIMIT)
async def analysis_score(
    request: Request,
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Setup score 0-10 for a ticker.

    Antwort enthält neben den Setup-Kriterien auch den `concentration`-Block
    (Single-Name + Sektor, v0.29.0) und `liquid_portfolio_chf` für Banner-
    Berechnung — analog zum internen Endpoint.
    """
    from services.scoring_service import assess_ticker

    upper = ticker.upper()
    manual_resistance = None
    sector = None
    # Fallback auch in der Watchlist suchen (analog zu /api/analysis/score)
    pos_result = await db.execute(
        select(Position.manual_resistance, Position.sector).where(
            (Position.ticker == upper) | (Position.yfinance_ticker == upper),
            Position.is_active == True,
            Position.user_id == user.id,
        ).limit(1)
    )
    row = pos_result.first()
    if row:
        if row[0] is not None:
            manual_resistance = float(row[0])
        sector = row[1]
    else:
        from models.watchlist import WatchlistItem
        wl_result = await db.execute(
            select(WatchlistItem.manual_resistance, WatchlistItem.sector).where(
                WatchlistItem.ticker == upper,
                WatchlistItem.is_active == True,
                WatchlistItem.user_id == user.id,
            ).limit(1)
        )
        wl_row = wl_result.first()
        if wl_row:
            if wl_row[0] is not None:
                manual_resistance = float(wl_row[0])
            sector = wl_row[1]

    try:
        result = await asyncio.to_thread(
            assess_ticker, upper, sector=sector, manual_resistance=manual_resistance
        )
    except Exception as e:
        logger.warning(f"External score failed for {ticker}: {e}")
        raise HTTPException(status_code=400, detail="Score-Berechnung fehlgeschlagen")

    if result.get("max_score", 0) == 0 and result.get("price") is None:
        raise HTTPException(status_code=404, detail="Ticker nicht gefunden")

    # Phase 1.1: Konzentrations-Block + Liquid-Portfolio-Total für Banner.
    # Defensiv — bei Fehler liefert der Endpoint trotzdem den Score.
    try:
        from services.concentration_service import get_concentration_for_ticker

        concentration = await get_concentration_for_ticker(db, upper, user.id)
        result["concentration"] = concentration
        portfolio = await get_portfolio_summary(db, user.id)
        result["liquid_portfolio_chf"] = portfolio.get("total_market_value_chf")
    except Exception as e:
        logger.debug(f"External concentration computation failed for {upper}: {e}")
        result["concentration"] = {
            "single_name": {"overlaps": [], "direct_position_chf": None,
                            "total_indirect_chf": 0.0, "total_chf": 0.0, "total_pct": None},
            "sector": {"status": "no_sector"},
            "portfolio": {
                "hhi": None, "effective_n": None, "nominal_count": 0,
                "max_weight_ticker": None, "max_weight_name": None,
                "max_weight_pct": 0.0, "classification": "unknown",
            },
        }
        result.setdefault("liquid_portfolio_chf", None)

    return result


@router.get("/analysis/heartbeat/{ticker}")
@limiter.limit(RATE_LIMIT)
async def analysis_heartbeat(
    request: Request,
    ticker: str,
    _user: User = Depends(get_api_user),
) -> dict:
    """Heartbeat-Pattern-Detektion mit Wyckoff-Volumen-Sub-Layer (v0.29.1).

    Liefert das ATR-Compression-basierte Heartbeat-Resultat plus den
    `wyckoff`-Sub-Block (volume-slope-Klassifikation, Spring-Sub-Tag).
    Keine User-spezifischen Daten — derselbe Cache wie der interne Endpoint.
    """
    from services.chart_service import get_heartbeat_pattern
    upper = ticker.upper()
    result = await asyncio.to_thread(get_heartbeat_pattern, upper)
    return {"ticker": upper, **result}


@router.get("/analysis/breakouts/{ticker}")
@limiter.limit(RATE_LIMIT)
async def analysis_breakouts(
    request: Request,
    ticker: str,
    period: str = Query(default="1y", pattern=r"^(3m|6m|1y|2y)$"),
    _user: User = Depends(get_api_user),
) -> dict:
    """Donchian-20d Breakout/Breakdown-Events über den gewählten Zeitraum."""
    from services.chart_service import get_breakout_events
    upper = ticker.upper()
    breakouts = await asyncio.to_thread(get_breakout_events, upper, period)
    return {"ticker": upper, "breakouts": breakouts}


@router.get("/analysis/mrs/{ticker}")
@limiter.limit(RATE_LIMIT)
async def analysis_mrs(
    request: Request,
    ticker: str,
    period: str = Query(default="1y", pattern=r"^(3m|6m|1y|2y)$"),
    user: User = Depends(get_api_user),
) -> dict:
    """Weekly MRS (Mansfield Relative Strength) history."""
    from services.chart_service import get_mrs_history
    data = await asyncio.to_thread(get_mrs_history, ticker.upper(), period)
    return {"ticker": ticker.upper(), "data": data}


@router.get("/analysis/levels/{ticker}")
@limiter.limit(RATE_LIMIT)
async def analysis_levels(
    request: Request,
    ticker: str,
    user: User = Depends(get_api_user),
) -> dict:
    """Support and resistance levels for a ticker."""
    from services.chart_service import get_support_resistance_levels
    return await asyncio.to_thread(get_support_resistance_levels, ticker.upper())


@router.get("/analysis/reversal/{ticker}")
@limiter.limit(RATE_LIMIT)
async def analysis_reversal(
    request: Request,
    ticker: str,
    user: User = Depends(get_api_user),
) -> dict:
    """3-point reversal detection."""
    from services.chart_service import get_three_point_reversal
    result = await asyncio.to_thread(get_three_point_reversal, ticker.upper())
    return {"ticker": ticker.upper(), **result}


@router.get("/analysis/correlation-matrix")
@limiter.limit(RATE_LIMIT)
async def analysis_correlation_matrix(
    request: Request,
    period: str = Query(default="90d", pattern="^(30d|90d|180d|1y)$"),
    include_cash: bool = Query(default=False),
    include_pension: bool = Query(default=False),
    include_commodity: bool = Query(default=True),
    include_crypto: bool = Query(default=True),
    bucket_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Paarweise Korrelations-Matrix aktiver Positionen plus HHI-Konzentration.

    bucket_id (optional, v0.39): filtert die Matrix auf Positionen eines Buckets.

    Cached fuer 24h pro (user, period, flag-combo). In der Korrelations-Matrix
    selbst sind `real_estate` und `private_equity` ausgeschlossen (keine
    handelbaren Zeitreihen); im HHI werden sie mitgezaehlt, weil sie sehr wohl
    Konzentrationsrisiko bedeuten. Cash und Pension fallen aus dem HHI raus.
    """
    bucket_suffix = f":b{bucket_id}" if bucket_id else ""
    cache_key = (
        f"external:correlation:{user.id}:{period}"
        f":c{int(include_cash)}p{int(include_pension)}"
        f"m{int(include_commodity)}k{int(include_crypto)}:v2{bucket_suffix}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = await compute_correlation_matrix(
            db,
            user.id,
            period=period,
            include_cash=include_cash,
            include_pension=include_pension,
            include_commodity=include_commodity,
            include_crypto=include_crypto,
            bucket_id=bucket_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("correlation-matrix failed")
        raise HTTPException(status_code=503, detail="correlation_matrix_unavailable")
    cache.set(cache_key, data, ttl=86400)
    return data


# --- Buckets (v0.39, Read-Only) ---

@router.get("/buckets")
@limiter.limit(RATE_LIMIT)
async def list_buckets_external(
    request: Request,
    include_deleted: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Liste aller Buckets des Users (User + System).

    Liefert auch deleted_at fuer geloeschte Buckets falls include_deleted=true.
    """
    from services.bucket_service import list_buckets
    from api.external_v1_schemas import filter_bucket
    buckets = await list_buckets(db, user.id, include_deleted=include_deleted)
    items = []
    for b in buckets:
        items.append(filter_bucket({
            "id": str(b.id),
            "name": b.name,
            "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
            "system_role": b.system_role.value if b.system_role else None,
            "color": b.color,
            "benchmark": b.benchmark,
            "target_pct": float(b.target_pct) if b.target_pct is not None else None,
            "target_chf": float(b.target_chf) if b.target_chf is not None else None,
            "description": b.description,
            "sort_order": b.sort_order,
            "risk_rules": b.risk_rules,
            "deleted_at": b.deleted_at.isoformat() if b.deleted_at else None,
        }))
    return {"buckets": items, "count": len(items)}


@router.get("/buckets/allocations")
@limiter.limit(RATE_LIMIT)
async def buckets_allocations_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Live-Allokation pro Bucket (analog der internen UI). PE/Real-Estate excluded."""
    from services.bucket_performance_service import get_allocations_by_bucket
    items = await get_allocations_by_bucket(db, user.id)
    return {"items": items}


@router.get("/buckets/{bucket_id}/summary")
@limiter.limit(RATE_LIMIT)
async def bucket_summary_external(
    request: Request,
    bucket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Aktueller Markt-Wert + Cost-Basis + Unrealized PnL eines Buckets."""
    from services.bucket_performance_service import get_bucket_summary
    data = await get_bucket_summary(db, user.id, bucket_id)
    if not data:
        raise HTTPException(status_code=404, detail="Bucket nicht gefunden")
    return data


@router.get("/buckets/{bucket_id}/history")
@limiter.limit(RATE_LIMIT)
async def bucket_history_external(
    request: Request,
    bucket_id: uuid.UUID,
    period: str = Query(default="ytd", pattern="^(ytd|1m|3m|6m|1y|all)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Snapshot-Zeitreihe eines Buckets (date, total_value_chf, net_cash_flow_chf, running_peak_chf)."""
    from services.bucket_performance_service import get_bucket_history
    history = await get_bucket_history(db, user.id, bucket_id, period=period)
    return {"bucket_id": str(bucket_id), "period": period, "history": history}


@router.get("/buckets/{bucket_id}/drawdown")
@limiter.limit(RATE_LIMIT)
async def bucket_drawdown_external(
    request: Request,
    bucket_id: uuid.UUID,
    period: str = Query(default="ytd", pattern="^(ytd|1m|3m|6m|1y|all)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Drawdown des Buckets (peak-to-trough) inkl. drawdown_brake_active-Flag."""
    from services.bucket_service import get_bucket, BucketError
    from services.drawdown_service import get_max_drawdown
    try:
        bucket = await get_bucket(db, user.id, bucket_id)
    except BucketError as e:
        raise HTTPException(status_code=404, detail=str(e))
    threshold = None
    if bucket.risk_rules:
        threshold = bucket.risk_rules.get("drawdown_brake_pct")
    return await get_max_drawdown(
        db, user.id, period=period,
        bucket_id=bucket_id, brake_threshold_pct=threshold,
    )


@router.get("/buckets/{bucket_id}/benchmark-comparison")
@limiter.limit(RATE_LIMIT)
async def bucket_benchmark_comparison_external(
    request: Request,
    bucket_id: uuid.UUID,
    period: str = Query(default="ytd", pattern="^(ytd|1m|3m|6m|1y|all)$"),
    start: datetime.date | None = Query(default=None, description="Arbitraerer Fenster-Start (ISO YYYY-MM-DD), Praezedenz vor period."),
    end: datetime.date | None = Query(default=None, description="Arbitraeres Fenster-Ende (ISO YYYY-MM-DD), Praezedenz vor period."),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Bucket-Return vs konfigurierter Benchmark (cashflow-adjustierter TWR vs
    exakter Fenster-Return des Benchmarks, geklemmt ab Bucket-Inception,
    Re-Label-neutralisiert). Mit ``start``/``end`` wird ein arbitraeres Datums-
    Fenster gemessen (z.B. vergangenes Quartal), sonst die ``period``-Enums."""
    from services.bucket_performance_service import compare_to_benchmark
    try:
        data = await compare_to_benchmark(
            db, user.id, bucket_id,
            period=period, start_date=start, end_date=end,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not data:
        raise HTTPException(status_code=404, detail="Bucket nicht gefunden")
    return data


@router.get("/buckets/{bucket_id}/monthly-returns")
@limiter.limit(RATE_LIMIT)
async def bucket_monthly_returns_external(
    request: Request,
    bucket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Monatsrenditen + Jahres-Totale eines Buckets (analog /performance/monthly-returns)."""
    from services.bucket_performance_service import get_bucket_monthly_returns
    return await get_bucket_monthly_returns(db, user.id, bucket_id)


# --- Macro ---

@router.get("/macro/ch")
@limiter.limit(RATE_LIMIT)
async def macro_ch(
    request: Request,
    _user: User = Depends(get_api_user),
) -> dict:
    """Schweizer Makro-Snapshot (SNB, SARON, FX, CPI, 10Y, SMI-vs-SP500).

    Aggregiert in einem Call, 6h-Cache. Partial-Failure-tolerant:
    nicht erreichbare Quellen landen als Strings in `warnings[]`, der
    Endpoint liefert trotzdem 200.
    """
    cache_key = "external:macro:ch:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = await get_ch_macro_snapshot()
    except Exception:
        logger.exception("ch macro snapshot failed")
        raise HTTPException(status_code=503, detail="ch_macro_unavailable")
    cache.set(cache_key, data, ttl=21600)  # 6h
    return data


# --- Market / Sectors ---

@router.get("/market/sectors")
@limiter.limit(RATE_LIMIT)
async def market_sectors(
    request: Request,
    _user: User = Depends(get_api_user),
) -> list:
    """Sektor-Rotation der 11 SPDR-ETFs mit 1D/1W/1M/3M Performance und Trend.

    Keine User-spezifischen Daten. Cache via sector_analyzer (60s Worker-Refresh).
    """
    return await asyncio.to_thread(get_sector_rotation)


@router.get("/market/industries")
@limiter.limit(RATE_LIMIT)
async def market_industries(
    request: Request,
    period: str = Query(default="ytd", pattern="^(1w|1m|3m|6m|ytd|1y|5y|10y)$"),
    top: int | None = Query(default=None, ge=1, le=200),
    bottom: int | None = Query(default=None, ge=1, le=200),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    min_mcap: float | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_api_user),
) -> dict:
    """Branchen-Rotation der ~129 US-Industries von TradingView.

    Taeglicher DB-Snapshot (01:30 CET). Keine User-spezifischen Daten.
    Query-Parameter: `period` (1w/1m/3m/6m/ytd/1y/5y/10y), `top`, `bottom`,
    `order`, `min_mcap` (untere MCap-Schwelle in USD, z.B. 1_000_000_000 = $1B;
    null/fehlend = kein Filter). 24h-Cache fuer externe Konsumenten.
    """
    cache_key = (
        f"external:market:industries:{period}:t{top or 'all'}:b{bottom or 'none'}"
        f":{order}:m{min_mcap or 'none'}:v3"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = await get_latest_industries(
            db, period=period, top=top, bottom=bottom, order=order,
            min_mcap=min_mcap,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cache.set(cache_key, data, ttl=86400)
    return data


@router.get("/market/industries/{slug}/members")
@limiter.limit(RATE_LIMIT)
async def market_industry_members(
    request: Request,
    slug: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_api_user),
) -> dict:
    """Einzelaktien einer Branche (Drill-down), nach MCap absteigend.

    Live von der TradingView-Scanner-API, nach Branche gefiltert. Der `slug`
    wird gegen den letzten Branchen-Snapshot in einen Namen aufgeloest. Keine
    User-spezifischen Daten. 24h-Cache fuer externe Konsumenten.
    """
    cache_key = f"external:market:industry_members:{slug}:l{limit}:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    name = await get_industry_name_for_slug(db, slug)
    if not name:
        raise HTTPException(status_code=404, detail="industry_not_found")

    try:
        members = await fetch_industry_members(name, limit=limit)
    except Exception:
        logger.exception("external industry members fetch failed for %s", slug)
        raise HTTPException(status_code=502, detail="industry_members_unavailable")

    data = {"slug": slug, "name": name, "count": len(members), "members": members}
    cache.set(cache_key, data, ttl=86400)
    return data


# --- Screening ---

@router.get("/watchlist")
@limiter.limit(RATE_LIMIT)
async def get_watchlist(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Watchlist des Users mit Preisen, Tags und Alert-Counts.

    Notes und die ``notes_last_api_*``-Marker werden immer ausgeliefert — der
    Marker ist Provenienz-Information (manuell vs. via-API geschrieben), die
    der ``/watchlist``-Skill für Sync-Decisions braucht.  Schreiben weiterhin
    nur mit ``write``-Scope.
    """
    from services.watchlist_service import get_watchlist_data
    return await get_watchlist_data(db, user.id)


@router.post("/watchlist", status_code=201)
@limiter.limit(RATE_LIMIT)
async def add_to_watchlist_external(
    request: Request,
    data: ExternalWatchlistAdd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Neuen Ticker zur Watchlist hinzufuegen. Erfordert Scope ``write``.

    Der Ticker wird auf Uppercase normalisiert. Doppelte Eintraege (gleicher
    User + gleicher Ticker) werden mit 409 abgelehnt — der UniqueConstraint
    `uq_watchlist_user_ticker` verhindert sie ohnehin auf DB-Ebene.
    Limit pro User: ``MAX_WATCHLIST_PER_USER`` (siehe ``constants/limits.py``).
    """
    require_scope(request, "write")

    ticker_norm = data.ticker.strip().upper()

    count_result = await db.execute(
        select(func.count()).select_from(WatchlistItem).where(
            WatchlistItem.user_id == user.id, WatchlistItem.is_active == True
        )
    )
    if (count_result.scalar() or 0) >= MAX_WATCHLIST_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Watchlist-Limit erreicht (max. {MAX_WATCHLIST_PER_USER} Eintraege)",
        )

    existing = await db.execute(
        select(WatchlistItem.id).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.ticker == ticker_norm,
        ).limit(1)
    )
    if existing.scalar() is not None:
        raise HTTPException(status_code=409, detail="Ticker ist bereits in der Watchlist")

    item = WatchlistItem(
        id=uuid.uuid4(),
        user_id=user.id,
        ticker=ticker_norm,
        name=data.name,
        sector=data.sector,
    )
    db.add(item)

    token = getattr(request.state, "api_token", None)
    db.add(ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker=ticker_norm,
        action="watchlist_add",
        target_id=item.id,
    ))

    await db.commit()
    await db.refresh(item)
    return {
        "id": str(item.id),
        "ticker": item.ticker,
        "name": item.name,
        "sector": item.sector,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.delete("/watchlist/{ticker}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def remove_from_watchlist_external(
    request: Request,
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> None:
    """Ticker aus der Watchlist entfernen. Erfordert Scope ``write``.

    Cascade-Verhalten ist identisch zum internen UI-Endpoint: Preis-Alarme
    auf demselben Ticker werden nur dann mit-geloescht, wenn der User
    keine aktive Position auf dem Ticker haelt — Stop-Loss-Alarme auf
    Portfolio-Tickers ueberleben das Entfernen aus der Watchlist.
    """
    require_scope(request, "write")

    ticker_norm = (ticker or "").strip().upper()
    if not ticker_norm:
        raise HTTPException(status_code=404, detail="Ticker nicht in Watchlist gefunden")

    result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.ticker == ticker_norm,
        )
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Ticker nicht in Watchlist gefunden")

    item_id_snapshot = item.id
    await db.delete(item)

    # Cascade: drop price alerts only when there's no active position for this ticker.
    position_q = await db.execute(
        select(Position.id).where(
            Position.user_id == user.id,
            Position.ticker == ticker_norm,
            Position.is_active == True,
            Position.shares > 0,
        ).limit(1)
    )
    if position_q.scalar() is None:
        alerts = await db.execute(
            select(PriceAlert).where(
                PriceAlert.user_id == user.id,
                PriceAlert.ticker == ticker_norm,
            )
        )
        for alert in alerts.scalars().all():
            await db.delete(alert)

    token = getattr(request.state, "api_token", None)
    db.add(ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker=ticker_norm,
        action="watchlist_remove",
        target_id=item_id_snapshot,
    ))

    await db.commit()


@router.patch("/watchlist/{ticker}/notes")
@limiter.limit(RATE_LIMIT)
async def update_watchlist_notes(
    request: Request,
    ticker: str,
    data: ExternalNotesUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Notiz eines Watchlist-Eintrags setzen oder anhaengen.

    Erfordert Token-Scope ``write``. ``mode='append'`` haengt mit dem Trenner
    ``\\n\\n---\\n`` an die bestehende Notiz an; ``mode='replace'`` (Default)
    ueberschreibt. Leerstring ``content`` loescht die Notiz.
    """
    require_scope(request, "write")

    ticker_norm = (ticker or "").strip().upper()
    if not ticker_norm:
        raise HTTPException(status_code=404, detail="Ticker nicht in Watchlist gefunden")

    result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.ticker == ticker_norm,
        )
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Ticker nicht in Watchlist gefunden")

    existing_plain = decrypt_field(item.notes) or ""
    char_count_before = len(existing_plain)

    new_content = data.content or ""
    if data.mode == "append" and existing_plain:
        if new_content:
            combined = f"{existing_plain}\n\n---\n{new_content}"
        else:
            combined = existing_plain
    else:
        combined = new_content

    if len(combined) > NOTES_MAX_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"Notiz ueberschreitet das Limit von {NOTES_MAX_LEN} Zeichen",
        )

    item.notes = encrypt_field(combined) if combined else None
    now = utcnow()
    item.notes_last_api_write_at = now
    token = getattr(request.state, "api_token", None)
    item.notes_last_api_token_name = getattr(token, "name", None)

    if not combined:
        action = "notes_clear"
    elif data.mode == "append":
        action = "notes_append"
    else:
        action = "notes_replace"

    db.add(ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker=ticker_norm,
        action=action,
        char_count_before=char_count_before,
        char_count_after=len(combined),
    ))

    await db.commit()

    return {
        "ticker": ticker_norm,
        "mode": data.mode,
        "char_count": len(combined),
        "notes_last_api_write_at": now.isoformat(),
    }


# --- Pending Orders ---
#
# Manuell gepflegte Limit-Orders, die der User beim Broker platziert hat.
# Read+Write fuer Tokens mit ``write``-Scope, GET auch fuer ``read``-Tokens
# (notes werden bei read-only Tokens ausgeblendet, analog Watchlist).


@router.get("/pending-orders")
@limiter.limit(RATE_LIMIT)
async def list_pending_orders_external(
    request: Request,
    status: str = Query(default="open"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Pending Orders des Users mit current_price und distance_pct.

    Notes und die ``notes_last_api_*``-Marker werden immer mitgeliefert (gleiches
    Pattern wie Watchlist) — Provenienz braucht der Konsument für Sync.
    """
    if status not in ("open", "closed", "all"):
        raise HTTPException(
            status_code=422, detail="status muss 'open', 'closed' oder 'all' sein"
        )

    from services.pending_order_service import get_pending_orders

    return await get_pending_orders(db, user.id, status_filter=status)  # type: ignore[arg-type]


def _serialize_order_minimal_for_external(order: PendingOrder) -> dict:
    from services.pending_order_service import compute_effective_status

    today = datetime.date.today()
    return {
        "id": str(order.id),
        "ticker": order.ticker,
        "side": order.side,
        "shares": float(order.shares),
        "limit_price": float(order.limit_price),
        "stop_price": float(order.stop_price) if order.stop_price is not None else None,
        "currency": order.currency,
        "expiry_type": order.expiry_type,
        "expiry_date": order.expiry_date.isoformat() if order.expiry_date else None,
        "broker": order.broker,
        "bucket_id_target": (
            str(order.bucket_id_target)
            if order.bucket_id_target is not None
            else None
        ),
        "status": order.status,
        "effective_status": compute_effective_status(order, today),
        "linked_transaction_id": (
            str(order.linked_transaction_id)
            if order.linked_transaction_id is not None
            else None
        ),
        "notes": order.notes,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


@router.post("/pending-orders", status_code=201)
@limiter.limit(RATE_LIMIT)
async def add_pending_order_external(
    request: Request,
    data: ExternalPendingOrderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Pending Order anlegen. Erfordert Scope ``write``."""
    require_scope(request, "write")

    count_result = await db.execute(
        select(func.count())
        .select_from(PendingOrder)
        .where(PendingOrder.user_id == user.id)
    )
    if (count_result.scalar() or 0) >= MAX_PENDING_ORDERS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=(
                "Pending-Order-Limit erreicht "
                f"(max. {MAX_PENDING_ORDERS_PER_USER} Eintraege)"
            ),
        )

    bucket_id_target = None
    if data.bucket_id_target is not None:
        from models.bucket import Bucket
        b_q = await db.execute(
            select(Bucket).where(
                Bucket.id == data.bucket_id_target,
                Bucket.user_id == user.id,
                Bucket.deleted_at.is_(None),
            )
        )
        if b_q.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Ungültiger Bucket")
        bucket_id_target = data.bucket_id_target

    ticker_norm = data.ticker.strip().upper()
    order = PendingOrder(
        id=uuid.uuid4(),
        user_id=user.id,
        ticker=ticker_norm,
        side=data.side,
        shares=data.shares,
        limit_price=data.limit_price,
        stop_price=data.stop_price,
        currency=data.currency.upper(),
        expiry_type=data.expiry_type,
        expiry_date=data.expiry_date,
        broker=data.broker,
        notes=data.notes,
        bucket_id_target=bucket_id_target,
        status="open",
    )
    db.add(order)

    token = getattr(request.state, "api_token", None)
    db.add(
        ApiWriteLog(
            token_id=getattr(token, "id", None),
            user_id=user.id,
            ticker=ticker_norm,
            action="pending_order_create",
            target_id=order.id,
        )
    )
    await db.commit()
    await db.refresh(order)
    return _serialize_order_minimal_for_external(order)


_FILLED_EDITABLE_FIELDS_EXT = {"notes"}


@router.patch("/pending-orders/{order_id}")
@limiter.limit(RATE_LIMIT)
async def update_pending_order_external(
    request: Request,
    order_id: uuid.UUID,
    data: ExternalPendingOrderUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Pending Order aktualisieren. Erfordert Scope ``write``."""
    require_scope(request, "write")

    order = await db.get(PendingOrder, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pending Order nicht gefunden")

    patch = data.model_dump(exclude_unset=True)
    if not patch:
        return _serialize_order_minimal_for_external(order)

    if order.status == "filled":
        illegal = set(patch.keys()) - _FILLED_EDITABLE_FIELDS_EXT
        if illegal:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Gefillte Order ist historisch — nur 'notes' editierbar. "
                    f"Abgelehnte Felder: {sorted(illegal)}"
                ),
            )

    new_expiry_type = patch.get("expiry_type", order.expiry_type)
    new_expiry_date = patch.get("expiry_date", order.expiry_date)
    if new_expiry_type == "gtd" and new_expiry_date is None:
        raise HTTPException(
            status_code=422,
            detail="expiry_date ist bei expiry_type='gtd' Pflicht",
        )
    if new_expiry_type != "gtd" and new_expiry_date is not None:
        raise HTTPException(
            status_code=422,
            detail="expiry_date nur bei expiry_type='gtd' erlaubt",
        )

    if "currency" in patch and patch["currency"]:
        patch["currency"] = patch["currency"].upper()
    if "bucket_id_target" in patch and patch["bucket_id_target"] is not None:
        from models.bucket import Bucket
        b_q = await db.execute(
            select(Bucket).where(
                Bucket.id == patch["bucket_id_target"],
                Bucket.user_id == user.id,
                Bucket.deleted_at.is_(None),
            )
        )
        if b_q.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Ungültiger Bucket")

    token = getattr(request.state, "api_token", None)
    if "notes" in patch:
        order.notes_last_api_write_at = utcnow()
        order.notes_last_api_token_name = getattr(token, "name", None)

    for key, val in patch.items():
        setattr(order, key, val)

    db.add(
        ApiWriteLog(
            token_id=getattr(token, "id", None),
            user_id=user.id,
            ticker=order.ticker,
            action="pending_order_update",
            target_id=order.id,
        )
    )
    await db.commit()
    await db.refresh(order)
    return _serialize_order_minimal_for_external(order)


@router.delete("/pending-orders/{order_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def delete_pending_order_external(
    request: Request,
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> None:
    """Pending Order loeschen. Erfordert Scope ``write``.

    Auch fuer ``filled``-Orders erlaubt — die verlinkte Transaktion bleibt
    dank ``ON DELETE SET NULL`` unberuehrt.
    """
    require_scope(request, "write")

    order = await db.get(PendingOrder, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pending Order nicht gefunden")

    ticker_snapshot = order.ticker
    order_id_snapshot = order.id
    await db.delete(order)

    token = getattr(request.state, "api_token", None)
    db.add(
        ApiWriteLog(
            token_id=getattr(token, "id", None),
            user_id=user.id,
            ticker=ticker_snapshot,
            action="pending_order_cancel",
            target_id=order_id_snapshot,
        )
    )
    await db.commit()


@router.post("/pending-orders/{order_id}/fill")
@limiter.limit(RATE_LIMIT)
async def fill_pending_order_external(
    request: Request,
    order_id: uuid.UUID,
    data: ExternalPendingOrderFill,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Pending Order als ausgefuehrt markieren — atomar Transaktion + Status.

    Erfordert Scope ``write``. Logik wird via ``api.orders._do_fill`` mit dem
    internen Endpoint geteilt — dort liegt die Position-Auto-Anlage und die
    Transaction-Buchung.
    """
    require_scope(request, "write")

    order = await db.get(PendingOrder, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pending Order nicht gefunden")

    from api.orders import PendingOrderFill, _do_fill
    from api.portfolio import invalidate_portfolio_cache
    from services.snapshot_trigger import trigger_snapshot_regen

    internal_data = PendingOrderFill(**data.model_dump())
    order, txn, _ = await _do_fill(db, user, order, internal_data)

    token = getattr(request.state, "api_token", None)
    db.add(
        ApiWriteLog(
            token_id=getattr(token, "id", None),
            user_id=user.id,
            ticker=order.ticker,
            action="pending_order_fill",
            target_id=order.id,
        )
    )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    await db.refresh(order)
    invalidate_portfolio_cache(str(user.id))
    trigger_snapshot_regen(user.id, txn.date)

    return {
        "order": _serialize_order_minimal_for_external(order),
        "transaction_id": str(txn.id),
    }


@router.get("/screening/macro/cot")
@limiter.limit(RATE_LIMIT)
async def screening_macro_cot(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_api_user),
) -> dict:
    """CFTC COT Macro-Positionierung (5 Futures-Instrumente, 52w-Perzentile).

    Isolierte Macro/Positioning-Daten — kein Einfluss auf den Equity-Screening-
    Score. Siehe SCOPE_SMART_MONEY_V4.md Block 1.
    """
    from services.macro.cot_service import get_latest_cot_overview
    return await get_latest_cot_overview(db)


@router.get("/screening/latest")
@limiter.limit(RATE_LIMIT)
async def screening_latest(
    request: Request,
    min_score: int = Query(default=1, ge=0, le=10),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Results of the most recent completed screening scan.

    Zusaetzlich zum Ergebnis-Array liefert der Endpoint ein
    `pipeline_health`-Objekt zurueck, das pro Datenquelle den Status des
    letzten Runs zeigt (done/error + count). Damit kann der Konsument
    differenzieren zwischen 'kein Signal' (weil die Pipeline laeuft aber
    nichts findet) und 'stumme Pipeline' (weil der Scraper kaputt ist).
    """
    latest_q = (
        select(ScreeningScan)
        .where(ScreeningScan.status == "completed")
        .order_by(desc(ScreeningScan.started_at))
        .limit(1)
    )
    scan = (await db.execute(latest_q)).scalar_one_or_none()
    if not scan:
        return {
            "scan_id": None,
            "scanned_at": None,
            "total": 0,
            "results": [],
            "pipeline_health": [],
            "warnings": ["no_completed_scan_yet"],
        }

    res_q = (
        select(ScreeningResult)
        .where(ScreeningResult.scan_id == scan.id, ScreeningResult.score >= min_score)
        .order_by(desc(ScreeningResult.score))
    )
    rows = (await db.execute(res_q)).scalars().all()

    # Pipeline-Health aus den Steps extrahieren
    steps = list(scan.steps or [])
    pipeline_health: list[dict] = []
    warnings: list[str] = []
    scan_age_days = 0
    if scan.started_at:
        from dateutils import utcnow
        scan_age_days = (utcnow() - scan.started_at).days
    if scan_age_days > 2:
        warnings.append(f"scan_stale:{scan_age_days}_days")

    for step in steps:
        source = step.get("source", "unknown")
        status = step.get("status", "unknown")
        count = step.get("count")
        pipeline_health.append({
            "source": source,
            "label": step.get("label", source),
            "status": status,
            "count": count,
        })
        # Explizite Warnings fuer stumme oder fehlerhafte Pipelines
        if status == "error":
            warnings.append(f"pipeline_error:{source}")
        elif status == "done" and (count is None or count == 0):
            warnings.append(f"pipeline_empty:{source}")

    return {
        "scan_id": str(scan.id),
        "scanned_at": scan.started_at.isoformat() if scan.started_at else None,
        "scan_age_days": scan_age_days,
        "total": len(rows),
        "results": [
            {
                "ticker": r.ticker,
                "name": r.name,
                "sector": r.sector,
                "score": r.score,
                "score_display": r.score_display,
                "signals": r.signals,
                "price_usd": r.price_usd,
            }
            for r in rows
        ],
        "pipeline_health": pipeline_health,
        "warnings": warnings,
    }


# --- Report-Vault (Upload) ---
#
# Schreibpfad fuer den Claude-Finance-Workspace. Read/List/Tag/Export/Delete
# liegen in api/reports.py (JWT, fuer das UI). Hier nur der Token-Upload.

@router.post("/reports", status_code=201)
@limiter.limit(RATE_LIMIT)
async def upload_report(
    request: Request,
    data: ReportUpload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Markdown-Brief in den Report-Vault hochladen (Token-Scope ``write``).

    Idempotent ueber ``source_path`` (natuerlicher Key pro Quelldatei):
    - vorhanden + gleicher content_hash → ``unchanged`` (no-op)
    - vorhanden + abweichender Hash → Body/Meta aktualisiert (``updated``);
      user-editierte ``tags`` bleiben erhalten
    - nicht vorhanden → ``created``
    Ohne ``source_path`` dedupliziert ``content_hash`` (exakt gleicher Brief).
    """
    require_scope(request, "write")

    content_hash = hashlib.sha256(data.body.encode("utf-8")).hexdigest()
    category = ((data.category or "other").strip().lower() or "other")[:50]
    tags = [str(t).strip()[:50] for t in (data.tags or []) if str(t).strip()]
    if len(tags) > MAX_TAGS_PER_REPORT:
        raise HTTPException(status_code=422, detail=f"Maximal {MAX_TAGS_PER_REPORT} Tags pro Report")

    if data.source_path:
        existing = (await db.execute(
            select(Report).where(
                Report.user_id == user.id, Report.source_path == data.source_path
            )
        )).scalars().first()
    else:
        existing = (await db.execute(
            select(Report).where(
                Report.user_id == user.id, Report.content_hash == content_hash
            )
        )).scalars().first()

    if existing:
        if existing.content_hash == content_hash:
            return {"status": "unchanged", "id": str(existing.id)}
        # source_path bekannt, Inhalt geaendert → updaten (tags nicht clobbern).
        existing.title = data.title
        existing.category = category
        existing.report_date = data.report_date
        existing.body = data.body
        existing.content_hash = content_hash
        if data.source is not None:
            existing.source = data.source
        if not existing.tags and tags:
            existing.tags = tags
        await db.commit()
        return {"status": "updated", "id": str(existing.id)}

    count = (await db.execute(
        select(func.count()).select_from(Report).where(Report.user_id == user.id)
    )).scalar() or 0
    if count >= MAX_REPORTS_PER_USER:
        raise HTTPException(
            status_code=400, detail=f"Report-Limit erreicht (max. {MAX_REPORTS_PER_USER})"
        )

    report = Report(
        user_id=user.id,
        category=category,
        title=data.title,
        report_date=data.report_date,
        body=data.body,
        tags=tags,
        source=data.source,
        source_path=data.source_path,
        content_hash=content_hash,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return {"status": "created", "id": str(report.id)}


@router.post("/reports/prune")
@limiter.limit(RATE_LIMIT)
async def prune_reports(
    request: Request,
    data: ReportPrune,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Vault-Waisen einer Sync-Quelle entfernen (Token-Scope ``write``).

    Reconciliation: `source_paths` ist die vollstaendige Menge aktuell
    existierender Quelldateien. Geloescht werden user-scoped alle Reports mit
    `source == data.source`, deren `source_path` NICHT in dieser Menge ist
    (= geloeschte/umbenannte Briefe). Strikt auf `source` gescoped — fremde
    oder manuell angelegte Eintraege bleiben unberuehrt.

    SICHERHEIT: leere `source_paths` → No-op (nie "loesche alles"). Schuetzt
    gegen einen Sync-Bug, der faelschlich 0 Dateien meldet.
    """
    require_scope(request, "write")

    if not data.source_paths:
        kept = (await db.execute(
            select(func.count()).select_from(Report).where(
                Report.user_id == user.id, Report.source == data.source
            )
        )).scalar() or 0
        return {"deleted": 0, "kept": kept, "warning": "empty_source_paths_skipped"}

    result = await db.execute(
        delete(Report).where(
            Report.user_id == user.id,
            Report.source == data.source,
            Report.source_path.isnot(None),
            Report.source_path.notin_(data.source_paths),
        )
    )
    await db.commit()
    deleted = result.rowcount or 0

    kept = (await db.execute(
        select(func.count()).select_from(Report).where(
            Report.user_id == user.id, Report.source == data.source
        )
    )).scalar() or 0

    return {"deleted": deleted, "kept": kept}


# --- Report-Vault (Lesen/Aendern/Loeschen per ID) ---
#
# Voll-CRUD-Parität mit der internen UI-API (api/reports.py), aber ueber den
# X-API-Key statt JWT. GET = read-Scope (jeder gueltige Token), PATCH/DELETE =
# write-Scope. Alles user-scoped — ein Token sieht nur Reports seines Users.

def _report_meta(r: Report) -> dict:
    """Listen-Repraesentation ohne Body (leichtgewichtig)."""
    return {
        "id": str(r.id),
        "category": r.category,
        "title": r.title,
        "report_date": r.report_date.isoformat() if r.report_date else None,
        "tags": r.tags or [],
        "source": r.source,
        "source_path": r.source_path,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


async def _get_owned_report(db: AsyncSession, report_id: uuid.UUID, user: User) -> Report:
    report = await db.get(Report, report_id)
    if not report or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="Report nicht gefunden")
    return report


@router.get("/reports")
@limiter.limit(RATE_LIMIT)
async def list_reports_external(
    request: Request,
    category: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    source: str | None = Query(default=None, max_length=100),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Reports des Token-Users — Metadaten ohne Body, gefiltert + paginiert (read-Scope).

    Liefert die ``id`` jedes Reports — der natuerliche Einstieg fuer das
    gezielte Lesen/Aendern/Loeschen per ``report_id``.
    """
    stmt = select(Report).where(Report.user_id == user.id)
    if category:
        stmt = stmt.where(Report.category == category)
    if source:
        stmt = stmt.where(Report.source == source)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Report.title.ilike(like), Report.body.ilike(like)))
    if date_from:
        stmt = stmt.where(Report.report_date >= date_from)
    if date_to:
        stmt = stmt.where(Report.report_date <= date_to)

    rows = (await db.execute(stmt)).scalars().all()

    # Tag-Filter in Python (JSONB-Array, portabel ueber SQLite-Tests).
    if tag:
        rows = [r for r in rows if tag in (r.tags or [])]

    # report_date desc (NULLs zuletzt), dann created_at desc.
    rows.sort(
        key=lambda r: (
            r.report_date is not None,
            r.report_date.isoformat() if r.report_date else "",
            r.created_at.isoformat() if r.created_at else "",
        ),
        reverse=True,
    )

    total = len(rows)
    start = (page - 1) * per_page
    page_rows = rows[start:start + per_page]
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": [_report_meta(r) for r in page_rows],
    }


@router.get("/reports/{report_id}")
@limiter.limit(RATE_LIMIT)
async def get_report_external(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Voller Report inkl. Markdown-``body`` (read-Scope)."""
    report = await _get_owned_report(db, report_id, user)
    return {**_report_meta(report), "body": report.body}


@router.patch("/reports/{report_id}")
@limiter.limit(RATE_LIMIT)
async def update_report_external(
    request: Request,
    report_id: uuid.UUID,
    data: ReportPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Report partiell aendern (write-Scope).

    Nur uebergebene Felder werden geaendert; ``tags: []`` leert die Tags.
    Body-Aenderung berechnet ``content_hash`` neu (haelt das Sync-Upsert konsistent).
    """
    require_scope(request, "write")
    report = await _get_owned_report(db, report_id, user)

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        return {"status": "unchanged", **_report_meta(report)}

    if "title" in updates:
        report.title = updates["title"]
    if "category" in updates:
        report.category = ((updates["category"] or "other").strip().lower() or "other")[:50]
    if "report_date" in updates:
        report.report_date = updates["report_date"]
    if "tags" in updates:
        tags = [str(t).strip()[:50] for t in (updates["tags"] or []) if str(t).strip()]
        seen: set[str] = set()
        deduped = [t for t in tags if not (t in seen or seen.add(t))]
        if len(deduped) > MAX_TAGS_PER_REPORT:
            raise HTTPException(status_code=422, detail=f"Maximal {MAX_TAGS_PER_REPORT} Tags pro Report")
        report.tags = deduped
    if "body" in updates:
        report.body = updates["body"]
        report.content_hash = hashlib.sha256(updates["body"].encode("utf-8")).hexdigest()

    await db.commit()
    await db.refresh(report)
    return {"status": "updated", **_report_meta(report)}


@router.delete("/reports/{report_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def delete_report_external(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Einzelnen Report per ID loeschen (write-Scope)."""
    require_scope(request, "write")
    report = await _get_owned_report(db, report_id, user)
    await db.delete(report)
    await db.commit()
    return Response(status_code=204)


# --- Immobilien (Real Estate) ---
#
# Eigener Namespace, weil Immobilien (HEILIGE Regel 4) niemals in die liquide
# Portfolio-Performance einfliessen. Sensible Felder (address, bank, tenant,
# notes) werden ueber filter_property() / filter_mortgage() entfernt.

def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail=f"{label} nicht gefunden")


@router.get("/immobilien")
@limiter.limit(RATE_LIMIT)
async def list_immobilien(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Alle Immobilien des Users inkl. Hypotheken (gefiltert), Totals."""
    summary = await get_properties_summary(db, user_id=user.id)
    return {
        "total_value_chf": summary.get("total_value_chf"),
        "total_mortgage_chf": summary.get("total_mortgage_chf"),
        "total_equity_chf": summary.get("total_equity_chf"),
        "properties": [filter_property(p) for p in summary.get("properties", [])],
    }


@router.get("/immobilien/{property_id}")
@limiter.limit(RATE_LIMIT)
async def get_immobilie(
    request: Request,
    property_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Detailansicht einer einzelnen Immobilie inkl. Hypotheken/Ausgaben/Einnahmen."""
    pid = _parse_uuid(property_id, "Immobilie")
    detail = await get_property_detail(db, pid, user_id=user.id)
    if not detail:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden")
    return filter_property(detail)


@router.get("/immobilien/{property_id}/hypotheken")
@limiter.limit(RATE_LIMIT)
async def list_hypotheken(
    request: Request,
    property_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Hypotheken einer Immobilie (ohne sensible Bank-Felder)."""
    pid = _parse_uuid(property_id, "Immobilie")
    detail = await get_property_detail(db, pid, user_id=user.id)
    if not detail:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden")
    filtered = filter_property(detail)
    return {
        "property_id": filtered["id"],
        "mortgages": filtered.get("mortgages", []),
    }


# --- Vorsorge (Saeule 3a / Pension) ---
#
# Eigener Namespace, weil Vorsorge (HEILIGE Regel 5) nicht in liquides Vermoegen
# einfliesst. Wir liefern hier nur die Accounts selbst — keine aggregierten
# Performance-Kennzahlen, weil cost_basis_chf == market_value_chf manuell
# gepflegt wird. Sensible Felder (bank_name, iban, notes) werden gefiltert.

def _pension_to_dict(p: Position) -> dict:
    return {
        "id": str(p.id),
        "ticker": p.ticker,
        "name": p.name,
        "type": p.type.value if p.type else None,
        "currency": p.currency,
        "cost_basis_chf": float(p.cost_basis_chf or 0),
        "market_value_chf": float(p.cost_basis_chf or 0),
        "buy_date": None,
        "is_active": p.is_active,
        "bank_name": decrypt_field(p.bank_name),
        "iban": decrypt_and_mask_iban(p.iban),
        "notes": decrypt_field(p.notes),
    }


@router.get("/vorsorge")
@limiter.limit(RATE_LIMIT)
async def list_vorsorge(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Alle Vorsorge-Konten (Saeule 3a) des Users (ohne bank_name/iban/notes)."""
    result = await db.execute(
        select(Position).where(
            Position.user_id == user.id,
            Position.type == AssetType.pension,
            Position.is_active == True,
        )
    )
    rows = result.scalars().all()
    accounts = [filter_pension_position(_pension_to_dict(p)) for p in rows]
    total = sum(a.get("market_value_chf", 0) or 0 for a in accounts)
    return {
        "total_value_chf": round(total, 2),
        "accounts": accounts,
    }


@router.get("/vorsorge/{position_id}")
@limiter.limit(RATE_LIMIT)
async def get_vorsorge(
    request: Request,
    position_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Detailansicht eines einzelnen Vorsorge-Kontos."""
    pid = _parse_uuid(position_id, "Vorsorge-Konto")
    result = await db.execute(
        select(Position).where(
            Position.id == pid,
            Position.user_id == user.id,
            Position.type == AssetType.pension,
        )
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Vorsorge-Konto nicht gefunden")
    return filter_pension_position(_pension_to_dict(pos))


# --- Price Alerts (Schreib-Endpoints, Scope: write; GET ist offen) ---


def _ext_alert_to_dict(a: PriceAlert) -> dict:
    return {
        "id": str(a.id),
        "ticker": a.ticker,
        "alert_type": a.alert_type,
        "target_value": float(a.target_value),
        "currency": a.currency,
        "is_active": a.is_active,
        "is_triggered": a.is_triggered,
        "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
        "trigger_price": float(a.trigger_price) if a.trigger_price else None,
        "notify_in_app": a.notify_in_app,
        "notify_email": a.notify_email,
        "note": a.note,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
    }


async def _user_owns_ticker(db: AsyncSession, user_id: uuid.UUID, ticker: str) -> bool:
    """True if the user has the ticker in watchlist OR holds an active position."""
    wl = await db.execute(
        select(WatchlistItem.id).where(
            WatchlistItem.user_id == user_id,
            WatchlistItem.ticker == ticker,
        ).limit(1)
    )
    if wl.scalar() is not None:
        return True
    pos = await db.execute(
        select(Position.id).where(
            Position.user_id == user_id,
            Position.ticker == ticker,
            Position.is_active == True,
            Position.shares > 0,
        ).limit(1)
    )
    return pos.scalar() is not None


@router.get("/alerts")
@limiter.limit(RATE_LIMIT)
async def list_alerts_external(
    request: Request,
    ticker: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    triggered: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list[dict]:
    """Eigene Preis-Alarme listen.

    Konsistent mit ``GET /watchlist`` ist dieser Endpoint **nicht**
    scope-gated — auch read-only Tokens duerfen ihre eigenen Alarme sehen,
    damit sie vor dem Schreiben pruefen koennen, ob ein Alarm bereits existiert.
    """
    query = select(PriceAlert).where(PriceAlert.user_id == user.id)
    if active is not None:
        query = query.where(PriceAlert.is_active == active)
    if triggered is not None:
        query = query.where(PriceAlert.is_triggered == triggered)
    if ticker:
        query = query.where(PriceAlert.ticker == ticker.upper())
    query = query.order_by(PriceAlert.created_at.desc())
    result = await db.execute(query)
    return [_ext_alert_to_dict(a) for a in result.scalars().all()]


@router.post("/alerts", status_code=201)
@limiter.limit(RATE_LIMIT)
async def create_alert_external(
    request: Request,
    data: ExternalAlertCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Neuen Preis-Alarm anlegen. Erfordert Scope ``write``.

    Der Ticker muss entweder in der Watchlist oder als aktive Position
    existieren — verhindert Spam ueber beliebige Tickers.
    """
    require_scope(request, "write")

    ticker_norm = data.ticker.strip().upper()
    if not await _user_owns_ticker(db, user.id, ticker_norm):
        raise HTTPException(
            status_code=400,
            detail="Ticker weder in Watchlist noch im Portfolio",
        )

    count_result = await db.execute(
        select(func.count()).select_from(PriceAlert).where(
            PriceAlert.user_id == user.id, PriceAlert.is_active == True
        )
    )
    if (count_result.scalar() or 0) >= 100:
        raise HTTPException(status_code=400, detail="Alarm-Limit erreicht (max. 100 aktive Alarme)")

    alert = PriceAlert(
        id=uuid.uuid4(),
        user_id=user.id,
        ticker=ticker_norm,
        alert_type=data.alert_type,
        target_value=data.target_value,
        currency=data.currency,
        notify_in_app=data.notify_in_app,
        notify_email=data.notify_email,
        note=data.note,
        expires_at=data.expires_at,
    )
    db.add(alert)

    token = getattr(request.state, "api_token", None)
    db.add(ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker=ticker_norm,
        action="alert_create",
        target_id=alert.id,
    ))

    await db.commit()
    await db.refresh(alert)
    return _ext_alert_to_dict(alert)


@router.patch("/alerts/{alert_id}")
@limiter.limit(RATE_LIMIT)
async def update_alert_external(
    request: Request,
    alert_id: uuid.UUID,
    data: ExternalAlertUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Bestehenden Alarm aktualisieren. Erfordert Scope ``write``.

    ``is_triggered`` und ``is_active`` koennen ueber diesen Endpoint nicht
    veraendert werden — wie im internen API.
    """
    require_scope(request, "write")

    alert = await db.get(PriceAlert, alert_id)
    if not alert or alert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alarm nicht gefunden")
    if alert.is_triggered:
        raise HTTPException(status_code=400, detail="Alarm wurde bereits ausgeloest")

    if data.target_value is not None:
        alert.target_value = data.target_value
    if data.note is not None:
        alert.note = data.note
    if data.notify_in_app is not None:
        alert.notify_in_app = data.notify_in_app
    if data.notify_email is not None:
        alert.notify_email = data.notify_email
    if data.expires_at is not None:
        alert.expires_at = data.expires_at

    token = getattr(request.state, "api_token", None)
    db.add(ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker=alert.ticker,
        action="alert_update",
        target_id=alert.id,
    ))

    await db.commit()
    await db.refresh(alert)
    return _ext_alert_to_dict(alert)


@router.delete("/alerts/{alert_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def delete_alert_external(
    request: Request,
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> None:
    """Alarm loeschen. Erfordert Scope ``write``."""
    require_scope(request, "write")

    alert = await db.get(PriceAlert, alert_id)
    if not alert or alert.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alarm nicht gefunden")

    ticker = alert.ticker
    aid = alert.id
    await db.delete(alert)

    token = getattr(request.state, "api_token", None)
    db.add(ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker=ticker,
        action="alert_delete",
        target_id=aid,
    ))

    await db.commit()


@router.get("/alerts/triggered")
@limiter.limit(RATE_LIMIT)
async def list_triggered_alerts_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list[dict]:
    """Kürzlich ausgelöste Alarme der letzten 7 Tage (Spiegel des UI-Widgets)."""
    cutoff = utcnow() - datetime.timedelta(days=7)
    result = await db.execute(
        select(PriceAlert).where(
            PriceAlert.user_id == user.id,
            PriceAlert.is_triggered == True,
            PriceAlert.triggered_at >= cutoff,
        ).order_by(PriceAlert.triggered_at.desc())
    )
    return [_ext_alert_to_dict(a) for a in result.scalars().all()]


# --- Stop-Loss (Read + Write) ---
#
# Read-Endpoints liefern dieselbe Sicht wie das UI-Stop-Loss-Widget.
# Write-Endpoints hinter ``write``-Scope, beide hinterlassen einen
# ``ApiWriteLog``-Eintrag für die Provenienz.  Hard-Cap auf den Batch
# (``STOP_LOSS_BATCH_MAX_ITEMS``) ist explizit strenger als intern, um
# Skript-Bugs (versehentliche 16k-Loops) abzufangen.


# Hinweis: Der ``stoploss_service`` nimmt ``user_id`` als ``str``, ruft aber
# intern ``Position.user_id == user_id`` auf — was bei SQLite (Test-DB) den
# String nicht korrekt in UUID konvertiert.  Wir reichen daher das ``user.id``
# **als UUID-Objekt** durch (Postgres akzeptiert beides; SQLite nur UUID).


@router.get("/portfolio/positions-without-stoploss")
@limiter.limit(RATE_LIMIT)
async def positions_without_stoploss_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list[dict]:
    """Aktive Positionen (shares > 0) ohne gesetzten Stop-Loss."""
    from services.stoploss_service import get_positions_without_stoploss
    return await get_positions_without_stoploss(db, user.id)  # type: ignore[arg-type]


@router.get("/portfolio/stop-loss-status")
@limiter.limit(RATE_LIMIT)
async def stop_loss_status_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list[dict]:
    """Stop-Loss-Status (price/method/distance/confirmed) für alle Tradables."""
    from services.stoploss_service import get_stop_loss_status
    return await get_stop_loss_status(db, user.id)  # type: ignore[arg-type]


@router.patch("/positions/by-id/{position_id}/stop-loss")
@limiter.limit(RATE_LIMIT)
async def update_stop_loss_external(
    request: Request,
    position_id: uuid.UUID,
    data: ExternalStopLossUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Stop-Loss einer Position via UUID setzen.  Erfordert Scope ``write``.

    ``confirmed_at_broker`` Default ist explizit ``False`` — ein API-Call ohne
    dieses Feld markiert den Stop NICHT als broker-confirmed.
    """
    require_scope(request, "write")

    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")

    from api.portfolio import invalidate_portfolio_cache
    from services.stoploss_service import update_stop_loss as service_update_stop_loss

    # Audit-Log VOR dem Service-Aufruf zur Session adden + flushen — damit der
    # Service-Commit beide Statements atomar persistiert (verhindert die Lücke
    # aus Audit v0.38.0 Finding #3, wo ein Crash zwischen den beiden Commits
    # den Stop persistent gesetzt aber den Audit-Log verloren hätte).
    token = getattr(request.state, "api_token", None)
    db.add(ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker=pos.ticker,
        action="stop_loss_update",
        target_id=position_id,
    ))
    await db.flush()

    result = await service_update_stop_loss(
        db,
        user.id,  # type: ignore[arg-type]
        position_id,  # type: ignore[arg-type]
        data.stop_loss_price,
        data.confirmed_at_broker,
        data.method,
    )
    invalidate_portfolio_cache(str(user.id))
    return result


@router.post("/portfolio/stop-loss/batch")
@limiter.limit(RATE_LIMIT)
async def batch_stop_loss_external(
    request: Request,
    data: ExternalStopLossBatchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Stop-Loss für mehrere Positionen gleichzeitig (bis zu
    ``STOP_LOSS_BATCH_MAX_ITEMS`` Einträge).  Erfordert Scope ``write``."""
    require_scope(request, "write")

    from api.portfolio import invalidate_portfolio_cache
    from services.stoploss_service import (
        batch_update_stop_loss as service_batch_update_stop_loss,
    )

    # Pro Item ein Audit-Log VORAUSSCHAUEND — das Service-Layer committet die
    # Updates anschliessend in einer Transaktion, die den Log gleich mit
    # persistiert (Audit v0.38.0 Finding #3).  Falls ein einzelnes Item dann
    # fehlschlägt (z.B. Ticker nicht gefunden), bleibt der Log-Eintrag drin —
    # auch das ist Audit-relevant ("ein API-Aufruf hat versucht, X zu setzen").
    token = getattr(request.state, "api_token", None)
    for item in data.items:
        db.add(ApiWriteLog(
            token_id=getattr(token, "id", None),
            user_id=user.id,
            ticker=item.ticker,
            action="stop_loss_batch",
        ))
    await db.flush()

    items = [item.model_dump() for item in data.items]
    result = await service_batch_update_stop_loss(db, user.id, items)  # type: ignore[arg-type]

    if result.get("updated"):
        invalidate_portfolio_cache(str(user.id))
    return result


# --- Transactions (Read) ---


@router.get("/transactions")
@limiter.limit(RATE_LIMIT)
async def list_transactions_external(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    type: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    date_from: datetime.date | None = Query(default=None),
    date_to: datetime.date | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Transaktionen des Users — paginiert, gleiche Filter wie UI.

    ``type`` muss einer von ``buy/sell/dividend/deposit/withdrawal/...`` sein
    (siehe ``TransactionType``).  Notes werden decrypted ausgeliefert.
    """
    from services.auth_service import escape_like

    txn_type = None
    if type:
        try:
            txn_type = TransactionType(type)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Ungueltiger Transaktions-Typ: {type}")

    query = (
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
    )
    count_query = (
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.user_id == user.id)
    )

    if txn_type is not None:
        query = query.where(Transaction.type == txn_type)
        count_query = count_query.where(Transaction.type == txn_type)

    if ticker:
        pos_result = await db.execute(
            select(Position.id).where(
                Position.ticker.ilike(f"%{escape_like(ticker)}%"),
                Position.user_id == user.id,
            )
        )
        pos_ids = [row[0] for row in pos_result]
        if not pos_ids:
            return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}
        query = query.where(Transaction.position_id.in_(pos_ids))
        count_query = count_query.where(Transaction.position_id.in_(pos_ids))

    if search:
        from sqlalchemy import or_
        search_term = f"%{escape_like(search)}%"
        pos_result = await db.execute(
            select(Position.id).where(
                Position.user_id == user.id,
                or_(
                    Position.ticker.ilike(search_term),
                    Position.name.ilike(search_term),
                ),
            )
        )
        matching_pos_ids = [row[0] for row in pos_result]
        if not matching_pos_ids:
            return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}
        query = query.where(Transaction.position_id.in_(matching_pos_ids))
        count_query = count_query.where(Transaction.position_id.in_(matching_pos_ids))

    if date_from:
        query = query.where(Transaction.date >= date_from)
        count_query = count_query.where(Transaction.date >= date_from)
    if date_to:
        query = query.where(Transaction.date <= date_to)
        count_query = count_query.where(Transaction.date <= date_to)

    total = (await db.execute(count_query)).scalar() or 0
    rows = (await db.execute(query.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    pos_ids_needed = {t.position_id for t in rows}
    positions_map = {}
    if pos_ids_needed:
        pos_result = await db.execute(
            select(Position).where(Position.id.in_(pos_ids_needed))
        )
        for p in pos_result.scalars():
            positions_map[p.id] = {"ticker": p.ticker, "name": p.name}

    items = []
    for t in rows:
        pos_info = positions_map.get(t.position_id, {})
        items.append({
            "id": str(t.id),
            "position_id": str(t.position_id),
            "ticker": pos_info.get("ticker", "–"),
            "position_name": pos_info.get("name", "–"),
            "type": t.type.value,
            "date": t.date.isoformat(),
            "shares": float(t.shares),
            "price_per_share": float(t.price_per_share),
            "currency": t.currency,
            "fx_rate_to_chf": float(t.fx_rate_to_chf),
            "fees_chf": float(t.fees_chf),
            "taxes_chf": float(t.taxes_chf),
            "total_chf": float(t.total_chf),
            "notes": decrypt_field(t.notes),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total else 0,
    }


# --- Dividends (Read) ---


@router.get("/dividends/pending")
@limiter.limit(RATE_LIMIT)
async def list_pending_dividends_external(
    request: Request,
    status: str = Query(default="pending"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Pending-Dividenden des Users — Spiegel von ``GET /api/dividends/pending``."""
    from api.dividends import list_pending_dividends
    response = await list_pending_dividends(status=status, limit=limit, db=db, user=user)
    return response.model_dump(mode="json")


@router.get("/dividends/count")
@limiter.limit(RATE_LIMIT)
async def count_pending_dividends_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Schneller Counter für pending Dividenden (Sidebar-Badge-Wert)."""
    from api.dividends import count_pending_dividends
    response = await count_pending_dividends(db=db, user=user)
    return response.model_dump(mode="json")


# --- Private Equity (Read) ---


@router.get("/private-equity")
@limiter.limit(RATE_LIMIT)
async def list_pe_holdings_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Alle aktiven PE-Beteiligungen mit Summary."""
    from services.private_equity_service import get_holdings_summary
    return await get_holdings_summary(db, user.id)


@router.get("/private-equity/{holding_id}")
@limiter.limit(RATE_LIMIT)
async def get_pe_holding_external(
    request: Request,
    holding_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Detailansicht inkl. Valuations + Dividends-History."""
    from services.private_equity_service import get_holding_detail
    detail = await get_holding_detail(db, user.id, holding_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Beteiligung nicht gefunden")
    return detail


# --- Position Submodi ---


@router.get("/positions/by-id/{position_id}")
@limiter.limit(RATE_LIMIT)
async def get_position_by_id_external(
    request: Request,
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Einzelne Position via UUID (für Stop-Loss-PATCH-Workflow)."""
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    return {
        "id": str(pos.id),
        "ticker": pos.ticker,
        "name": pos.name,
        "type": pos.type.value,
        "sector": pos.sector,
        "industry": pos.industry,
        "currency": pos.currency,
        "bucket_id": str(pos.bucket_id) if pos.bucket_id else None,
        "shares": float(pos.shares),
        "cost_basis_chf": float(pos.cost_basis_chf),
        "current_price": float(pos.current_price) if pos.current_price else None,
        "manual_resistance": (
            float(pos.manual_resistance) if pos.manual_resistance is not None else None
        ),
        "stop_loss_price": (
            float(pos.stop_loss_price) if pos.stop_loss_price is not None else None
        ),
        "stop_loss_method": pos.stop_loss_method,
        "stop_loss_confirmed_at_broker": pos.stop_loss_confirmed_at_broker,
        "stop_loss_updated_at": (
            pos.stop_loss_updated_at.isoformat() if pos.stop_loss_updated_at else None
        ),
        "is_etf": pos.is_etf,
        "is_active": pos.is_active,
        "bank_name": decrypt_field(pos.bank_name),
        "iban": decrypt_and_mask_iban(pos.iban),
        "notes": decrypt_field(pos.notes),
    }


@router.get("/positions/by-id/{position_id}/history")
@limiter.limit(RATE_LIMIT)
async def position_history_external(
    request: Request,
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list[dict]:
    """Transaktionshistorie einer Position."""
    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    rows = await db.execute(
        select(Transaction)
        .where(Transaction.position_id == position_id)
        .order_by(Transaction.date.desc())
    )
    return [
        {
            "id": str(t.id),
            "type": t.type.value,
            "date": t.date.isoformat(),
            "shares": float(t.shares),
            "price_per_share": float(t.price_per_share),
            "currency": t.currency,
            "fx_rate_to_chf": float(t.fx_rate_to_chf),
            "fees_chf": float(t.fees_chf),
            "taxes_chf": float(t.taxes_chf),
            "total_chf": float(t.total_chf),
            "notes": decrypt_field(t.notes),
        }
        for t in rows.scalars().all()
    ]


@router.get("/positions/by-id/{position_id}/dividends")
@limiter.limit(RATE_LIMIT)
async def position_dividends_external(
    request: Request,
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list:
    """Dividendenhistorie aus yfinance, gefiltert ab erster Buy-Transaction."""
    from services.dividend_service import fetch_dividends

    pos = await db.get(Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    result = await db.execute(
        select(Transaction.date)
        .where(Transaction.position_id == position_id, Transaction.type == "buy")
        .order_by(Transaction.date.asc())
        .limit(1)
    )
    first_buy = result.scalar()
    if not first_buy:
        return []
    yf_ticker = pos.yfinance_ticker or pos.ticker
    return await asyncio.to_thread(
        fetch_dividends, yf_ticker, first_buy, float(pos.shares), pos.currency,
    )


# --- Performance (Lückenschluss) ---


@router.get("/performance/benchmark-returns")
@limiter.limit(RATE_LIMIT)
async def benchmark_returns_external(
    request: Request,
    ticker: str = Query(default="^GSPC"),
    user: User = Depends(get_api_user),
) -> dict:
    """Monatliche Benchmark-Returns (S&P/Nasdaq/STOXX50/SMI)."""
    ALLOWED = frozenset({"^GSPC", "^IXIC", "^STOXX50E", "^SSMI"})
    if ticker not in ALLOWED:
        raise HTTPException(status_code=400, detail="Ungueltiger Benchmark-Ticker")
    from services.benchmark_service import get_benchmark_monthly_returns
    return await asyncio.to_thread(get_benchmark_monthly_returns, ticker)


@router.get("/performance/fee-summary")
@limiter.limit(RATE_LIMIT)
async def fee_summary_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Gebühren- und Steuer-Aggregat über alle Transaktionen."""
    from services.total_return_service import get_fee_summary
    return await get_fee_summary(db, user_id=user.id)


@router.get("/performance/allocation/core-satellite")
@limiter.limit(RATE_LIMIT)
async def core_satellite_allocation_external(
    request: Request,
    view: str = Query(default="liquid"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Core/Satellite/Unassigned-Allocation."""
    from services.allocation_service import get_core_satellite_allocation
    return await get_core_satellite_allocation(db, user.id, view)


# --- Market-Daten ---


@router.get("/market/climate")
@limiter.limit(RATE_LIMIT)
async def market_climate_external(
    request: Request,
    _user: User = Depends(get_api_user),
) -> dict:
    """Markt-Klima inkl. Macro-Gate, Tech-Checks, VIX/SARON."""
    from services.macro_indicators_service import (
        fetch_all_indicators,
        fetch_extra_indicators,
    )
    from services.macro_gate_service import calculate_macro_gate
    from services.market_analyzer import get_market_climate

    climate, macro, extra = await asyncio.gather(
        asyncio.to_thread(get_market_climate),
        fetch_all_indicators(),
        fetch_extra_indicators(),
    )
    gate = calculate_macro_gate(climate=climate)

    checks = climate.get("checks", {})
    tech_checks = [
        {"id": "above_200dma", "label": "S&P 500 ueber 200-DMA", "passed": checks.get("price_above_ma200")},
        {"id": "above_150dma", "label": "S&P 500 ueber 150-DMA", "passed": checks.get("price_above_ma150")},
        {"id": "above_50dma", "label": "S&P 500 ueber 50-DMA", "passed": checks.get("price_above_ma50")},
        {"id": "hh_hl", "label": "S&P 500 HH/HL Struktur", "passed": (
            checks.get("price_above_ma50") is True and checks.get("ma50_above_ma150") is True
        ) if checks.get("price_above_ma50") is not None and checks.get("ma50_above_ma150") is not None else None},
    ]
    tech_score = sum(1 for c in tech_checks if c["passed"] is True)
    climate["tech_checks"] = tech_checks
    climate["tech_score"] = tech_score
    climate["macro"] = macro
    climate["extra_indicators"] = extra
    climate["gate"] = gate
    return climate


@router.get("/market/vix")
@limiter.limit(RATE_LIMIT)
async def market_vix_external(
    request: Request,
    _user: User = Depends(get_api_user),
) -> dict:
    """VIX-Snapshot."""
    from services.price_service import get_vix
    return await asyncio.to_thread(get_vix)


@router.get("/market/macro-indicators")
@limiter.limit(RATE_LIMIT)
async def market_macro_indicators_external(
    request: Request,
    _user: User = Depends(get_api_user),
) -> dict:
    """5 Makro-Crash-Indikatoren mit Ampel-Status + Gate."""
    from services.macro_indicators_service import fetch_all_indicators
    from services.macro_gate_service import calculate_macro_gate
    result = await fetch_all_indicators()
    gate = calculate_macro_gate()
    result["gate_passed"] = gate["passed"]
    result["gate"] = gate
    return result


_FX_CCY_PATTERN = r"^[A-Za-z]{3,5}$"


@router.get("/market/fx/{from_currency}")
@limiter.limit(RATE_LIMIT)
async def market_fx_external(
    request: Request,
    from_currency: str,
    to_currency: str = Query(default="CHF", pattern=_FX_CCY_PATTERN),
    _user: User = Depends(get_api_user),
) -> dict:
    """FX-Spot-Rate (Default Ziel: CHF).

    ``from_currency`` und ``to_currency`` werden auf ISO-4217-Format validiert
    (3-5 Buchstaben).  Unbekannte Codes liefern weiter ``rate=1.0`` (stiller
    Fallback im Service-Layer), die Validation hier verhindert nur offensichtlichen
    Garbage wie ``GET /market/fx/garbage12345``.
    """
    import re
    if not re.match(_FX_CCY_PATTERN, from_currency):
        raise HTTPException(status_code=422, detail="Ungueltiger Waehrungscode")
    from services.utils import get_fx_rate
    rate = await asyncio.to_thread(
        get_fx_rate, from_currency.upper(), to_currency.upper()
    )
    return {"from": from_currency.upper(), "to": to_currency.upper(), "rate": rate}


@router.get("/market/precious-metals")
@limiter.limit(RATE_LIMIT)
async def market_precious_metals_external(
    request: Request,
    _user: User = Depends(get_api_user),
) -> dict:
    """Gold-/Silber-Spot + Gold-Silver-Ratio."""
    from services.price_service import get_gold_price_chf, get_stock_price
    gold_spot, gold_comex, silver_comex = await asyncio.gather(
        asyncio.to_thread(get_gold_price_chf),
        asyncio.to_thread(get_stock_price, "GC=F"),
        asyncio.to_thread(get_stock_price, "SI=F"),
    )
    ratio = None
    if gold_comex and silver_comex and silver_comex["price"] > 0:
        ratio = round(gold_comex["price"] / silver_comex["price"], 1)
    return {
        "gold_spot_chf": gold_spot,
        "gold_comex_usd": gold_comex,
        "silver_comex_usd": silver_comex,
        "gold_silver_ratio": ratio,
    }


@router.get("/market/real-estate")
@limiter.limit(RATE_LIMIT)
async def market_real_estate_external(
    request: Request,
    _user: User = Depends(get_api_user),
) -> dict:
    """Immobilien-Markt-Benchmark (Schweizer Indizes, Mieten/Preise)."""
    from services.property_service import get_real_estate_market_data
    return await get_real_estate_market_data()


@router.get("/market/crypto-metrics")
@limiter.limit(RATE_LIMIT)
async def market_crypto_metrics_external(
    request: Request,
    _user: User = Depends(get_api_user),
) -> dict:
    """Krypto-Metriken (BTC-Dominanz, F&G, Halving, DXY, BTC-ATH-Distanz)."""
    cached = cache.get("crypto_metrics")
    if cached is not None:
        return cached
    # Re-use the internal endpoint's exact logic — it already caches under
    # ``crypto_metrics``, so the next external pull serves from cache too.
    from api.market import crypto_metrics as _internal_crypto_metrics
    # FastAPI Endpoint nicht direkt aufrufbar (request-Objekt) — dupliziere
    # die Service-Aufrufe statt den Decorator zu reverse-engineeren.
    from config import settings as cfg_settings
    from datetime import date
    from services.api_utils import fetch_json
    from services.price_service import get_stock_price

    result = {"tier1": {}, "tier2": {}}

    async def _fetch_global():
        try:
            data = await fetch_json(f"{cfg_settings.coingecko_base_url}/global")
            return data.get("data", {})
        except Exception as e:
            logger.warning(f"CoinGecko global failed: {e}")
            return None

    async def _fetch_fng():
        try:
            return await fetch_json("https://api.alternative.me/fng/?limit=1")
        except Exception as e:
            logger.warning(f"Fear & Greed API failed: {e}")
            return None

    async def _fetch_btc_ath():
        try:
            return await fetch_json(
                f"{cfg_settings.coingecko_base_url}/coins/bitcoin",
                params={"localization": "false", "tickers": "false",
                        "community_data": "false", "developer_data": "false"},
            )
        except Exception as e:
            logger.warning(f"CoinGecko BTC ATH failed: {e}")
            return None

    global_data, fng_data, btc_data, dxy = await asyncio.gather(
        _fetch_global(), _fetch_fng(), _fetch_btc_ath(),
        asyncio.to_thread(get_stock_price, "DX-Y.NYB"),
    )

    if global_data:
        result["tier1"]["btc_dominance"] = round(
            global_data.get("market_cap_percentage", {}).get("btc", 0), 1
        )
    if fng_data:
        fng = fng_data.get("data", [{}])[0]
        result["tier1"]["fear_greed_value"] = int(fng.get("value", 0))
        result["tier1"]["fear_greed_label"] = fng.get("value_classification", "")

    halving_date = date(2028, 4, 15)
    days_to_halving = (halving_date - date.today()).days
    result["tier1"]["next_halving_days"] = max(days_to_halving, 0)
    result["tier1"]["next_halving_date"] = "April 2028"

    if dxy:
        result["tier1"]["dxy_value"] = dxy["price"]
        result["tier1"]["dxy_change_pct"] = dxy.get("change_pct", 0)

    if btc_data:
        market = btc_data.get("market_data", {})
        ath_chf = market.get("ath", {}).get("chf")
        current_chf = market.get("current_price", {}).get("chf")
        if ath_chf and current_chf:
            result["tier2"]["btc_ath_chf"] = round(ath_chf, 0)
            result["tier2"]["btc_ath_distance_pct"] = round(
                ((current_chf / ath_chf) - 1) * 100, 1
            )

    cache.set("crypto_metrics", result, ttl=900)
    return result


@router.get("/market/sectors/{etf_ticker}/holdings")
@limiter.limit(RATE_LIMIT)
async def market_sector_holdings_external(
    request: Request,
    etf_ticker: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_api_user),
) -> dict:
    """SPDR-Sektor-ETF Holdings + Setup-Scores."""
    from services.sector_analyzer import get_sector_holdings
    result = await get_sector_holdings(etf_ticker.upper(), db)
    if result is None:
        raise HTTPException(status_code=404, detail="ETF nicht gefunden")
    return result


@router.get("/market/sectors/{etf_ticker}/scores")
@limiter.limit(RATE_LIMIT)
async def market_sector_scores_external(
    request: Request,
    etf_ticker: str,
    _user: User = Depends(get_api_user),
) -> dict:
    """Setup-Scores aller Holdings eines Sektor-ETFs (24h Cache)."""
    from services.sector_analyzer import SECTOR_ETF_HOLDINGS
    from services.scoring_service import assess_ticker

    holdings = SECTOR_ETF_HOLDINGS.get(etf_ticker.upper())
    if not holdings:
        raise HTTPException(status_code=404, detail="ETF nicht gefunden")

    batch_cache_key = f"sector_scores:{etf_ticker.upper()}"
    cached = cache.get(batch_cache_key)
    if cached is not None:
        return cached

    tickers = [t for t, _, _ in holdings]
    etf_sector_map = {
        "XLK": "Technology", "XLV": "Healthcare", "XLF": "Financial Services",
        "XLY": "Consumer Cyclical", "XLP": "Consumer Defensive", "XLE": "Energy",
        "XLI": "Industrials", "XLB": "Basic Materials", "XLRE": "Real Estate",
        "XLU": "Utilities", "XLC": "Communication Services",
    }
    sector = etf_sector_map.get(etf_ticker.upper())

    def _compute_all():
        results = {}
        for ticker in tickers:
            ticker_cache_key = f"setup_score:{ticker}"
            ticker_cached = cache.get(ticker_cache_key)
            if ticker_cached is not None:
                results[ticker] = ticker_cached
                continue
            try:
                data = assess_ticker(ticker, sector=sector)
                score_data = {
                    "score": data.get("score", 0),
                    "max_score": data.get("max_score", 0),
                    "rating": data.get("rating", ""),
                    "mansfield_rs": data.get("mansfield_rs"),
                    "signal": data.get("signal", ""),
                    "gate_blocked": data.get("gate_blocked", False),
                }
                cache.set(ticker_cache_key, score_data, ttl=86400)
                results[ticker] = score_data
            except Exception as e:
                logger.debug(f"Score failed for {ticker}: {e}")
                results[ticker] = {
                    "score": 0, "max_score": 0, "rating": "", "mansfield_rs": None,
                }
        return results

    scores = await asyncio.to_thread(_compute_all)
    cache.set(batch_cache_key, scores, ttl=86400)
    return scores


# --- Stock Search + Profile + ETF-Sector ---


@router.get("/stock/search")
@limiter.limit(RATE_LIMIT)
async def stock_search_external(
    request: Request,
    q: str = Query(..., min_length=1, max_length=30),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list[dict]:
    """Ticker-Suche: zuerst eigene Positionen, dann yfinance."""
    from services.auth_service import escape_like

    query = q.strip().upper()
    results: list[dict] = []
    seen: set[str] = set()

    search_term = f"%{escape_like(query)}%"
    pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user.id,
            Position.ticker.ilike(search_term) | Position.name.ilike(search_term),
        ).limit(10)
    )
    for p in pos_result.scalars():
        results.append({
            "ticker": p.ticker,
            "name": p.name,
            "type": p.type.value,
            "currency": p.currency,
            "position_id": str(p.id),
            "is_existing": True,
        })
        seen.add(p.ticker.upper())

    if len(results) < 8:
        try:
            def _yf_search(q: str) -> list[dict]:
                import yfinance as yf
                inner: list[dict] = []
                try:
                    search = yf.Search(q)
                    for quote in (search.quotes or [])[:8]:
                        symbol = quote.get("symbol", "")
                        if not symbol:
                            continue
                        inner.append({
                            "ticker": symbol,
                            "name": quote.get("shortname") or quote.get("longname") or symbol,
                            "type": quote.get("quoteType", "EQUITY").lower(),
                            "exchange": quote.get("exchange", ""),
                        })
                except Exception:
                    try:
                        info = yf.Ticker(q).info or {}
                        if info.get("symbol"):
                            inner.append({
                                "ticker": info["symbol"],
                                "name": info.get("shortName") or info.get("longName") or info["symbol"],
                                "type": info.get("quoteType", "EQUITY").lower(),
                                "exchange": info.get("exchange", ""),
                            })
                    except Exception:
                        pass
                return inner

            yf_results = await asyncio.to_thread(_yf_search, query)
            for item in yf_results:
                if item["ticker"].upper() not in seen:
                    qt = item["type"].lower()
                    if qt == "etf":
                        asset_type = "etf"
                    elif qt in ("cryptocurrency", "crypto"):
                        asset_type = "crypto"
                    else:
                        asset_type = "stock"
                    results.append({
                        "ticker": item["ticker"],
                        "name": item["name"],
                        "type": asset_type,
                        "currency": None,
                        "position_id": None,
                        "is_existing": False,
                    })
                    seen.add(item["ticker"].upper())
        except Exception as e:
            logger.warning(f"yfinance search failed for {query}: {e}")

    return results


@router.get("/stock/{ticker}/profile")
@limiter.limit(RATE_LIMIT)
async def stock_profile_external(
    request: Request,
    ticker: str,
    _user: User = Depends(get_api_user),
) -> dict:
    """Company-Profil (Sector/Industry/MCap/Margins)."""
    from services.stock_service import get_company_profile
    try:
        return await asyncio.to_thread(get_company_profile, ticker.upper())
    except Exception as e:
        logger.warning(f"Stock profile failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail="Profil konnte nicht geladen werden")


@router.get("/etf-sectors/{ticker}")
@limiter.limit(RATE_LIMIT)
async def etf_sectors_external(
    request: Request,
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """User-spezifische Sektor-Gewichtungen für Multi-Sektor-ETFs."""
    from models.etf_sector_weight import EtfSectorWeight
    result = await db.execute(
        select(EtfSectorWeight).where(
            EtfSectorWeight.ticker == ticker.upper(),
            EtfSectorWeight.user_id == user.id,
        )
    )
    weights = result.scalars().all()
    sectors = [{"sector": w.sector, "weight_pct": float(w.weight_pct)} for w in weights]
    total = sum(s["weight_pct"] for s in sectors)
    return {
        "ticker": ticker.upper(),
        "sectors": sorted(sectors, key=lambda s: s["weight_pct"], reverse=True),
        "is_complete": 99.9 <= total <= 100.1,
    }


# --- Screening (Read) ---


@router.get("/screening/results")
@limiter.limit(RATE_LIMIT)
async def screening_results_external(
    request: Request,
    min_score: int = Query(default=1, ge=0, le=10),
    signal_type: str | None = Query(default=None),
    sector_momentum: str | None = Query(default=None),
    sort_by: str = Query(default="score"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_api_user),
) -> dict:
    """Screening-Resultate des letzten abgeschlossenen Scans (paginiert).

    Identisch zur internen ``/api/screening/results`` — nur read-only und
    ohne Session-Auth.  ``per_page`` ist auf 200 gecapt (konsistent mit
    ``/transactions``); UI nutzt typisch 50.
    """
    from services.screening.sector_rotation_service import VALID_MOMENTUM_VALUES

    if sector_momentum is not None and sector_momentum not in VALID_MOMENTUM_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"sector_momentum muss einer von {sorted(VALID_MOMENTUM_VALUES)} sein",
        )

    latest_scan_q = (
        select(ScreeningScan)
        .where(ScreeningScan.status == "completed")
        .order_by(desc(ScreeningScan.started_at))
        .limit(1)
    )
    scan = (await db.execute(latest_scan_q)).scalar_one_or_none()
    if not scan:
        return {"results": [], "total": 0, "scan_id": None, "scanned_at": None}

    query = select(ScreeningResult).where(
        ScreeningResult.scan_id == scan.id,
        ScreeningResult.score >= min_score,
    )
    if signal_type:
        query = query.where(ScreeningResult.signals.has_key(signal_type))
    if sector_momentum:
        query = query.where(ScreeningResult.sector_momentum == sector_momentum)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    if sort_by == "ticker":
        query = query.order_by(ScreeningResult.ticker)
    else:
        query = query.order_by(desc(ScreeningResult.score), ScreeningResult.ticker)

    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    results = (await db.execute(query)).scalars().all()

    return {
        "results": [
            {
                "ticker": r.ticker,
                "name": r.name,
                "sector": r.sector,
                "score": r.score,
                "score_display": r.score_display,
                "signals": r.signals,
                "price_usd": r.price_usd,
                "industry_name": r.industry_name,
                "sector_momentum": r.sector_momentum,
                "sector_bonus": r.sector_bonus,
            }
            for r in results
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "scan_id": str(scan.id),
        "scanned_at": scan.started_at.isoformat() if scan.started_at else None,
    }


@router.get("/screening/ticker/{ticker}")
@limiter.limit(RATE_LIMIT)
async def screening_ticker_external(
    request: Request,
    ticker: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_api_user),
) -> dict:
    """Screening-Resultat eines einzelnen Tickers aus dem letzten Scan."""
    latest_q = (
        select(ScreeningScan)
        .where(ScreeningScan.status == "completed")
        .order_by(desc(ScreeningScan.started_at))
        .limit(1)
    )
    scan = (await db.execute(latest_q)).scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=404, detail="Kein abgeschlossener Scan vorhanden")
    result_q = select(ScreeningResult).where(
        ScreeningResult.scan_id == scan.id,
        ScreeningResult.ticker == ticker.upper(),
    )
    result = (await db.execute(result_q)).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="Ticker nicht im Screening gefunden")
    return {
        "ticker": result.ticker,
        "name": result.name,
        "sector": result.sector,
        "score": result.score,
        "score_display": result.score_display,
        "signals": result.signals,
        "price_usd": result.price_usd,
        "industry_name": result.industry_name,
        "sector_momentum": result.sector_momentum,
        "sector_bonus": result.sector_bonus,
        "scanned_at": scan.started_at.isoformat() if scan.started_at else None,
    }


@router.get("/screening/scan/{scan_id}/progress")
@limiter.limit(RATE_LIMIT)
async def screening_scan_progress_external(
    request: Request,
    scan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_api_user),
) -> dict:
    """Fortschritt eines laufenden Scans (Polling-Endpoint).

    POST ``/scan`` selbst bleibt UI-only (Background-Job mit Snapshot-Trigger).
    """
    scan = await db.get(ScreeningScan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan nicht gefunden")
    return {
        "scan_id": str(scan.id),
        "status": scan.status,
        "steps": scan.steps or [],
        "result_count": scan.result_count,
        "started_at": scan.started_at.isoformat() if scan.started_at else None,
        "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
        "error": scan.error,
    }


# --- Precious Metals (Read) ---


def _metal_item_to_dict(item) -> dict:
    return {
        "id": str(item.id),
        "metal_type": item.metal_type,
        "form": item.form,
        "manufacturer": item.manufacturer,
        "weight_grams": float(item.weight_grams),
        "weight_oz": item.weight_oz,
        "serial_number": decrypt_field(item.serial_number),
        "fineness": item.fineness,
        "purchase_date": item.purchase_date.isoformat(),
        "purchase_price_chf": float(item.purchase_price_chf),
        "storage_location": decrypt_field(item.storage_location),
        "is_sold": item.is_sold,
        "sold_date": item.sold_date.isoformat() if item.sold_date else None,
        "sold_price_chf": float(item.sold_price_chf) if item.sold_price_chf else None,
        "notes": decrypt_field(item.notes),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/precious-metals")
@limiter.limit(RATE_LIMIT)
async def precious_metals_list_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Aktive Edelmetall-Bestände, gruppiert nach Metall-Typ."""
    from models.precious_metal_item import PreciousMetalItem
    rows = await db.execute(
        select(PreciousMetalItem)
        .where(PreciousMetalItem.user_id == user.id, PreciousMetalItem.is_sold == False)
        .order_by(PreciousMetalItem.metal_type, PreciousMetalItem.purchase_date)
    )
    items = rows.scalars().all()
    groups: dict = {}
    for item in items:
        mt = item.metal_type
        if mt not in groups:
            groups[mt] = {
                "metal_type": mt,
                "total_weight_grams": 0,
                "total_weight_oz": 0,
                "total_cost_chf": 0,
                "item_count": 0,
                "items": [],
            }
        groups[mt]["total_weight_grams"] += float(item.weight_grams)
        groups[mt]["total_weight_oz"] += item.weight_oz
        groups[mt]["total_cost_chf"] += float(item.purchase_price_chf)
        groups[mt]["item_count"] += 1
        groups[mt]["items"].append(_metal_item_to_dict(item))
    for g in groups.values():
        g["total_weight_grams"] = round(g["total_weight_grams"], 4)
        g["total_weight_oz"] = round(g["total_weight_oz"], 4)
        g["total_cost_chf"] = round(g["total_cost_chf"], 2)
    return {"groups": list(groups.values())}


@router.get("/precious-metals/sold")
@limiter.limit(RATE_LIMIT)
async def precious_metals_sold_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list[dict]:
    """Verkaufte Edelmetall-Bestände."""
    from models.precious_metal_item import PreciousMetalItem
    rows = await db.execute(
        select(PreciousMetalItem)
        .where(PreciousMetalItem.user_id == user.id, PreciousMetalItem.is_sold == True)
        .order_by(PreciousMetalItem.sold_date.desc())
    )
    return [_metal_item_to_dict(i) for i in rows.scalars().all()]


@router.get("/precious-metals/expenses")
@limiter.limit(RATE_LIMIT)
async def precious_metals_expenses_external(
    request: Request,
    metal_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list[dict]:
    """Edelmetall-Ausgaben (Lager, Versicherung, etc.)."""
    from models.precious_metal_expense import PreciousMetalExpense
    stmt = select(PreciousMetalExpense).where(PreciousMetalExpense.user_id == user.id)
    if metal_type:
        stmt = stmt.where(PreciousMetalExpense.metal_type == metal_type)
    stmt = stmt.order_by(PreciousMetalExpense.date.desc())
    rows = await db.execute(stmt)
    return [
        {
            "id": str(e.id),
            "metal_type": e.metal_type,
            "date": e.date.isoformat(),
            "category": e.category.value if e.category else None,
            "description": e.description,
            "amount": float(e.amount),
            "recurring": e.recurring,
            "frequency": e.frequency.value if e.frequency else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows.scalars().all()
    ]


@router.get("/precious-metals/expenses/summary")
@limiter.limit(RATE_LIMIT)
async def precious_metals_expenses_summary_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Annualisierte Ausgaben-Aggregate pro Kategorie."""
    from models.precious_metal_expense import PreciousMetalExpense
    rows = await db.execute(
        select(PreciousMetalExpense).where(PreciousMetalExpense.user_id == user.id)
    )
    expenses = rows.scalars().all()
    by_category = {"storage": 0.0, "insurance": 0.0, "other": 0.0}
    total = 0.0

    def _annualize(exp) -> float:
        amount = float(exp.amount)
        if not exp.recurring or not exp.frequency:
            return amount if exp.date.year == datetime.datetime.utcnow().year else 0.0
        freq = exp.frequency.value if hasattr(exp.frequency, "value") else exp.frequency
        if freq == "monthly":
            return amount * 12
        if freq == "quarterly":
            return amount * 4
        return amount

    for exp in expenses:
        annual = _annualize(exp)
        cat = exp.category.value if exp.category else "other"
        by_category[cat] = by_category.get(cat, 0.0) + annual
        total += annual
    return {
        "annual_total_chf": round(total, 2),
        "by_category": {k: round(v, 2) for k, v in by_category.items()},
        "expense_count": len(expenses),
    }


# --- Watchlist Tags ---


@router.get("/watchlist/tags")
@limiter.limit(RATE_LIMIT)
async def watchlist_tags_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list[dict]:
    """Eigene Watchlist-Tags (Name + Farbe)."""
    from models.watchlist_tag import WatchlistTag
    rows = await db.execute(
        select(WatchlistTag)
        .where(WatchlistTag.user_id == user.id)
        .order_by(WatchlistTag.name)
    )
    return [
        {"id": str(t.id), "name": t.name, "color": t.color}
        for t in rows.scalars().all()
    ]


# --- Settings (Read, Secrets maskiert) ---


@router.get("/settings")
@limiter.limit(RATE_LIMIT)
async def settings_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """User-Settings (base_currency, broker, Stop-Loss-Defaults, Alert-Toggles).

    Secrets (FRED/FMP/Finnhub-Keys) werden zu ``has_*``-Booleans maskiert.
    """
    from services import settings_service as svc
    raw = await svc.get_settings(db, user.id)
    return filter_settings(raw)


@router.get("/settings/alert-preferences")
@limiter.limit(RATE_LIMIT)
async def settings_alert_preferences_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list[dict]:
    """Pro-Kategorie Alert-Präferenzen (in_app/email/push)."""
    from services import settings_service as svc
    return await svc.get_alert_preferences(db, user.id)


@router.get("/settings/onboarding/status")
@limiter.limit(RATE_LIMIT)
async def settings_onboarding_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Onboarding-Tour-Status."""
    from services import settings_service as svc
    return await svc.get_onboarding_status(db, user)


# --- Taxonomy (Read) ---


@router.get("/taxonomy/sectors")
@limiter.limit(RATE_LIMIT)
async def taxonomy_sectors_external(
    request: Request,
    _user: User = Depends(get_api_user),
) -> dict:
    """Sektor/Industrie-Hierarchie (Finviz + multi-sector mapping)."""
    from services.sector_mapping import (
        SECTOR_ORDER,
        FINVIZ_SECTORS,
        SECTORS_WITH_INDUSTRIES,
        MULTI_SECTOR_INDUSTRIES,
    )
    return {
        "sectors": SECTOR_ORDER,
        "finviz_sectors": FINVIZ_SECTORS,
        "multi_sector_industries": MULTI_SECTOR_INDUSTRIES,
        "sectors_with_industries": SECTORS_WITH_INDUSTRIES,
    }
