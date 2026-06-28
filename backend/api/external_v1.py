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

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import limiter
from api.external_v1_schemas import (
    ExternalAlertCreate,
    ExternalAlertUpdate,
    ExternalNotesUpdate,
    ExternalDividendConfirm,
    ExternalDividendDismiss,
    ExternalEpsThresholds,
    ExternalEtfSectorWeights,
    ExternalFireAssumptions,
    ExternalMetalCreate,
    ExternalMetalExpenseCreate,
    ExternalMetalExpenseUpdate,
    ExternalMetalUpdate,
    ExternalMortgageCreate,
    ExternalMortgageUpdate,
    ExternalPEDividendCreate,
    ExternalPEDividendUpdate,
    ExternalPEHoldingCreate,
    ExternalPEHoldingUpdate,
    ExternalPEValuationCreate,
    ExternalPEValuationUpdate,
    ExternalPendingOrderCreate,
    ExternalPendingOrderFill,
    ExternalPendingOrderUpdate,
    ExternalOnboardingStep,
    ExternalPositionCreate,
    ExternalPositionUpdate,
    ExternalPropertyCreate,
    ExternalPropertyExpenseCreate,
    ExternalPropertyExpenseUpdate,
    ExternalPropertyIncomeCreate,
    ExternalPropertyIncomeUpdate,
    ExternalPropertyUpdate,
    ExternalResistanceUpdate,
    ExternalStopLossBatchRequest,
    ExternalStopLossUpdate,
    ExternalTagCreate,
    ExternalTransactionCreate,
    ExternalTransactionUpdate,
    ExternalWatchlistAdd,
    NOTES_MAX_LEN,
    ReportPatch,
    ReportPrune,
    ReportUpload,
    STOP_LOSS_BATCH_MAX_ITEMS,
    filter_bucket,
    filter_mortgage,
    filter_metal_expense,
    filter_metal_item,
    filter_pe_holding,
    filter_pension_position,
    filter_position,
    filter_property,
    filter_property_expense,
    filter_property_income,
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
from services import eps_scanner_service as eps_svc
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


@router.get("/admin/worker-health")
@limiter.limit(RATE_LIMIT)
async def external_worker_health(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/admin/worker-health` — Worker-Job-Liveness (nur Admin-Token)."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    from dateutils import utcnow
    from services.worker_health_service import (
        FAILURE_ALERT_THRESHOLD, get_all_health, is_stale_row,
    )
    now = utcnow()
    rows = await get_all_health(db)
    items = []
    stale_n = failing_n = 0
    for r in rows:
        is_stale = is_stale_row(r, now)
        is_failing = (r.get("consecutive_failures") or 0) >= FAILURE_ALERT_THRESHOLD
        stale_n += int(is_stale)
        failing_n += int(is_failing)
        items.append({**r, "is_stale": is_stale, "is_failing": is_failing})
    return {
        "jobs": items,
        "summary": {"total": len(items), "stale": stale_n, "failing": failing_n},
        "as_of": now.isoformat(),
    }


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
    period: str = Query(default="1y", pattern="^(1m|3m|6m|ytd|1y|all)$"),
    benchmark: str = Query(default="^GSPC", pattern=r"^[\^A-Z0-9.\-=]{1,20}$"),
    raw: bool = Query(default=False),
    liquid: bool = Query(default=False),
    bucket_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Portfolio history snapshots over the requested period.

    raw=true liefert die ungedownsamplete tägliche Kurve (jede echte Tagesbeobachtung
    ab Inception) statt der 5-Tage-Ausdünnung bei langen Ranges — für empirische
    Auswertungen wie Faktor-Regression/Event-Study. Es wird keine synthetische
    Pre-Inception-Historie erzeugt.

    liquid=true schliesst Cash UND Vorsorge aus → nur das Rendite-Risikobuch
    (stock/etf/crypto/commodity, inkl. Gold+BTC). Ohne den konstanten Null-Rendite-
    Ballast sind Faktor-Betas/Vol nicht gedämpft. PE + Immobilien sind ohnehin immer
    ausgeschlossen.

    bucket_id (optional) skopiert die indexierte Kurve auf die Positionen eines
    Buckets — selbe cash-flow-bereinigte portfolio_indexed-Methodik.
    """
    from services.history_service import get_portfolio_history

    today = datetime.date.today()
    if period == "1m":
        start = today - datetime.timedelta(days=30)
    elif period == "3m":
        start = today - datetime.timedelta(days=90)
    elif period == "6m":
        start = today - datetime.timedelta(days=182)
    elif period == "ytd":
        start = datetime.date(today.year, 1, 1)
    elif period == "1y":
        start = today - datetime.timedelta(days=365)
    else:  # all
        start = datetime.date(2000, 1, 1)

    return await get_portfolio_history(
        db, start, today, benchmark, user_id=user.id,
        downsample=not raw, liquid=liquid, bucket_id=bucket_id,
    )


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


@router.get("/performance/fee-summary")
@limiter.limit(RATE_LIMIT)
async def performance_fee_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Monatlicher Gebuehren-/Steuer-Breakdown (Trading/Other/Taxes)."""
    from services.total_return_service import get_fee_summary
    return await get_fee_summary(db, user_id=user.id)


@router.get("/performance/risk-metrics")
@limiter.limit(RATE_LIMIT)
async def performance_risk_metrics(
    request: Request,
    period: str = Query(default="5y", pattern="^(1y|2y|3y|5y|all)$"),
    benchmark: str = Query(default="^GSPC", pattern=r"^[\^A-Z0-9.\-=]{1,20}$"),
    bucket_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Risiko-Kennzahlen (Sharpe/Sortino/Calmar/Vol/Information-Ratio + Rolling).

    Spiegelt `GET /api/portfolio/risk-metrics`. Additive Read-Kennzahlen aus der
    cash-flow-bereinigten Index-Reihe; bucket_id (optional) skopiert auf einen
    Bucket. Bei zu wenig Historie: 422.
    """
    from services.risk_metrics_service import compute_risk_metrics

    today = datetime.date.today()
    if period == "1y":
        start = today - datetime.timedelta(days=365)
    elif period == "2y":
        start = today - datetime.timedelta(days=730)
    elif period == "3y":
        start = today - datetime.timedelta(days=1095)
    elif period == "5y":
        start = today - datetime.timedelta(days=1825)
    else:  # all
        start = datetime.date(2000, 1, 1)

    result = await compute_risk_metrics(
        db, start, today, benchmark=benchmark, user_id=user.id, bucket_id=bucket_id
    )
    if result.get("error") == "insufficient_history":
        raise HTTPException(
            status_code=422,
            detail=(
                f"Zu wenig Historie fuer Risiko-Kennzahlen "
                f"(vorhanden: {result.get('n_obs', 0)} Handelstage)."
            ),
        )
    return result


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
    """Weekly MRS (Mansfield Relative Strength) history.

    Bei leerem ``data`` enthaelt die Antwort ein ``warnings``-Array — ein
    stilles ``[]`` war fuer Konsumenten nicht von fehlender Coverage
    unterscheidbar (Befund TSM 2026-06-10). Detail-Grund steht im Backend-Log.
    """
    from services.chart_service import get_mrs_history
    data = await asyncio.to_thread(get_mrs_history, ticker.upper(), period)
    result: dict = {"ticker": ticker.upper(), "data": data}
    if not data:
        result["warnings"] = [
            "mrs_empty: Preisserie nicht verfuegbar oder Wochen-Historie < 14 "
            "(yfinance-Fetch fehlgeschlagen und/oder DB-Fallback zu kurz) — Details im Backend-Log"
        ]
    return result


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


# --- EPS-Scanner (Quartals-Gewinn-Scanner, S&P 500) ---

@router.get("/eps-scanner/results")
@limiter.limit(RATE_LIMIT)
async def eps_scanner_results(
    request: Request,
    super_quarter_only: bool = Query(default=False),
    record_quarter_only: bool = Query(default=False),
    turnaround_only: bool = Query(default=False),
    min_quarters: int = Query(default=6, ge=2, le=8),
    sector: list[str] | None = Query(default=None),
    index: list[str] | None = Query(default=None),
    search: str | None = Query(default=None, max_length=50),
    sort_by: str = Query(default="yoy_growth"),
    sort_asc: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """EPS-Scanner-Ergebnistabelle (Reported EPS, YoY, Super-/Record-Quartal).

    EPS-Rohdaten sind universe-global; die angewandten Filter-Schwellen sind
    die des Token-Eigentuemers (user_settings). Keine PII. Identische Berechnung
    wie das interne UI.
    """
    valid_sort = {"ticker", "yoy_growth", "streak_count", "latest_eps"}
    if sort_by not in valid_sort:
        sort_by = "yoy_growth"
    return await eps_svc.get_scanner_results(
        db,
        user.id,
        super_quarter_only=super_quarter_only,
        record_quarter_only=record_quarter_only,
        turnaround_only=turnaround_only,
        min_quarters=min_quarters,
        sectors=sector,
        indices=index,
        search=search,
        sort_by=sort_by,
        sort_asc=sort_asc,
        page=page,
        per_page=per_page,
    )


@router.get("/eps-scanner/thresholds")
@limiter.limit(RATE_LIMIT)
async def eps_scanner_thresholds(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Filter-Schwellen des Token-Eigentuemers (Service-Defaults bei NULL)."""
    t = await eps_svc.resolve_thresholds(db, user.id)
    return {
        "super_quarter_yoy_pct": t.yoy_threshold,
        "acceleration_margin_pp": t.acceleration_margin,
        "outlier_multiplier": t.outlier_multiplier,
    }


@router.get("/eps-scanner/status")
@limiter.limit(RATE_LIMIT)
async def eps_scanner_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Daten-Freshness / Worker-Job-Status des EPS-Scanners (universe-global)."""
    return await eps_svc.get_status(db)


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


@router.get("/analysis/factor-decomposition")
@limiter.limit(RATE_LIMIT)
async def analysis_factor_decomposition(
    request: Request,
    period: str = Query(default="all", pattern="^(1y|2y|3y|5y|all)$"),
    bucket_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Serverseitige Faktor-Decomposition (OLS) der liquiden Portfolio-Returns.

    Spiegelt `GET /api/analysis/factor-decomposition`. Regressiert die rohen
    taeglichen Liquid-Returns (raw=true, liquid=true) auf das fixe Faktor-Menu
    (SPY/MTUM/VLUE/QUAL/IWM/GLD/BTC-USD/USDCHF), NYSE-Session-aligned (Wochenende
    vorwaerts kompoundiert). Liefert betas/std_err/t_stat je Faktor, alpha,
    r_squared, adj_r_squared, n_obs, window, missing_factors.

    period steuert das Lookback-Fenster; `all` verankert via raw=true ohnehin an
    der echten Inception (keine synthetische Pre-Inception-Historie).
    """
    from services.factor_decomposition_service import factor_decomposition

    today = datetime.date.today()
    if period == "1y":
        start = today - datetime.timedelta(days=365)
    elif period == "2y":
        start = today - datetime.timedelta(days=730)
    elif period == "3y":
        start = today - datetime.timedelta(days=1095)
    elif period == "5y":
        start = today - datetime.timedelta(days=1825)
    else:  # all
        start = datetime.date(2000, 1, 1)

    result = await factor_decomposition(db, start, today, user_id=user.id, bucket_id=bucket_id)
    err = result.get("error")
    if err == "insufficient_history":
        raise HTTPException(
            status_code=422,
            detail=(
                f"Zu wenig ueberlappende Historie fuer eine Faktor-Regression "
                f"(min. 30 Handelstage, vorhanden: {result.get('n_obs', 0)})."
            ),
        )
    if err == "factor_fetch_failed":
        raise HTTPException(status_code=503, detail="factor_data_unavailable")
    return result


# --- Analyse-Sichten (External-Paritaet zu /api/analysis/*) ---
# Reiner Durchreich auf dieselben Services wie die interne UI (read-Scope).

@router.get("/analysis/net-worth")
@limiter.limit(RATE_LIMIT)
async def analysis_net_worth(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/analysis/net-worth` — Netto-Vermoegen (Konzept A)."""
    from services.net_worth_service import get_net_worth
    return await get_net_worth(db, user.id)


@router.get("/analysis/dividend-yoc")
@limiter.limit(RATE_LIMIT)
async def analysis_dividend_yoc(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/analysis/dividend-yoc` — Dividenden Yield-on-Cost (12M)."""
    from services.income_service import get_dividend_yield_on_cost
    return await get_dividend_yield_on_cost(db, user.id)


@router.get("/analysis/dividend-forecast")
@limiter.limit(RATE_LIMIT)
async def analysis_dividend_forecast(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/analysis/dividend-forecast` — projiziertes 12M-Einkommen."""
    from services.dividend_forecast_service import get_dividend_forecast
    return await get_dividend_forecast(db, user.id)


@router.post("/analysis/dividend-forecast/refresh")
@limiter.limit(RATE_LIMIT)
async def analysis_dividend_forecast_refresh(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `POST /api/analysis/dividend-forecast/refresh` — On-demand-Neuberechnung (write)."""
    require_scope(request, "write")
    from services.dividend_forecast_service import compute_dividend_forecast
    return await compute_dividend_forecast(db, user.id)


@router.get("/analysis/rebalancing")
@limiter.limit(RATE_LIMIT)
async def analysis_rebalancing(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/analysis/rebalancing` — Soll/Ist/Delta je Bucket."""
    from services.rebalancing_service import get_rebalancing_plan
    return await get_rebalancing_plan(db, user.id)


@router.get("/analysis/position-rebalancing")
@limiter.limit(RATE_LIMIT)
async def analysis_position_rebalancing(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/analysis/position-rebalancing` — Trim-Kandidaten + Konzentration."""
    from services.position_rebalancing_service import get_position_rebalancing
    return await get_position_rebalancing(db, user.id)


@router.get("/analysis/trade-journal")
@limiter.limit(RATE_LIMIT)
async def analysis_trade_journal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/analysis/trade-journal` — Vault-Plan -> Ist -> Status."""
    from services.trade_journal_service import get_trade_journal
    return await get_trade_journal(db, user.id)


@router.get("/analysis/country-lookthrough")
@limiter.limit(RATE_LIMIT)
async def analysis_country_lookthrough(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/analysis/country-lookthrough` — ETF-Laender-Durchsicht."""
    from services.concentration_service import get_country_lookthrough
    return await get_country_lookthrough(db, user.id)


@router.get("/analysis/fire-projection")
@limiter.limit(RATE_LIMIT)
async def analysis_fire_projection(
    request: Request,
    capital_base: str = Query(default="with_pension", pattern="^(liquid|with_pension)$"),
    annual_return_pct: float = Query(default=5.0, ge=-20.0, le=30.0),
    annual_savings_chf: float = Query(default=40000.0, ge=0.0, le=100_000_000.0),
    withdrawal_rate_pct: float = Query(default=4.0, gt=0.0, le=20.0),
    target_annual_spending_chf: float | None = Query(default=None, ge=0.0, le=100_000_000.0),
    horizon_years: int = Query(default=40, ge=1, le=60),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/analysis/fire-projection` — FIRE-/Kapital-Projektion (real)."""
    from services.fire_projection_service import compute_fire_projection
    return await compute_fire_projection(
        db, user.id,
        capital_base=capital_base, annual_return_pct=annual_return_pct,
        annual_savings_chf=annual_savings_chf, withdrawal_rate_pct=withdrawal_rate_pct,
        target_annual_spending_chf=target_annual_spending_chf, horizon_years=horizon_years,
    )


@router.get("/analysis/fire-assumptions")
@limiter.limit(RATE_LIMIT)
async def analysis_fire_assumptions_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/analysis/fire-assumptions` — persistierte FIRE-Annahmen."""
    from services.fire_projection_service import get_fire_assumptions
    return await get_fire_assumptions(db, user.id)


@router.put("/analysis/fire-assumptions")
@limiter.limit(RATE_LIMIT)
async def analysis_fire_assumptions_put(
    request: Request,
    data: ExternalFireAssumptions,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `PUT /api/analysis/fire-assumptions` — Annahmen speichern (write)."""
    require_scope(request, "write")
    from services.fire_projection_service import save_fire_assumptions
    return await save_fire_assumptions(db, user.id, data.model_dump())


@router.get("/analysis/signal-backtest-history")
@limiter.limit(RATE_LIMIT)
async def analysis_signal_backtest_history(
    request: Request,
    window_days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Spiegelt `GET /api/analysis/signal-backtest-history` — Per-Signal-Regime-Historie (global)."""
    from services.signal_backtest_service import get_signal_backtest_history
    return await get_signal_backtest_history(db, window_days=window_days)


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


@router.get("/buckets/{bucket_id}/total-return")
@limiter.limit(RATE_LIMIT)
async def bucket_total_return_external(
    request: Request,
    bucket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Bucket-skopierter Total-Return-Breakdown (analog /performance/total-return).

    total_return_pct ist Geld-auf-Geld (is_money_weighted=False); zeitgewichtete
    Rendite via /buckets/{id}/benchmark-comparison + /monthly-returns.
    """
    from services.bucket_service import get_bucket, BucketError
    from services.total_return_service import get_bucket_total_return
    try:
        await get_bucket(db, user.id, bucket_id)
    except BucketError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return await get_bucket_total_return(db, user.id, bucket_id)


@router.get("/buckets/{bucket_id}/fee-summary")
@limiter.limit(RATE_LIMIT)
async def bucket_fee_summary_external(
    request: Request,
    bucket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Monatlicher Gebuehren-/Steuer-Breakdown eines Buckets (analog /performance/fee-summary)."""
    from services.bucket_service import get_bucket, BucketError
    from services.total_return_service import get_fee_summary
    try:
        await get_bucket(db, user.id, bucket_id)
    except BucketError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return await get_fee_summary(db, user_id=user.id, bucket_id=bucket_id)


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
            detail=f"Watchlist-Limit erreicht (max. {MAX_WATCHLIST_PER_USER} Einträge)",
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
            detail=f"Notiz überschreitet das Limit von {NOTES_MAX_LEN} Zeichen",
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
                f"(max. {MAX_PENDING_ORDERS_PER_USER} Einträge)"
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

def _norm_ticker(raw: str | None) -> str | None:
    t = (raw or "").strip().upper()
    return t[:30] or None


async def _resolve_linked_txn_id(db: AsyncSession, user: User, raw: str | None) -> uuid.UUID | None:
    """Validiert linked_transaction_id: muss eine gueltige UUID sein UND dem
    aufrufenden User gehoeren (Multi-User-Schutz — sonst koennte ein Token einen
    Plan-Report an eine fremde Transaktion haengen). Leerstring/None -> None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        tid = uuid.UUID(s)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="linked_transaction_id ist keine gueltige UUID")
    owned = (await db.execute(
        select(Transaction.id).where(Transaction.id == tid, Transaction.user_id == user.id)
    )).first()
    if owned is None:
        raise HTTPException(status_code=404, detail="linked_transaction_id: Transaktion nicht gefunden")
    return tid


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
    # Trade-Journal-Felder (Plan->Ist-Link), ownership-validiert.
    linked_id = await _resolve_linked_txn_id(db, user, data.linked_transaction_id)

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
        # Re-Upload einer zuvor archivierten/geprunten Quelldatei holt den
        # Report zurueck in die aktive Ansicht (archived_at → NULL).
        resurrected = existing.archived_at is not None
        if resurrected:
            existing.archived_at = None
        if existing.content_hash == content_hash:
            if resurrected:
                await db.commit()
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
        # Trade-Journal-Felder nur setzen, wenn uebergeben (None = unveraendert lassen,
        # damit ein Re-Push ohne diese Felder den Link nicht ungewollt loescht).
        if data.ticker is not None:
            existing.ticker = _norm_ticker(data.ticker)
        if data.side is not None:
            existing.side = data.side
        if data.linked_transaction_id is not None:
            existing.linked_transaction_id = linked_id
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
        ticker=_norm_ticker(data.ticker),
        side=data.side,
        linked_transaction_id=linked_id,
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
    """Vault-Waisen einer Sync-Quelle archivieren (Token-Scope ``write``).

    Reconciliation: `source_paths` ist die vollstaendige Menge aktuell
    existierender Quelldateien. **Archiviert** (nicht hart geloescht) werden
    user-scoped alle aktiven Reports mit `source == data.source`, deren
    `source_path` NICHT in dieser Menge ist (= geloeschte/umbenannte Briefe).
    Reversibel: ein Re-Upload derselben Quelldatei holt den Report zurueck.
    Strikt auf `source` gescoped — fremde/manuelle Eintraege bleiben unberuehrt.

    SICHERHEIT: leere `source_paths` → No-op (nie "archiviere alles"). Schuetzt
    gegen einen Sync-Bug, der faelschlich 0 Dateien meldet.
    """
    require_scope(request, "write")

    def _active_count_stmt():
        return select(func.count()).select_from(Report).where(
            Report.user_id == user.id,
            Report.source == data.source,
            Report.archived_at.is_(None),
        )

    if not data.source_paths:
        kept = (await db.execute(_active_count_stmt())).scalar() or 0
        return {"archived": 0, "kept": kept, "warning": "empty_source_paths_skipped"}

    result = await db.execute(
        update(Report).where(
            Report.user_id == user.id,
            Report.source == data.source,
            Report.source_path.isnot(None),
            Report.source_path.notin_(data.source_paths),
            Report.archived_at.is_(None),
        ).values(archived_at=utcnow())
    )
    await db.commit()
    archived = result.rowcount or 0

    kept = (await db.execute(_active_count_stmt())).scalar() or 0

    return {"archived": archived, "kept": kept}


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
        "ticker": r.ticker,
        "side": r.side,
        "linked_transaction_id": str(r.linked_transaction_id) if r.linked_transaction_id else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "archived_at": r.archived_at.isoformat() if r.archived_at else None,
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
    archived: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Reports des Token-Users — Metadaten ohne Body, gefiltert + paginiert (read-Scope).

    Liefert die ``id`` jedes Reports — der natuerliche Einstieg fuer das
    gezielte Lesen/Aendern/Loeschen per ``report_id``. Standardmaessig nur
    **aktive** Reports; ``?archived=true`` zeigt ausschliesslich das Archiv.
    """
    stmt = select(Report).where(Report.user_id == user.id)
    stmt = stmt.where(Report.archived_at.isnot(None) if archived else Report.archived_at.is_(None))
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
    # Trade-Journal Plan->Ist-Link (exclude_unset: nur uebergebene Felder; "" loest).
    if "ticker" in updates:
        report.ticker = _norm_ticker(updates["ticker"])
    if "side" in updates:
        report.side = updates["side"]
    if "linked_transaction_id" in updates:
        report.linked_transaction_id = await _resolve_linked_txn_id(
            db, user, updates["linked_transaction_id"]
        )

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


@router.post("/reports/{report_id}/archive")
@limiter.limit(RATE_LIMIT)
async def archive_report_external(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Report ins Archiv verschieben (write-Scope) — reversibel, kein Datenverlust.

    Archivierte Reports verschwinden aus der Default-Liste und erscheinen nur
    unter ``GET /reports?archived=true``. Idempotent (erneutes Archivieren
    aendert den ``archived_at``-Zeitstempel nicht).
    """
    require_scope(request, "write")
    report = await _get_owned_report(db, report_id, user)
    if report.archived_at is None:
        report.archived_at = utcnow()
        await db.commit()
        await db.refresh(report)
    return {"status": "archived", **_report_meta(report)}


@router.post("/reports/{report_id}/unarchive")
@limiter.limit(RATE_LIMIT)
async def unarchive_report_external(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Report aus dem Archiv zurueck in die aktive Ansicht holen (write-Scope)."""
    require_scope(request, "write")
    report = await _get_owned_report(db, report_id, user)
    if report.archived_at is not None:
        report.archived_at = None
        await db.commit()
        await db.refresh(report)
    return {"status": "active", **_report_meta(report)}


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
        raise HTTPException(status_code=400, detail="Alarm wurde bereits ausgelöst")

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


# --- Positionen (Write) — volle Paritaet zum internen UI ---


@router.post("/positions", status_code=201)
@limiter.limit(RATE_LIMIT)
async def create_position_external(
    request: Request,
    data: ExternalPositionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Position anlegen — Paritaet zum UI. Erfordert Scope ``write``.

    Teilt die Kernlogik (Bucket-Auto-Zuordnung, PII-Verschluesselung,
    Sektor-Ableitung, Snapshot-Regen) mit dem internen Endpoint ueber
    ``api.positions.create_position_core``. Der ``ApiWriteLog`` wird atomar mit
    der Position committet."""
    require_scope(request, "write")

    from api.positions import PositionCreate, create_position_core

    internal_data = PositionCreate(**data.model_dump(exclude_unset=True))
    token = getattr(request.state, "api_token", None)
    audit_log = ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker="",
        action="position_create",
    )
    result = await create_position_core(db, user, internal_data, audit_log=audit_log)
    return filter_position(result)


@router.put("/positions/by-id/{position_id}")
@limiter.limit(RATE_LIMIT)
async def update_position_external(
    request: Request,
    position_id: uuid.UUID,
    data: ExternalPositionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Position aendern — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")

    from api.positions import PositionUpdate, update_position_core

    internal_data = PositionUpdate(**data.model_dump(exclude_unset=True))
    token = getattr(request.state, "api_token", None)
    audit_log = ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker="",
        action="position_update",
    )
    result = await update_position_core(db, user, position_id, internal_data, audit_log=audit_log)
    return filter_position(result)


@router.delete("/positions/by-id/{position_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def delete_position_external(
    request: Request,
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Position loeschen — Paritaet zum UI. Erfordert Scope ``write``.

    Macht die Snapshot-Regen-Wirkung an. Der ``ApiWriteLog`` wird atomar mit dem
    Delete committet."""
    require_scope(request, "write")

    from api.positions import delete_position_core

    token = getattr(request.state, "api_token", None)
    audit_log = ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker="",
        action="position_delete",
    )
    await delete_position_core(db, user, position_id, audit_log=audit_log)
    return Response(status_code=204)


@router.post("/positions/recalculate")
@limiter.limit(RATE_LIMIT)
async def recalculate_positions_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Alle Positionen neu berechnen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")

    from services.recalculate_service import recalculate_all_positions

    token = getattr(request.state, "api_token", None)
    db.add(ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker="",
        action="position_recalculate",
    ))
    results = await recalculate_all_positions(db, user_id=user.id)
    await db.commit()
    return {"results": results}


@router.post("/positions/by-id/{position_id}/recalculate")
@limiter.limit(RATE_LIMIT)
async def recalculate_position_external(
    request: Request,
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Einzelne Position neu berechnen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")

    from api.portfolio import invalidate_portfolio_cache
    from models.position import Position as _Position
    from services.recalculate_service import recalculate_position

    pos = await db.get(_Position, position_id)
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position nicht gefunden")
    token = getattr(request.state, "api_token", None)
    db.add(ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker=(pos.ticker or "")[:30],
        action="position_recalculate",
        target_id=pos.id,
    ))
    result = await recalculate_position(db, position_id)
    await db.commit()
    invalidate_portfolio_cache(str(user.id))
    return result


# --- Immobilien (Write) — volle Paritaet zum internen UI ---
#
# Die internen Routen (api/real_estate.py) sind duenne Wrapper ueber
# ``services.property_service`` (self-committing). Die externen Endpoints rufen
# dieselben Service-Funktionen und haengen einen ``ApiWriteLog`` an, der mit dem
# Service-Commit atomar persistiert wird (Log VOR dem Service-Aufruf in die
# Session, target_id bei Updates/Deletes vom Pfad-Parameter).


def _mk_re_log(request: Request, user: User, action: str, target_id=None) -> ApiWriteLog:
    token = getattr(request.state, "api_token", None)
    return ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker="",
        action=action,
        target_id=target_id,
    )


@router.post("/immobilien", status_code=201)
@limiter.limit(RATE_LIMIT)
async def create_property_external(
    request: Request,
    data: ExternalPropertyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Immobilie anlegen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import create_property as svc

    db.add(_mk_re_log(request, user, "property_create"))
    result = await svc(db, user.id, data.model_dump())
    return filter_property(result)


@router.put("/immobilien/{property_id}")
@limiter.limit(RATE_LIMIT)
async def update_property_external(
    request: Request,
    property_id: uuid.UUID,
    data: ExternalPropertyUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Immobilie aendern — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import update_property as svc

    db.add(_mk_re_log(request, user, "property_update", target_id=property_id))
    result = await svc(db, user.id, property_id, data.model_dump(exclude_unset=True))
    return filter_property(result)


@router.delete("/immobilien/{property_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def delete_property_external(
    request: Request,
    property_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Immobilie loeschen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import delete_property as svc

    db.add(_mk_re_log(request, user, "property_delete", target_id=property_id))
    await svc(db, user.id, property_id)
    return Response(status_code=204)


@router.post("/immobilien/{property_id}/hypotheken", status_code=201)
@limiter.limit(RATE_LIMIT)
async def create_mortgage_external(
    request: Request,
    property_id: uuid.UUID,
    data: ExternalMortgageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Hypothek anlegen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import create_mortgage as svc

    db.add(_mk_re_log(request, user, "mortgage_create", target_id=property_id))
    result = await svc(db, user.id, property_id, data.model_dump())
    return filter_mortgage(result)


@router.put("/immobilien/hypotheken/{mortgage_id}")
@limiter.limit(RATE_LIMIT)
async def update_mortgage_external(
    request: Request,
    mortgage_id: uuid.UUID,
    data: ExternalMortgageUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Hypothek aendern — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import update_mortgage as svc

    db.add(_mk_re_log(request, user, "mortgage_update", target_id=mortgage_id))
    result = await svc(db, user.id, uuid.UUID(int=0), mortgage_id, data.model_dump(exclude_unset=True))
    return filter_mortgage(result)


@router.delete("/immobilien/hypotheken/{mortgage_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def delete_mortgage_external(
    request: Request,
    mortgage_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Hypothek loeschen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import delete_mortgage as svc

    db.add(_mk_re_log(request, user, "mortgage_delete", target_id=mortgage_id))
    await svc(db, user.id, uuid.UUID(int=0), mortgage_id)
    return Response(status_code=204)


@router.post("/immobilien/{property_id}/ausgaben", status_code=201)
@limiter.limit(RATE_LIMIT)
async def create_property_expense_external(
    request: Request,
    property_id: uuid.UUID,
    data: ExternalPropertyExpenseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Immobilien-Ausgabe anlegen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import create_expense as svc

    db.add(_mk_re_log(request, user, "property_expense_create", target_id=property_id))
    result = await svc(db, user.id, property_id, data.model_dump())
    return filter_property_expense(result)


@router.put("/immobilien/ausgaben/{expense_id}")
@limiter.limit(RATE_LIMIT)
async def update_property_expense_external(
    request: Request,
    expense_id: uuid.UUID,
    data: ExternalPropertyExpenseUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Immobilien-Ausgabe aendern — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import update_expense as svc

    db.add(_mk_re_log(request, user, "property_expense_update", target_id=expense_id))
    result = await svc(db, user.id, uuid.UUID(int=0), expense_id, data.model_dump(exclude_unset=True))
    return filter_property_expense(result)


@router.delete("/immobilien/ausgaben/{expense_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def delete_property_expense_external(
    request: Request,
    expense_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Immobilien-Ausgabe loeschen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import delete_expense as svc

    db.add(_mk_re_log(request, user, "property_expense_delete", target_id=expense_id))
    await svc(db, user.id, uuid.UUID(int=0), expense_id)
    return Response(status_code=204)


@router.post("/immobilien/{property_id}/einnahmen", status_code=201)
@limiter.limit(RATE_LIMIT)
async def create_property_income_external(
    request: Request,
    property_id: uuid.UUID,
    data: ExternalPropertyIncomeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Immobilien-Einnahme anlegen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import create_income as svc

    db.add(_mk_re_log(request, user, "property_income_create", target_id=property_id))
    result = await svc(db, user.id, property_id, data.model_dump())
    return filter_property_income(result)


@router.put("/immobilien/einnahmen/{income_id}")
@limiter.limit(RATE_LIMIT)
async def update_property_income_external(
    request: Request,
    income_id: uuid.UUID,
    data: ExternalPropertyIncomeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Immobilien-Einnahme aendern — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import update_income as svc

    db.add(_mk_re_log(request, user, "property_income_update", target_id=income_id))
    result = await svc(db, user.id, uuid.UUID(int=0), income_id, data.model_dump(exclude_unset=True))
    return filter_property_income(result)


@router.delete("/immobilien/einnahmen/{income_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def delete_property_income_external(
    request: Request,
    income_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Immobilien-Einnahme loeschen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from services.property_service import delete_income as svc

    db.add(_mk_re_log(request, user, "property_income_delete", target_id=income_id))
    await svc(db, user.id, uuid.UUID(int=0), income_id)
    return Response(status_code=204)


# --- Transactions (Read + Write) ---


@router.post("/transactions", status_code=201)
@limiter.limit(RATE_LIMIT)
async def create_transaction_external(
    request: Request,
    data: ExternalTransactionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Transaktion direkt buchen — volle Paritaet zum internen UI-Endpoint.

    Erfordert Scope ``write``.  Teilt die Kernlogik mit dem internen Endpoint
    ueber ``api.transactions.create_transaction_core`` (Position-Auto-Anlage,
    Snapshot-Regen, Cache-Invalidierung, Dividend-Auto-Match).  Es gibt KEINEN
    impliziten Duplikat-Schutz: der Caller muss vor dem Schreiben pruefen, dass
    die Transaktion nicht schon existiert (z. B. via ``GET /transactions`` mit
    ``date_from``/``date_to``/``ticker``).

    Der ``ApiWriteLog`` wird **atomar** mit der Buchung committet (an
    ``create_transaction_core`` durchgereicht). Damit kann ein fehlgeschlagener
    Log-Insert nie eine bereits durable Buchung hinterlassen — ein Retry des
    Callers bleibt duplikatfrei.
    """
    require_scope(request, "write")

    from api.transactions import TransactionCreate, create_transaction_core

    internal_data = TransactionCreate(**data.model_dump())
    token = getattr(request.state, "api_token", None)
    # ticker/target_id setzt der Core nach dem Flush aus der erzeugten Buchung.
    audit_log = ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker="",
        action="transaction_create",
    )
    return await create_transaction_core(
        db, user, internal_data, audit_log=audit_log,
    )


@router.put("/transactions/{txn_id}")
@limiter.limit(RATE_LIMIT)
async def update_transaction_external(
    request: Request,
    txn_id: uuid.UUID,
    data: ExternalTransactionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Transaktion aendern — Paritaet zum UI. Erfordert Scope ``write``.

    Position/Ticker/Typ sind nicht aenderbar (wie im UI). Der ``ApiWriteLog``
    wird atomar mit dem Update committet (siehe POST).
    """
    require_scope(request, "write")

    from api.transactions import TransactionUpdate, update_transaction_core

    internal_data = TransactionUpdate(**data.model_dump(exclude_unset=True))
    token = getattr(request.state, "api_token", None)
    audit_log = ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker="",
        action="transaction_update",
    )
    return await update_transaction_core(
        db, user, txn_id, internal_data, audit_log=audit_log,
    )


@router.delete("/transactions/{txn_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def delete_transaction_external(
    request: Request,
    txn_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Transaktion loeschen — Paritaet zum UI. Erfordert Scope ``write``.

    Macht die Positions-Wirkung rueckgaengig (``reverse_transaction_on_position``)
    und triggert Snapshot-Regen. Der ``ApiWriteLog`` wird atomar mit dem Delete
    committet (Rollback bei Log-Fehler — kein halb-geloeschter Zustand).
    """
    require_scope(request, "write")

    from api.transactions import delete_transaction_core

    token = getattr(request.state, "api_token", None)
    audit_log = ApiWriteLog(
        token_id=getattr(token, "id", None),
        user_id=user.id,
        ticker="",
        action="transaction_delete",
    )
    await delete_transaction_core(db, user, txn_id, audit_log=audit_log)
    return Response(status_code=204)


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
            raise HTTPException(status_code=422, detail=f"Ungültiger Transaktions-Typ: {type}")

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
        raise HTTPException(status_code=400, detail="Ungültiger Benchmark-Ticker")
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
        raise HTTPException(status_code=422, detail="Ungültiger Währungscode")
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


# =====================================================================
# UI-Paritaet v0.45 — restliche Schreib-Endpoints (Scope ``write``)
# Jeder Endpoint spiegelt 1:1 das interne UI ueber dieselbe Kernlogik
# (geteilte ``_core``-Funktionen bzw. Service-Layer) und haengt einen
# atomaren ``ApiWriteLog`` an.
# =====================================================================


# --- Private Equity (Write) ---


@router.post("/private-equity", status_code=201)
@limiter.limit(RATE_LIMIT)
async def pe_create_holding_external(
    request: Request,
    data: ExternalPEHoldingCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """PE-Beteiligung anlegen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.private_equity import HoldingCreate, create_holding_core

    audit_log = _mk_re_log(request, user, "pe_holding_create")
    result = await create_holding_core(
        db, user, HoldingCreate(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )
    return filter_pe_holding(result)


@router.put("/private-equity/{holding_id}")
@limiter.limit(RATE_LIMIT)
async def pe_update_holding_external(
    request: Request,
    holding_id: uuid.UUID,
    data: ExternalPEHoldingUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """PE-Beteiligung aendern — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.private_equity import HoldingUpdate, update_holding_core

    audit_log = _mk_re_log(request, user, "pe_holding_update", target_id=holding_id)
    result = await update_holding_core(
        db, user, holding_id, HoldingUpdate(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )
    return filter_pe_holding(result)


@router.delete("/private-equity/{holding_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def pe_delete_holding_external(
    request: Request,
    holding_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """PE-Beteiligung loeschen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.private_equity import delete_holding_core

    audit_log = _mk_re_log(request, user, "pe_holding_delete", target_id=holding_id)
    await delete_holding_core(db, user, holding_id, audit_log=audit_log)
    return Response(status_code=204)


@router.post("/private-equity/{holding_id}/valuations", status_code=201)
@limiter.limit(RATE_LIMIT)
async def pe_create_valuation_external(
    request: Request,
    holding_id: uuid.UUID,
    data: ExternalPEValuationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """PE-Bewertung anlegen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.private_equity import ValuationCreate, create_valuation_core

    audit_log = _mk_re_log(request, user, "pe_valuation_create", target_id=holding_id)
    result = await create_valuation_core(
        db, user, holding_id, ValuationCreate(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )
    return filter_pe_holding(result)


@router.put("/private-equity/{holding_id}/valuations/{valuation_id}")
@limiter.limit(RATE_LIMIT)
async def pe_update_valuation_external(
    request: Request,
    holding_id: uuid.UUID,
    valuation_id: uuid.UUID,
    data: ExternalPEValuationUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """PE-Bewertung aendern — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.private_equity import ValuationUpdate, update_valuation_core

    audit_log = _mk_re_log(request, user, "pe_valuation_update", target_id=holding_id)
    result = await update_valuation_core(
        db, user, holding_id, valuation_id, ValuationUpdate(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )
    return filter_pe_holding(result)


@router.delete("/private-equity/{holding_id}/valuations/{valuation_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def pe_delete_valuation_external(
    request: Request,
    holding_id: uuid.UUID,
    valuation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """PE-Bewertung loeschen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.private_equity import delete_valuation_core

    audit_log = _mk_re_log(request, user, "pe_valuation_delete", target_id=holding_id)
    await delete_valuation_core(db, user, holding_id, valuation_id, audit_log=audit_log)
    return Response(status_code=204)


@router.post("/private-equity/{holding_id}/dividends", status_code=201)
@limiter.limit(RATE_LIMIT)
async def pe_create_dividend_external(
    request: Request,
    holding_id: uuid.UUID,
    data: ExternalPEDividendCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """PE-Dividende anlegen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.private_equity import DividendCreate, create_dividend_core

    audit_log = _mk_re_log(request, user, "pe_dividend_create", target_id=holding_id)
    result = await create_dividend_core(
        db, user, holding_id, DividendCreate(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )
    return filter_pe_holding(result)


@router.put("/private-equity/{holding_id}/dividends/{dividend_id}")
@limiter.limit(RATE_LIMIT)
async def pe_update_dividend_external(
    request: Request,
    holding_id: uuid.UUID,
    dividend_id: uuid.UUID,
    data: ExternalPEDividendUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """PE-Dividende aendern — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.private_equity import DividendUpdate, update_dividend_core

    audit_log = _mk_re_log(request, user, "pe_dividend_update", target_id=holding_id)
    result = await update_dividend_core(
        db, user, holding_id, dividend_id, DividendUpdate(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )
    return filter_pe_holding(result)


@router.delete("/private-equity/{holding_id}/dividends/{dividend_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def pe_delete_dividend_external(
    request: Request,
    holding_id: uuid.UUID,
    dividend_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """PE-Dividende loeschen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.private_equity import delete_dividend_core

    audit_log = _mk_re_log(request, user, "pe_dividend_delete", target_id=holding_id)
    await delete_dividend_core(db, user, holding_id, dividend_id, audit_log=audit_log)
    return Response(status_code=204)


# --- Edelmetalle (Write) ---


@router.post("/precious-metals", status_code=201)
@limiter.limit(RATE_LIMIT)
async def metal_create_item_external(
    request: Request,
    data: ExternalMetalCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Edelmetall-Bestand anlegen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.precious_metals import PreciousMetalCreate, create_metal_item_core

    audit_log = _mk_re_log(request, user, "metal_item_create")
    result = await create_metal_item_core(
        db, user, PreciousMetalCreate(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )
    return filter_metal_item(result)


@router.put("/precious-metals/{item_id}")
@limiter.limit(RATE_LIMIT)
async def metal_update_item_external(
    request: Request,
    item_id: uuid.UUID,
    data: ExternalMetalUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Edelmetall-Bestand aendern — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.precious_metals import PreciousMetalUpdate, update_metal_item_core

    audit_log = _mk_re_log(request, user, "metal_item_update", target_id=item_id)
    result = await update_metal_item_core(
        db, user, item_id, PreciousMetalUpdate(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )
    return filter_metal_item(result)


@router.delete("/precious-metals/{item_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def metal_delete_item_external(
    request: Request,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Edelmetall-Bestand loeschen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.precious_metals import delete_metal_item_core

    audit_log = _mk_re_log(request, user, "metal_item_delete", target_id=item_id)
    await delete_metal_item_core(db, user, item_id, audit_log=audit_log)
    return Response(status_code=204)


@router.post("/precious-metals/expenses", status_code=201)
@limiter.limit(RATE_LIMIT)
async def metal_create_expense_external(
    request: Request,
    data: ExternalMetalExpenseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Edelmetall-Ausgabe anlegen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.precious_metals import ExpenseCreate as MetalExpenseCreate, create_metal_expense_core

    audit_log = _mk_re_log(request, user, "metal_expense_create")
    result = await create_metal_expense_core(
        db, user, MetalExpenseCreate(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )
    return filter_metal_expense(result)


@router.put("/precious-metals/expenses/{expense_id}")
@limiter.limit(RATE_LIMIT)
async def metal_update_expense_external(
    request: Request,
    expense_id: uuid.UUID,
    data: ExternalMetalExpenseUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Edelmetall-Ausgabe aendern — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.precious_metals import ExpenseUpdate as MetalExpenseUpdate, update_metal_expense_core

    audit_log = _mk_re_log(request, user, "metal_expense_update", target_id=expense_id)
    result = await update_metal_expense_core(
        db, user, expense_id, MetalExpenseUpdate(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )
    return filter_metal_expense(result)


@router.delete("/precious-metals/expenses/{expense_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def metal_delete_expense_external(
    request: Request,
    expense_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Edelmetall-Ausgabe loeschen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.precious_metals import delete_metal_expense_core

    audit_log = _mk_re_log(request, user, "metal_expense_delete", target_id=expense_id)
    await delete_metal_expense_core(db, user, expense_id, audit_log=audit_log)
    return Response(status_code=204)


# --- Dividenden (Write) — Pending confirm/dismiss ---


@router.post("/dividends/{pending_id}/confirm", status_code=201)
@limiter.limit(RATE_LIMIT)
async def dividend_confirm_external(
    request: Request,
    pending_id: uuid.UUID,
    data: ExternalDividendConfirm,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Pending-Dividende bestaetigen (bucht Dividenden-Transaktion) — Paritaet
    zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.dividends import ConfirmDividendRequest, confirm_pending_dividend_core

    audit_log = _mk_re_log(request, user, "dividend_confirm", target_id=pending_id)
    return await confirm_pending_dividend_core(
        db, user, pending_id, ConfirmDividendRequest(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )


@router.post("/dividends/{pending_id}/dismiss")
@limiter.limit(RATE_LIMIT)
async def dividend_dismiss_external(
    request: Request,
    pending_id: uuid.UUID,
    data: ExternalDividendDismiss,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Pending-Dividende verwerfen — Paritaet zum UI. Erfordert Scope ``write``."""
    require_scope(request, "write")
    from api.dividends import DismissDividendRequest, dismiss_pending_dividend_core

    audit_log = _mk_re_log(request, user, "dividend_dismiss", target_id=pending_id)
    return await dismiss_pending_dividend_core(
        db, user, pending_id, DismissDividendRequest(**data.model_dump(exclude_unset=True)), audit_log=audit_log,
    )


# --- Performance-Aktionen (Write) ---


@router.post("/performance/recalculate")
@limiter.limit(RATE_LIMIT)
async def performance_recalculate_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Cost-Basis aller Positionen aus Transaktionen neu rechnen + Snapshot-Regen
    — Paritaet zum UI (POST /api/performance/recalculate). Scope ``write``."""
    require_scope(request, "write")
    from datetime import date as _date
    from services.recalculate_service import recalculate_all_positions
    from services.snapshot_trigger import trigger_snapshot_regen

    db.add(_mk_re_log(request, user, "performance_recalculate"))
    results = await recalculate_all_positions(db, user_id=user.id)
    positions = [
        {
            "ticker": r["ticker"],
            "old_cost_basis_chf": r["old_cost_basis_chf"],
            "new_cost_basis_chf": r["new_cost_basis_chf"],
            "delta_chf": round(r["new_cost_basis_chf"] - r["old_cost_basis_chf"], 2),
        }
        for r in results
        if "error" not in r
    ]
    trigger_snapshot_regen(user.id, _date(2000, 1, 1))
    return {"recalculated": len(positions), "positions": positions, "snapshots_regenerating": True}


@router.post("/performance/fix-total-chf")
@limiter.limit(RATE_LIMIT)
async def performance_fix_total_chf_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """total_chf aus fx_rate_to_chf fuer Fremdwaehrungs-Transaktionen korrigieren
    — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from services.transaction_service import fix_foreign_total_chf

    db.add(_mk_re_log(request, user, "performance_fix_total_chf"))
    result = await fix_foreign_total_chf(db, user.id)
    await db.commit()
    return result


@router.post("/performance/regenerate-snapshots")
@limiter.limit(RATE_LIMIT)
async def performance_regenerate_snapshots_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Alle Portfolio-Snapshots aus Ledger + Historie neu bauen — Paritaet zum
    UI. Scope ``write``."""
    require_scope(request, "write")
    from services.snapshot_service import regenerate_snapshots

    db.add(_mk_re_log(request, user, "performance_regen_snapshots"))
    result = await regenerate_snapshots(db, user.id)
    await db.commit()
    return result


@router.post("/performance/earnings/refresh")
@limiter.limit(RATE_LIMIT)
async def performance_earnings_refresh_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Naechste Earnings-Termine aller aktiven Stock/ETF-Positionen aktualisieren
    — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from services.earnings_service import refresh_all_earnings

    db.add(_mk_re_log(request, user, "performance_earnings_refresh"))
    result = await refresh_all_earnings(db, user.id)
    await db.commit()
    return result


# --- Screening-Scan (Write) ---


@router.post("/screening/scan", status_code=201)
@limiter.limit("1/day")
async def screening_scan_external(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Neuen Screening-Scan starten (Fortschritt via GET /screening/scan/{id}/
    progress) — Paritaet zum UI. Scope ``write``. Hartes 1/Tag-Limit wie intern."""
    require_scope(request, "write")
    from api.screening import _run_scan_background

    scan = ScreeningScan(status="pending", steps=[])
    db.add(scan)
    db.add(_mk_re_log(request, user, "screening_scan"))
    await db.commit()
    await db.refresh(scan)
    background_tasks.add_task(_run_scan_background, scan.id)
    return {"scan_id": str(scan.id), "status": "pending"}


# --- ETF-Sektor-Gewichte (Write) ---


@router.put("/etf-sectors/{ticker}")
@limiter.limit(RATE_LIMIT)
async def etf_sectors_put_external(
    request: Request,
    ticker: str,
    body: ExternalEtfSectorWeights,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """ETF-Sektorgewichte setzen (ersetzt bestehende) — Paritaet zum UI.
    Summe muss 100% (+/-0.1) ergeben. Scope ``write``."""
    require_scope(request, "write")
    from sqlalchemy import delete as _delete
    from models.etf_sector_weight import EtfSectorWeight
    from services.sector_mapping import FINVIZ_SECTORS

    valid = set(FINVIZ_SECTORS)
    for s in body.sectors:
        if s.sector not in valid:
            raise HTTPException(400, f"Ungueltiger Sektor: {s.sector}")
        if not (0.0 <= s.weight_pct <= 100.0):
            raise HTTPException(400, f"Gewichtung muss zwischen 0 und 100 liegen: {s.sector}")
    total = sum(s.weight_pct for s in body.sectors)
    if not (99.9 <= total <= 100.1):
        raise HTTPException(400, f"Summe muss 100% ergeben (aktuell: {total:.1f}%)")

    tkr = ticker.upper()
    await db.execute(_delete(EtfSectorWeight).where(
        EtfSectorWeight.ticker == tkr, EtfSectorWeight.user_id == user.id,
    ))
    for s in body.sectors:
        if s.weight_pct > 0:
            db.add(EtfSectorWeight(user_id=user.id, ticker=tkr, sector=s.sector, weight_pct=s.weight_pct))
    db.add(_mk_re_log(request, user, "etf_sector_update"))
    await db.commit()
    return {"ticker": tkr, "sectors": [{"sector": s.sector, "weight_pct": s.weight_pct} for s in sorted(body.sectors, key=lambda x: x.weight_pct, reverse=True)]}


@router.delete("/etf-sectors/{ticker}")
@limiter.limit(RATE_LIMIT)
async def etf_sectors_delete_external(
    request: Request,
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """ETF-Sektorgewichte loeschen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from sqlalchemy import delete as _delete
    from models.etf_sector_weight import EtfSectorWeight

    await db.execute(_delete(EtfSectorWeight).where(
        EtfSectorWeight.ticker == ticker.upper(), EtfSectorWeight.user_id == user.id,
    ))
    db.add(_mk_re_log(request, user, "etf_sector_delete"))
    await db.commit()
    return {"status": "deleted", "ticker": ticker.upper()}


# --- EPS-Scanner-Schwellen (Write) ---


@router.patch("/eps-scanner/thresholds")
@limiter.limit(RATE_LIMIT)
async def eps_thresholds_patch_external(
    request: Request,
    data: ExternalEpsThresholds,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """EPS-Scanner-Filterschwellen setzen (user-scoped) — Paritaet zum UI.
    Scope ``write``."""
    require_scope(request, "write")
    db.add(_mk_re_log(request, user, "eps_thresholds_update"))
    t = await eps_svc.update_thresholds(
        db, user.id,
        yoy=data.super_quarter_yoy_pct,
        accel=data.acceleration_margin_pp,
        outlier=data.outlier_multiplier,
    )
    await db.commit()
    return {
        "super_quarter_yoy_pct": t.yoy_threshold,
        "acceleration_margin_pp": t.acceleration_margin,
        "outlier_multiplier": t.outlier_multiplier,
    }


# --- Analyse: Resistance + Watchlist-Tags (Write) ---


@router.put("/analysis/resistance/{ticker}")
@limiter.limit(RATE_LIMIT)
async def resistance_put_external(
    request: Request,
    ticker: str,
    data: ExternalResistanceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Manuelles Resistance-Level fuer einen Ticker setzen (Positionen +
    Watchlist) — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from services import cache

    tkr = ticker.upper()
    updated = False
    pos_rows = await db.execute(select(Position).where(
        (Position.ticker == tkr) | (Position.yfinance_ticker == tkr),
        Position.is_active == True, Position.user_id == user.id,
    ))
    for pos in pos_rows.scalars().all():
        pos.manual_resistance = data.manual_resistance
        updated = True
    wl_rows = await db.execute(select(WatchlistItem).where(
        WatchlistItem.ticker == tkr, WatchlistItem.is_active == True,
        WatchlistItem.user_id == user.id,
    ))
    for item in wl_rows.scalars().all():
        item.manual_resistance = data.manual_resistance
        updated = True
    db.add(_mk_re_log(request, user, "resistance_update"))
    await db.commit()
    cache.delete(f"scorer_data:{tkr}")
    return {"ticker": tkr, "manual_resistance": data.manual_resistance, "updated": updated}


@router.post("/watchlist/{item_id}/tags", status_code=201)
@limiter.limit(RATE_LIMIT)
async def watchlist_tag_add_external(
    request: Request,
    item_id: uuid.UUID,
    data: ExternalTagCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Tag an Watchlist-Eintrag haengen (find-or-create) — Paritaet zum UI.
    Scope ``write``."""
    require_scope(request, "write")
    from constants.limits import MAX_WATCHLIST_TAGS_PER_USER
    from models.watchlist_tag import WatchlistTag, watchlist_item_tags

    TAG_PALETTE = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899", "#06B6D4", "#6B7280"]

    item = await db.get(WatchlistItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Watchlist-Eintrag nicht gefunden")
    cnt = await db.scalar(select(func.count()).select_from(watchlist_item_tags).where(
        watchlist_item_tags.c.watchlist_item_id == item_id,
    ))
    if (cnt or 0) >= 5:
        raise HTTPException(status_code=400, detail="Max. 5 Tags pro Eintrag")
    tag_name = data.name.strip()[:30]
    tag = (await db.execute(select(WatchlistTag).where(
        WatchlistTag.user_id == user.id,
        func.lower(WatchlistTag.name) == tag_name.lower(),
    ))).scalars().first()
    if not tag:
        tag_count = await db.scalar(select(func.count()).select_from(WatchlistTag).where(
            WatchlistTag.user_id == user.id,
        )) or 0
        if tag_count >= MAX_WATCHLIST_TAGS_PER_USER:
            raise HTTPException(400, f"Tag-Limit erreicht (max. {MAX_WATCHLIST_TAGS_PER_USER} Tags)")
        idx = tag_count % len(TAG_PALETTE)
        tag = WatchlistTag(user_id=user.id, name=tag_name, color=data.color or TAG_PALETTE[idx])
        db.add(tag)
        await db.flush()
    existing = await db.execute(select(watchlist_item_tags).where(
        watchlist_item_tags.c.watchlist_item_id == item_id,
        watchlist_item_tags.c.tag_id == tag.id,
    ))
    if existing.first():
        return {"id": str(tag.id), "name": tag.name, "color": tag.color}
    await db.execute(watchlist_item_tags.insert().values(watchlist_item_id=item_id, tag_id=tag.id))
    db.add(_mk_re_log(request, user, "watchlist_tag_add", target_id=item_id))
    await db.commit()
    return {"id": str(tag.id), "name": tag.name, "color": tag.color}


@router.delete("/watchlist/{item_id}/tags/{tag_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def watchlist_tag_remove_external(
    request: Request,
    item_id: uuid.UUID,
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Tag von Watchlist-Eintrag entfernen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from models.watchlist_tag import watchlist_item_tags

    item = await db.get(WatchlistItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Watchlist-Eintrag nicht gefunden")
    await db.execute(watchlist_item_tags.delete().where(
        watchlist_item_tags.c.watchlist_item_id == item_id,
        watchlist_item_tags.c.tag_id == tag_id,
    ))
    db.add(_mk_re_log(request, user, "watchlist_tag_remove", target_id=item_id))
    await db.commit()
    return Response(status_code=204)


# --- Settings + Onboarding (Write) — ohne Secrets ---


@router.patch("/settings")
@limiter.limit(RATE_LIMIT)
async def settings_patch_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Benutzer-Einstellungen aendern (Basiswaehrung, Stop-Loss-Defaults, Alert-
    Toggles, Formate) — Paritaet zum UI. Secrets (API-Keys/SMTP/ntfy) sind hier
    bewusst NICHT erreichbar. Scope ``write``."""
    require_scope(request, "write")
    from api.settings import SettingsUpdate
    from services import settings_service as svc

    body = await request.json()
    data = SettingsUpdate(**(body or {}))
    db.add(_mk_re_log(request, user, "settings_update"))
    result = await svc.update_settings(db, user.id, data.model_dump(exclude_unset=True))
    return filter_settings(result if isinstance(result, dict) else {})


@router.put("/settings/alert-preferences")
@limiter.limit(RATE_LIMIT)
async def alert_preferences_put_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Alert-Praeferenz pro Kategorie setzen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from api.settings import AlertPrefUpdate
    from services import settings_service as svc

    body = await request.json()
    data = AlertPrefUpdate(**(body or {}))
    db.add(_mk_re_log(request, user, "alert_pref_update"))
    return await svc.update_alert_preference(
        db, user.id, data.category, data.is_enabled,
        data.notify_in_app, data.notify_email, data.notify_push,
    )


@router.post("/settings/onboarding/tour-complete")
@limiter.limit(RATE_LIMIT)
async def onboarding_tour_complete_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Onboarding-Tour als abgeschlossen markieren — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from services import settings_service as svc

    db.add(_mk_re_log(request, user, "onboarding_update"))
    result = await svc.mark_tour_complete(db, user.id)
    return result if isinstance(result, dict) else {"status": "ok"}


@router.post("/settings/onboarding/hide-checklist")
@limiter.limit(RATE_LIMIT)
async def onboarding_hide_checklist_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Onboarding-Checkliste ausblenden — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from services import settings_service as svc

    db.add(_mk_re_log(request, user, "onboarding_update"))
    result = await svc.hide_checklist(db, user.id)
    return result if isinstance(result, dict) else {"status": "ok"}


@router.post("/settings/onboarding/step-complete")
@limiter.limit(RATE_LIMIT)
async def onboarding_step_complete_external(
    request: Request,
    data: ExternalOnboardingStep,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Onboarding-Schritt als erledigt markieren — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from services import settings_service as svc

    db.add(_mk_re_log(request, user, "onboarding_update"))
    result = await svc.mark_step_complete(db, user.id, data.step)
    return result if isinstance(result, dict) else {"status": "ok"}


# --- Buckets (Write) — volle Paritaet zum internen UI ---
#
# Bucket-Schemas (BucketCreate/Update etc.) werden vom internen Modul
# wiederverwendet: sie tragen ein verschachteltes ``risk_rules``-Modell, dessen
# 1:1-Nachbau die Drift-Gefahr eher erhoeht als senkt. Die Response wird ueber
# ``filter_bucket`` auf den stabilen externen Vertrag verengt.


@router.post("/buckets", status_code=201)
@limiter.limit(RATE_LIMIT)
async def bucket_create_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Bucket anlegen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from api.buckets import BucketCreate, BucketOut, _validate_benchmark
    from services.bucket_service import BucketError, create_bucket

    payload = BucketCreate(**(await request.json() or {}))
    benchmark = _validate_benchmark(payload.benchmark)
    rules = payload.risk_rules.model_dump(exclude_none=True) if payload.risk_rules is not None else None
    try:
        bucket = await create_bucket(
            db, user.id, name=payload.name, color=payload.color, benchmark=benchmark,
            target_pct=payload.target_pct, target_chf=payload.target_chf,
            description=payload.description, risk_rules=rules, sort_order=payload.sort_order,
        )
    except BucketError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.add(_mk_re_log(request, user, "bucket_create", target_id=bucket.id))
    await db.commit()
    return filter_bucket(BucketOut.from_model(bucket).model_dump())


@router.patch("/buckets/{bucket_id}")
@limiter.limit(RATE_LIMIT)
async def bucket_update_external(
    request: Request,
    bucket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Bucket aendern — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from api.buckets import BucketUpdate, BucketOut, _validate_benchmark
    from services.bucket_service import BucketError, update_bucket

    payload = BucketUpdate(**(await request.json() or {}))
    benchmark = _validate_benchmark(payload.benchmark) if payload.benchmark is not None else None
    rules = payload.risk_rules.model_dump(exclude_none=True) if payload.risk_rules is not None else None
    try:
        bucket = await update_bucket(
            db, user.id, bucket_id, name=payload.name, color=payload.color, benchmark=benchmark,
            target_pct=payload.target_pct, target_chf=payload.target_chf,
            description=payload.description, risk_rules=rules, sort_order=payload.sort_order,
        )
    except BucketError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.add(_mk_re_log(request, user, "bucket_update", target_id=bucket_id))
    await db.commit()
    return filter_bucket(BucketOut.from_model(bucket).model_dump())


@router.delete("/buckets/{bucket_id}")
@limiter.limit(RATE_LIMIT)
async def bucket_delete_external(
    request: Request,
    bucket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Bucket loeschen (Positionen wandern in den Liquid-Default) — Paritaet zum
    UI. Scope ``write``."""
    require_scope(request, "write")
    from services.bucket_service import BucketError, delete_bucket

    try:
        moved = await delete_bucket(db, user.id, bucket_id)
    except BucketError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.add(_mk_re_log(request, user, "bucket_delete", target_id=bucket_id))
    await db.commit()
    if moved > 0:
        from api.portfolio import invalidate_portfolio_cache
        invalidate_portfolio_cache(str(user.id))
    return {"deleted": True, "positions_moved": moved}


@router.post("/buckets/from-template", status_code=201)
@limiter.limit(RATE_LIMIT)
async def bucket_from_template_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Bucket-Set aus Vorlage anlegen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from api.buckets import TemplateApply, BucketOut
    from services.bucket_service import BucketError
    from services.bucket_templates import apply_template

    payload = TemplateApply(**(await request.json() or {}))
    try:
        created = await apply_template(db, user.id, payload.template_key, replace_existing=payload.replace_existing)
    except BucketError as e:
        await db.rollback()
        msg = str(e)
        if msg.startswith("Bucket-Namen existieren bereits"):
            raise HTTPException(status_code=409, detail={"error": "bucket_name_conflict", "message": msg, "can_replace": True})
        raise HTTPException(status_code=400, detail=msg)
    db.add(_mk_re_log(request, user, "bucket_from_template"))
    await db.commit()
    return {"created": [filter_bucket(BucketOut.from_model(b).model_dump()) for b in created], "count": len(created)}


@router.post("/buckets/migration-rollback")
@limiter.limit(RATE_LIMIT)
async def bucket_migration_rollback_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Bucket-Migration zurueckrollen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from services.bucket_service import migration_rollback

    result = await migration_rollback(db, user.id)
    db.add(_mk_re_log(request, user, "bucket_migration_rollback"))
    await db.commit()
    if result.get("positions_moved", 0) > 0:
        from api.portfolio import invalidate_portfolio_cache
        invalidate_portfolio_cache(str(user.id))
    return result


@router.post("/positions/by-id/{position_id}/split-to-bucket")
@limiter.limit(RATE_LIMIT)
async def bucket_split_position_external(
    request: Request,
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Position teilweise in anderen Bucket splitten — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from api.buckets import SplitPosition
    from services.bucket_service import BucketError, split_position_to_bucket

    payload = SplitPosition(**(await request.json() or {}))
    try:
        target_uuid = uuid.UUID(payload.target_bucket_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungueltige Bucket-ID")
    try:
        original, new_pos = await split_position_to_bucket(
            db, user.id, position_id, target_uuid, split_pct=payload.split_pct, note=payload.note,
        )
    except BucketError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.add(_mk_re_log(request, user, "bucket_split_position", target_id=position_id))
    await db.commit()
    from api.portfolio import invalidate_portfolio_cache
    invalidate_portfolio_cache(str(user.id))
    return {
        "original_position": {"id": str(original.id), "shares": float(original.shares), "cost_basis_chf": float(original.cost_basis_chf)},
        "new_position": {"id": str(new_pos.id), "bucket_id": str(new_pos.bucket_id), "shares": float(new_pos.shares), "cost_basis_chf": float(new_pos.cost_basis_chf)},
    }


@router.post("/positions/by-id/{position_id}/move-to-bucket")
@limiter.limit(RATE_LIMIT)
async def bucket_move_position_external(
    request: Request,
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Position in anderen Bucket verschieben — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from api.buckets import MovePosition
    from services.bucket_service import BucketError, move_position_to_bucket

    payload = MovePosition(**(await request.json() or {}))
    try:
        target_uuid = uuid.UUID(payload.target_bucket_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungueltige Bucket-ID")
    try:
        position = await move_position_to_bucket(
            db, user.id, position_id, target_uuid, changed_by="user",
            note=payload.note, keep_risk_rules=payload.keep_risk_rules,
        )
    except BucketError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.add(_mk_re_log(request, user, "bucket_move_position", target_id=position_id))
    await db.commit()
    from api.portfolio import invalidate_portfolio_cache
    invalidate_portfolio_cache(str(user.id))
    return {"position_id": str(position.id), "ticker": position.ticker, "bucket_id": str(position.bucket_id)}


@router.post("/buckets/import-rules", status_code=201)
@limiter.limit(RATE_LIMIT)
async def bucket_import_rule_create_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Import-Bucket-Mapping-Regel anlegen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from api.buckets import ImportRuleCreate
    from services.import_bucket_rule_service import ImportRuleError, create_rule

    payload = ImportRuleCreate(**(await request.json() or {}))
    try:
        bucket_uuid = uuid.UUID(payload.bucket_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungueltige Bucket-ID")
    try:
        rule = await create_rule(
            db, user.id, bucket_id=bucket_uuid, source=payload.source,
            ticker_pattern=payload.ticker_pattern, priority=payload.priority,
        )
    except ImportRuleError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.add(_mk_re_log(request, user, "bucket_import_rule_create", target_id=rule.id))
    await db.commit()
    return {
        "id": str(rule.id), "bucket_id": str(rule.bucket_id), "source": rule.source,
        "ticker_pattern": rule.ticker_pattern, "priority": rule.priority,
    }


@router.delete("/buckets/import-rules/{rule_id}")
@limiter.limit(RATE_LIMIT)
async def bucket_import_rule_delete_external(
    request: Request,
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Import-Bucket-Mapping-Regel loeschen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from services.import_bucket_rule_service import delete_rule

    deleted = await delete_rule(db, user.id, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Regel nicht gefunden")
    db.add(_mk_re_log(request, user, "bucket_import_rule_del", target_id=rule_id))
    await db.commit()
    return {"deleted": True}


@router.post("/buckets/backfill-snapshots")
@limiter.limit(RATE_LIMIT)
async def bucket_backfill_snapshots_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Bucket-Snapshots rueckwirkend aus Portfolio-Snapshots backfillen — Paritaet
    zum UI. Scope ``write``."""
    require_scope(request, "write")
    from services.bucket_snapshot_backfill_service import backfill_bucket_snapshots

    result = await backfill_bucket_snapshots(db, user.id)
    db.add(_mk_re_log(request, user, "bucket_backfill_snapshots"))
    await db.commit()
    return result


@router.post("/buckets/onboarding-dismiss")
@limiter.limit(RATE_LIMIT)
async def bucket_onboarding_dismiss_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Bucket-Migrations-Modal ohne Rollback schliessen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from models.user import UserSettings

    settings = (await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))).scalar_one_or_none()
    if settings is not None:
        settings.noticed_buckets_migration = True
    db.add(_mk_re_log(request, user, "bucket_onboarding_dismiss"))
    await db.commit()
    return {"noticed_buckets_migration": True}


# --- Import-Flow (Write) — CSV-Upload, Mapping, Confirm, Profile ---
#
# parse/analyze/parse-with-mapping spiegeln die internen Multipart- bzw. JSON-
# Endpoints; ``confirm`` ist der eigentliche Schreibvorgang (Bulk-Insert +
# Recalc + Snapshot-Regen). Schemas (ConfirmRequest/ProfileCreate/
# ParseWithMappingRequest) werden vom internen Modul wiederverwendet.

_IMPORT_MAX_FILE = 10 * 1024 * 1024


@router.post("/import/parse")
@limiter.limit(RATE_LIMIT)
async def import_parse_external(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """CSV hochladen + parsen (Vorschau) — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from services.import_service import parse_csv

    fn = file.filename or ""
    if not fn.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Nur CSV-Dateien erlaubt")
    content = await file.read()
    if len(content) > _IMPORT_MAX_FILE:
        raise HTTPException(status_code=400, detail="Datei zu gross (max. 10 MB)")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Datei ist leer")
    try:
        preview = await parse_csv(content, fn, db, user_id=user.id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # Audit-Log erst NACH erfolgreichem Parse — ein 422 soll keinen
    # irrefuehrenden "Erfolgs"-Log hinterlassen (Audit v0.45 Finding #1).
    db.add(_mk_re_log(request, user, "import_parse"))
    await db.commit()
    return preview.model_dump() if hasattr(preview, "model_dump") else preview


@router.post("/import/analyze")
@limiter.limit(RATE_LIMIT)
async def import_analyze_external(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """CSV-Struktur analysieren (Encoding/Delimiter/Header/Broker) — Paritaet zum
    UI. Scope ``write`` (legt Temp-Upload an)."""
    require_scope(request, "write")
    from services.import_service import analyze_csv_structure

    fn = file.filename or ""
    if not fn.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Nur CSV-Dateien erlaubt")
    content = await file.read()
    if len(content) > _IMPORT_MAX_FILE:
        raise HTTPException(status_code=400, detail="Datei zu gross (max. 10 MB)")
    if not content:
        raise HTTPException(status_code=400, detail="Datei ist leer")
    try:
        result = await analyze_csv_structure(content, fn, db, user.id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # Log erst nach erfolgreicher Analyse (Audit v0.45 Finding #1).
    db.add(_mk_re_log(request, user, "import_parse"))
    await db.commit()
    return result


@router.post("/import/parse-with-mapping")
@limiter.limit(RATE_LIMIT)
async def import_parse_with_mapping_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Zuvor hochgeladene CSV mit explizitem Spalten-Mapping parsen — Paritaet
    zum UI. Scope ``write``."""
    require_scope(request, "write")
    import os as _os
    from api.imports import ParseWithMappingRequest, UPLOAD_DIR
    from services.import_service import parse_csv

    data = ParseWithMappingRequest(**(await request.json() or {}))
    try:
        uuid.UUID(data.upload_id)
    except ValueError:
        raise HTTPException(400, "Ungueltige Upload-ID")
    user_dir = _os.path.join(UPLOAD_DIR, str(user.id))
    filepath = _os.path.join(user_dir, f"{data.upload_id}.csv")
    if not _os.path.realpath(filepath).startswith(_os.path.realpath(user_dir) + _os.sep):
        raise HTTPException(400, "Ungueltige Upload-ID")
    if not _os.path.exists(filepath):
        raise HTTPException(404, "Upload nicht gefunden. Bitte CSV erneut hochladen.")
    with open(filepath, "rb") as f:
        content = f.read()
    column_mapping, type_mapping, date_format = data.column_mapping, data.type_mapping, data.date_format
    if data.profile_id:
        from models.import_profile import ImportProfile
        try:
            profile_uuid = uuid.UUID(data.profile_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Ungueltige Profil-ID")
        profile = await db.get(ImportProfile, profile_uuid)
        if profile and profile.user_id == user.id:
            column_mapping, type_mapping = profile.column_mapping, profile.type_mapping
            if profile.date_format:
                date_format = profile.date_format
    try:
        preview = await parse_csv(
            content, f"upload_{data.upload_id}.csv", db,
            user_mapping=column_mapping, user_id=user.id, type_mapping=type_mapping,
            broker_defaults=data.broker_defaults, total_chf_formula=data.total_chf_formula,
            date_format=date_format,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    # Log erst nach erfolgreichem Parse (Audit v0.45 Finding #1).
    db.add(_mk_re_log(request, user, "import_parse"))
    await db.commit()
    return preview.model_dump() if hasattr(preview, "model_dump") else preview


@router.post("/import/confirm", status_code=201)
@limiter.limit(RATE_LIMIT)
async def import_confirm_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Geparste Transaktionen bestaetigen + bulk-inserten (inkl. Recalc +
    Snapshot-Regen) — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    import asyncio as _asyncio
    from api.imports import ConfirmRequest, _bg_tasks
    from db import async_session
    from services.import_service import confirm_import
    from services.recalculate_service import recalculate_all_positions

    data = ConfirmRequest(**(await request.json() or {}))
    db.add(_mk_re_log(request, user, "import_confirm"))
    txn_dicts = [t.model_dump(exclude_none=True) for t in data.transactions]
    pos_dicts = [p.model_dump(exclude_none=True) for p in data.new_positions]
    fx_dicts = [f.model_dump(exclude_none=True) for f in data.fx_transactions]
    result = await confirm_import(txn_dicts, pos_dicts, db, user.id, fx_transactions=fx_dicts)
    recalc_results = await recalculate_all_positions(db, user_id=user.id)
    result["recalculated_positions"] = len([r for r in recalc_results if "error" not in r])

    async def _regenerate_bg(uid):
        from services.snapshot_service import regenerate_snapshots
        try:
            async with async_session() as bg_db:
                await regenerate_snapshots(bg_db, uid)
        except Exception as exc:
            logger.error(f"Background snapshot regeneration failed: {exc}", exc_info=True)

    task = _asyncio.create_task(_regenerate_bg(user.id))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    from api.portfolio import invalidate_portfolio_cache
    invalidate_portfolio_cache(str(user.id))
    return result


@router.get("/import/profiles")
@limiter.limit(RATE_LIMIT)
async def import_profiles_list_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> list:
    """Import-Profile auflisten — Paritaet zum UI."""
    from models.import_profile import ImportProfile

    rows = (await db.execute(
        select(ImportProfile).where(ImportProfile.user_id == user.id).order_by(ImportProfile.name)
    )).scalars().all()
    return [
        {
            "id": str(p.id), "name": p.name, "column_mapping": p.column_mapping,
            "type_mapping": p.type_mapping, "delimiter": p.delimiter, "encoding": p.encoding,
            "date_format": p.date_format, "decimal_separator": p.decimal_separator,
            "has_forex_pairs": p.has_forex_pairs, "aggregate_partial_fills": p.aggregate_partial_fills,
        }
        for p in rows
    ]


@router.post("/import/profiles", status_code=201)
@limiter.limit(RATE_LIMIT)
async def import_profile_create_external(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> dict:
    """Import-Profil anlegen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from api.imports import ProfileCreate
    from constants.limits import MAX_IMPORT_PROFILES_PER_USER
    from models.import_profile import ImportProfile

    data = ProfileCreate(**(await request.json() or {}))
    cnt = await db.scalar(select(func.count()).select_from(ImportProfile).where(ImportProfile.user_id == user.id)) or 0
    if cnt >= MAX_IMPORT_PROFILES_PER_USER:
        raise HTTPException(400, f"Limit erreicht (max. {MAX_IMPORT_PROFILES_PER_USER} Import-Profile)")
    profile = ImportProfile(
        user_id=user.id, name=data.name, column_mapping=data.column_mapping,
        type_mapping=data.type_mapping, delimiter=data.delimiter, encoding=data.encoding,
        date_format=data.date_format, decimal_separator=data.decimal_separator,
        has_forex_pairs=data.has_forex_pairs, aggregate_partial_fills=data.aggregate_partial_fills,
    )
    db.add(profile)
    await db.flush()
    log = _mk_re_log(request, user, "import_profile_create", target_id=profile.id)
    db.add(log)
    await db.commit()
    await db.refresh(profile)
    return {"id": str(profile.id), "name": profile.name}


@router.delete("/import/profiles/{profile_id}", status_code=204)
@limiter.limit(RATE_LIMIT)
async def import_profile_delete_external(
    request: Request,
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
) -> Response:
    """Import-Profil loeschen — Paritaet zum UI. Scope ``write``."""
    require_scope(request, "write")
    from models.import_profile import ImportProfile

    profile = await db.get(ImportProfile, profile_id)
    if not profile or profile.user_id != user.id:
        raise HTTPException(404, "Profil nicht gefunden")
    db.add(_mk_re_log(request, user, "import_profile_delete", target_id=profile_id))
    await db.delete(profile)
    await db.commit()
    return Response(status_code=204)
