import asyncio
import logging
import os
import time as _time
import uuid as _uuid
import yf_patch  # noqa: F401 — must be first to patch yfinance before any service imports

from contextlib import asynccontextmanager
from datetime import datetime

from dateutils import utcnow

from logging_config import setup_logging
setup_logging("api")

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from auth import get_current_user
from config import settings
from db import async_session, engine, get_db
from models import Base
from api.market import router as market_router
from api.portfolio import router as portfolio_router
from api.positions import router as positions_router
from api.stoploss import router as stoploss_router
from api.performance import router as performance_router
from api.analysis import router as analysis_router
from api.transactions import router as transactions_router
from api.imports import router as imports_router
from api.real_estate import router as real_estate_router
from api.stock import router as stock_router
from api.auth import router as auth_router
from api.settings import router as settings_router, export_router
from api.etf_sectors import router as etf_sectors_router
from api.taxonomy import router as taxonomy_router
from api.alerts import router as alerts_router
from api.admin import router as admin_router
from api.precious_metals import router as precious_metals_router
from api.private_equity import router as private_equity_router
from api.screening import router as screening_router
from api.external_v1 import router as external_v1_router

logger = logging.getLogger(__name__)


async def record_snapshot():
    """Record daily portfolio snapshot after price refresh."""
    from services.snapshot_service import record_daily_snapshot
    async with async_session() as db:
        count = await record_daily_snapshot(db)
        logger.info(f"Portfolio snapshots recorded: {count}")


async def create_admin_user():
    """Create initial admin user from ADMIN_EMAIL/ADMIN_PASSWORD env vars."""
    import os
    from sqlalchemy import select, func
    from models.user import User, UserSettings

    admin_email = settings.admin_email.strip().lower() if settings.admin_email else ""
    admin_password = settings.admin_password if settings.admin_password else ""

    if not admin_email or not admin_password:
        return

    try:
        from services.auth_service import hash_password, validate_password

        errors = validate_password(admin_password)
        if errors:
            logger.warning(f"Admin-Passwort ungültig: {', '.join(errors)}")
            return

        async with async_session() as db:
            result = await db.execute(select(User).where(func.lower(User.email) == admin_email))
            existing = result.scalars().first()

            if existing:
                if not existing.is_admin:
                    existing.is_admin = True
                    await db.commit()
                    logger.info(f"Admin-Recht gesetzt für: {admin_email}")
                else:
                    logger.info(f"Admin-User existiert bereits: {admin_email}")
            else:
                try:
                    user = User(email=admin_email, password_hash=hash_password(admin_password), is_admin=True)
                    db.add(user)
                    await db.commit()
                    await db.refresh(user)

                    user_settings = UserSettings(user_id=user.id)
                    db.add(user_settings)
                    await db.commit()

                    logger.info(f"Admin-User erstellt: {admin_email}")
                except IntegrityError:
                    await db.rollback()
                    logger.info(f"Admin-User existiert bereits: {admin_email}")
    except Exception as e:
        logger.error(f"Admin-User Erstellung fehlgeschlagen: {e}")
    finally:
        # Remove credentials from process environment
        os.environ.pop("ADMIN_EMAIL", None)
        os.environ.pop("ADMIN_PASSWORD", None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))

    # Warn on default DB credentials
    if "CHANGE_ME" in (settings.database_url or "") or "MUST_SET" in (settings.database_url or ""):
        logger.warning("SECURITY: Default database password detected. Change POSTGRES_PASSWORD in .env for production!")

    # Create initial admin user if configured
    await create_admin_user()

    # Migrate encrypted values from legacy key derivation
    try:
        from services.auth_service import migrate_encrypted_values
        migrated, errors = await migrate_encrypted_values()
        if migrated > 0:
            logger.info(f"Encryption migration: {migrated} Wert(e) migriert")
    except Exception as e:
        logger.warning(f"Encryption migration fehlgeschlagen: {e}")

    # Scheduler runs in separate worker container — no APScheduler here

    yield

    await engine.dispose()


_docs_enabled = os.getenv("ENABLE_API_DOCS", "false").lower() == "true"

app = FastAPI(
    title="OpenFolio API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# Rate limiting
from api.auth import limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if "*" in _cors_origins:
    logger.warning("CORS: Wildcard origin with credentials is insecure. Falling back to localhost.")
    _cors_origins = ["http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# Prometheus metrics
from middleware.metrics import metrics_middleware, metrics_endpoint
app.middleware("http")(metrics_middleware)
app.add_api_route("/metrics", metrics_endpoint, include_in_schema=False, dependencies=[Depends(get_current_user)])

# Request body size limit middleware (10 MB)
MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024  # 10 MB


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-XSS-Protection"] = "0"
    return response


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = str(_uuid.uuid4())[:8]
    request.state.request_id = request_id
    start = _time.monotonic()
    response = await call_next(request)
    duration_ms = round((_time.monotonic() - start) * 1000, 1)
    path = request.url.path
    if not path.startswith(("/api/health", "/metrics")):
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
    return response


@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    try:
        cl = int(content_length) if content_length else 0
    except (ValueError, TypeError):
        logger.debug(f"Could not parse content-length header: {content_length!r}")
        cl = 0
    if cl > MAX_REQUEST_BODY_SIZE:
        return JSONResponse(status_code=413, content={"detail": "Request body too large (max 10 MB)"})
    return await call_next(request)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", None)
    content = {"detail": exc.detail}
    if request_id:
        content["request_id"] = request_id
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=getattr(exc, "headers", None),
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    content = {"detail": "Interner Serverfehler"}
    if request_id:
        content["request_id"] = request_id
    return JSONResponse(
        status_code=500,
        content=content,
    )

app.include_router(auth_router)
app.include_router(market_router)
app.include_router(portfolio_router)
app.include_router(positions_router)
app.include_router(stoploss_router)
app.include_router(performance_router)
app.include_router(analysis_router)
app.include_router(transactions_router)
app.include_router(imports_router)
app.include_router(real_estate_router)
app.include_router(stock_router)
app.include_router(settings_router)
app.include_router(export_router)
app.include_router(etf_sectors_router)
app.include_router(taxonomy_router)
app.include_router(alerts_router)
app.include_router(admin_router)
app.include_router(precious_metals_router)
app.include_router(private_equity_router)
app.include_router(screening_router)
app.include_router(external_v1_router)


@app.get("/api/health")
async def health():
    db_status = "connected"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning(f"Health check: DB connection failed: {e}")
        db_status = "disconnected"
    redis_status = "connected"
    try:
        from services.cache import _get_redis
        r = _get_redis()
        if r:
            r.ping()
        else:
            redis_status = "unavailable"
    except Exception as e:
        logger.warning(f"Health check: Redis connection failed: {e}")
        redis_status = "disconnected"
    from version import APP_VERSION
    return {"status": "ok", "version": APP_VERSION, "db": db_status, "redis": redis_status}


@app.post("/api/errors")
@limiter.limit("10/minute")
async def report_frontend_error(request: Request):
    """Receive frontend error reports (no auth required, rate limited)."""
    try:
        raw = await request.body()
        if len(raw) > 10240:  # 10 KB limit
            return JSONResponse(status_code=413, content={"detail": "Request body too large"})
        body = await request.json()
        logger.error(
            "Frontend error",
            extra={
                "error_message": body.get("message", "unknown"),
                "error_stack": body.get("stack"),
                "component_stack": body.get("componentStack"),
                "url": body.get("url"),
                "user_agent": body.get("userAgent"),
                "client_timestamp": body.get("timestamp"),
            },
        )
    except Exception:
        logger.warning("Could not parse frontend error report")
    return {"ok": True}


@app.post("/api/cache/clear")
@limiter.limit("5/minute")
async def clear_cache(request: Request, user=Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    from services.cache import clear
    clear()
    return {"status": "cleared"}


@app.post("/api/cache/refresh")
@limiter.limit("5/minute")
async def refresh_cache_endpoint(request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    from services.cache_service import is_refreshing, get_refresh_state, refresh_cache, _save_refresh_state_to_db
    if await is_refreshing():
        state = await get_refresh_state()
        return JSONResponse(
            status_code=429,
            content={"status": "already_refreshing", "started_at": state.get("started_at")},
        )
    try:
        result = await asyncio.wait_for(refresh_cache(db), timeout=60)
    except asyncio.TimeoutError:
        logger.error("Cache refresh timed out after 60s")
        await _save_refresh_state_to_db({
            "refreshing": False, "started_at": None, "ticker_count": 0,
            "status": "timeout", "last_refresh": None,
            "errors": ["Refresh abgebrochen nach 60s"],
        })
        result = {"status": "timeout", "error": "Abgebrochen nach 60s"}

    # Record daily snapshot after price refresh (keeps monthly returns up to date)
    try:
        await record_snapshot()
    except Exception as e:
        logger.warning(f"Snapshot after cache refresh failed: {e}")

    return result


@app.get("/api/cache/status")
async def cache_status(user=Depends(get_current_user)):
    from services.cache_service import get_refresh_state
    state = await get_refresh_state()
    age_minutes = None
    if state.get("last_refresh"):
        try:
            last = datetime.fromisoformat(state["last_refresh"].replace("Z", "+00:00"))
            age_minutes = int((datetime.now(last.tzinfo) - last).total_seconds() / 60)
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not parse last_refresh timestamp: {e}")
    return {**state, "age_minutes": age_minutes}


@app.get("/api/search/symbols")
async def search_symbols(q: str = "", limit: int = 8, user=Depends(get_current_user)):
    """Search for stock/ETF symbols with autocomplete."""
    from services import cache as app_cache
    from services.api_utils import fetch_json

    if not q or len(q) < 1:
        return {"results": []}

    cache_key = f"symbol_search:{q.lower()}"
    cached = app_cache.get(cache_key)
    if cached is not None:
        return {"results": cached}

    try:
        url = "https://query2.finance.yahoo.com/v1/finance/search"
        params = {
            "q": q,
            "quotesCount": limit,
            "newsCount": 0,
            "listsCount": 0,
            "enableFuzzyQuery": False,
            "quotesQueryId": "tss_match_phrase_query",
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        data = await fetch_json(url, params=params, headers=headers, timeout=5)

        results = []
        for quote in data.get("quotes", []):
            if quote.get("quoteType") in ("EQUITY", "ETF"):
                results.append({
                    "ticker": quote.get("symbol", ""),
                    "name": quote.get("longname") or quote.get("shortname", ""),
                    "exchange": quote.get("exchange", ""),
                    "type": quote.get("quoteType", "").lower(),
                    "sector": quote.get("sector", ""),
                    "industry": quote.get("industry", ""),
                })

        app_cache.set(cache_key, results, ttl=300)
        return {"results": results}
    except Exception as e:
        logger.warning(f"Symbol search failed: {e}")
        return {"results": []}


@app.get("/api/alerts")
async def get_alerts(db=Depends(get_db), user=Depends(get_current_user)):
    from services.portfolio_service import get_portfolio_summary
    from services.market_analyzer import get_market_climate
    from services.alert_service import generate_alerts

    from sqlalchemy import select as sa_select
    from models.user import UserSettings
    from models.alert_preference import AlertPreference
    from services.settings_service import settings_to_dict as _settings_to_dict

    # Reuse cached summary from portfolio endpoint if available
    from services import cache as app_cache
    from api.portfolio import _SUMMARY_TTL
    cache_key = f"portfolio_summary:{user.id}"
    cached = app_cache.get(cache_key)
    if cached:
        summary = cached
    else:
        summary = await get_portfolio_summary(db, user.id)
        app_cache.set(cache_key, summary, ttl=_SUMMARY_TTL)
    climate = await asyncio.to_thread(get_market_climate)

    # Load watchlist tickers with MA data for ETF 200-DMA alerts
    from models.watchlist import WatchlistItem
    from services.utils import compute_moving_averages, prefetch_close_series
    from services.sector_mapping import is_broad_etf
    wl_result = await db.execute(
        sa_select(WatchlistItem).where(WatchlistItem.user_id == user.id)
    )
    wl_items = wl_result.scalars().all()

    # Pre-filter broad ETF tickers and batch-prefetch close series (C-1 fix)
    broad_etf_tickers = [w.ticker for w in wl_items if is_broad_etf(w.ticker)]
    if broad_etf_tickers:
        await asyncio.to_thread(prefetch_close_series, broad_etf_tickers)

    # Compute all MAs in a single thread to avoid blocking the event loop
    def _compute_watchlist_mas():
        ma_results = {}
        for ticker in broad_etf_tickers:
            mas = compute_moving_averages(ticker, [200])
            current = mas.get("current")
            ma200 = mas.get("ma200")
            ma_results[ticker] = current > ma200 if current is not None and ma200 is not None else None
        return ma_results

    ma_map = await asyncio.to_thread(_compute_watchlist_mas) if broad_etf_tickers else {}

    watchlist_tickers: list[dict] = []
    for w in wl_items:
        watchlist_tickers.append({
            "ticker": w.ticker,
            "name": w.name or w.ticker,
            "ma_detail": {"above_ma200": ma_map.get(w.ticker)},
        })

    result = await db.execute(sa_select(UserSettings).where(UserSettings.user_id == user.id))
    user_settings = result.scalars().first()
    prefs = _settings_to_dict(user_settings) if user_settings else {}

    alerts = generate_alerts(summary.get("positions", []), climate, prefs, watchlist_tickers=watchlist_tickers)

    # Load alert preferences to filter by enabled + notify_in_app
    pref_result = await db.execute(
        sa_select(AlertPreference).where(AlertPreference.user_id == user.id)
    )
    pref_map = {p.category: p for p in pref_result.scalars().all()}

    # Map alert_service categories to preference categories
    CATEGORY_MAP = {
        "stop_loss_missing": "stop_missing",
        "stop_loss_unconfirmed": "stop_unconfirmed",
        "stop_proximity": "stop_proximity",
        "stop_reached": "stop_proximity",
        "stop_loss_review": "stop_review",
        "stop_loss_age": "stop_review",
        "ma_critical": "ma_critical",
        "ma_warning": "ma_warning",
        "position_limit": "position_limit",
        "sector_limit": "sector_limit",
        "loss": "loss",
        "market": "market_climate",
        "vix": "vix",
        "earnings": "earnings",
        "allocation_satellite": "allocation",
        "allocation_core": "allocation",
        "position_type_missing": "position_type_missing",
        "etf_200dma_buy": "etf_200dma_buy",
    }

    # Filter alerts by preference (default: enabled + in-app)
    filtered = []
    for a in alerts:
        cat = CATEGORY_MAP.get(a.get("category", ""), "")
        p = pref_map.get(cat)
        if p:
            if not p.is_enabled or not p.notify_in_app:
                continue
        filtered.append(a)
    alerts = filtered

    # Add recently triggered price alerts
    price_alert_pref = pref_map.get("price_alert")
    show_price_alerts = not price_alert_pref or (price_alert_pref.is_enabled and price_alert_pref.notify_in_app)

    if show_price_alerts:
        from datetime import timedelta
        from sqlalchemy import select as sa_sel2
        from models.price_alert import PriceAlert
        cutoff = utcnow() - timedelta(days=7)
        pa_result = await db.execute(
            sa_sel2(PriceAlert).where(
                PriceAlert.user_id == user.id,
                PriceAlert.is_triggered == True,
                PriceAlert.triggered_at >= cutoff,
            ).order_by(PriceAlert.triggered_at.desc())
        )
        type_labels = {"price_above": "über", "price_below": "unter", "pct_change_day": "Tagesveränderung über"}
        for pa in pa_result.scalars().all():
            target_str = f"{pa.target_value}%" if pa.alert_type == "pct_change_day" else f"{pa.currency or 'CHF'} {float(pa.target_value):.2f}"
            alerts.insert(0, {
                "severity": "info",
                "category": "price_alert",
                "message": f"Preis-Alarm: {pa.ticker} — {type_labels.get(pa.alert_type, '')} {target_str} erreicht ({pa.currency or 'CHF'} {float(pa.trigger_price):.2f})",
                "ticker": pa.ticker,
            })

    critical_count = sum(1 for a in alerts if a["severity"] == "critical")
    return {"alerts": alerts, "count": len(alerts), "critical_count": critical_count}
