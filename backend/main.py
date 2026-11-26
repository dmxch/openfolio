import asyncio
import logging
import os
import time as _time
import uuid as _uuid
import yf_patch  # noqa: F401 — must be first to patch yfinance before any service imports

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime

from dateutils import utcnow

from logging_config import setup_logging
setup_logging("api")

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from auth import get_current_user
from config import settings
from constants.limits import RL_SEARCH
from db import async_session, engine, get_db
from models import Base
from services.auth_service import decode_access_token
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
from api.auth import limiter, router as auth_router
from api.settings import router as settings_router, export_router
from api.etf_sectors import router as etf_sectors_router
from api.taxonomy import router as taxonomy_router
from api.alerts import router as alerts_router
from api.admin import router as admin_router
from api.precious_metals import router as precious_metals_router
from api.private_equity import router as private_equity_router
from api.screening import router as screening_router
from api.external_v1 import router as external_v1_router
from api.dividends import router as dividends_router
from api.orders import router as orders_router
from api.buckets import router as buckets_router
from api.eps_scanner import router as eps_scanner_router

logger = logging.getLogger(__name__)


async def record_snapshot():
    """Record daily portfolio snapshot after price refresh."""
    from services.snapshot_service import record_daily_snapshot
    async with async_session() as db:
        count = await record_daily_snapshot(db)
        logger.info(f"Portfolio snapshots recorded: {count}")


async def create_admin_user():
    """Create the initial admin from ADMIN_EMAIL/ADMIN_PASSWORD — only while no active admin exists.

    Bootstrap, kein Dauerzustand: die App bestätigt E-Mail-Adressen nicht. Wer
    die Adresse aus ADMIN_EMAIL später auf sein Konto setzt (change-email), würde
    sonst beim nächsten Start zum Admin befördert (Vollreview 11/2026, K091).

    Gesperrte Admins zählen nicht: sonst bliebe eine Instanz, deren Admins alle
    gesperrt sind, ohne Weg zu einem neuen Admin.

    Der Start legt nur ein neues Konto an. Ein bestehendes Konto befördert oder
    entsperrt er nie, auch nicht, solange gar kein Admin existiert.
    """
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
            admin_states = {
                row[0]
                for row in await db.execute(
                    select(User.is_active).where(User.is_admin == True).distinct()  # noqa: E712
                )
            }
            if True in admin_states:
                logger.info("Admin bootstrap skipped: an active admin account already exists")
                return
            # True: es gibt Admins, aber alle sind gesperrt.
            only_disabled_admins = bool(admin_states)

            result = await db.execute(select(User).where(func.lower(User.email) == admin_email))
            existing = result.scalars().first()

            if existing:
                # Kein bestehendes Konto befördern oder entsperren (K091): die App
                # bestätigt E-Mail-Adressen nicht. Sonst genügte es, die Adresse
                # aus ADMIN_EMAIL per Registrierung oder change-email zu belegen;
                # der Start machte das Konto mit dem Passwort seines Inhabers zum
                # Admin.
                logger.warning(
                    "Admin bootstrap skipped: %s and ADMIN_EMAIL belongs to an existing account. "
                    "Set ADMIN_EMAIL to an unused address.",
                    "all admin accounts are deactivated" if only_disabled_admins
                    else "no admin account exists",
                )
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


async def enforce_default_rate_limit(request: Request) -> None:
    """Default-Limit (RL_DEFAULT) für Routen ohne eigenes @limiter.limit (K032).

    App-Dependency statt SlowAPIMiddleware: die Middleware sucht den Handler in
    app.routes. Routen aus include_router liegen dort als _IncludedRouter ohne
    Endpunkt, die Middleware liesse sie ohne Limit (im Container gemessen:
    241 Aufrufe, kein 429). Eine Dependency läuft nach dem Routing, der
    Endpunkt steht dann im Scope. Sie läuft vor der Auth-Dependency der Route.
    """
    lim = request.app.state.limiter
    endpoint = request.scope.get("endpoint")
    if not lim.enabled or endpoint is None:
        return
    name = f"{endpoint.__module__}.{endpoint.__name__}"
    # Dekorierte Routen prüft ihr Dekorator selbst, sonst zählten sie doppelt.
    if name in lim._route_limits or name in lim._exempt_routes:
        return
    lim._check_request_limit(request, endpoint, True)


app = FastAPI(
    title="OpenFolio API",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(enforce_default_rate_limit)],
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# Rate limiting
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
# /metrics ohne Auth: Prometheus scrapt tokenlos (JWTs laufen ab), und der
# Endpoint liefert nur Ops-Counter (keine Portfolio-/PII-Daten). Netzwerkseitig
# safe — nginx proxyt nur /api/, Backend-Port nur auf 127.0.0.1 (nicht oeffentlich).
# Vom Default-Limit ausgenommen: Prometheus scrapt in festem Takt.
app.add_api_route("/metrics", limiter.exempt(metrics_endpoint), include_in_schema=False)

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
    # Ein Body mit Transfer-Encoding trägt keine prüfbare Länge, und FastAPI
    # liest ihn vollständig, bevor die Auth-Dependency läuft. Transfer-Encoding
    # geht laut RFC 9112 einem Content-Length vor; der Header zählt dann nicht.
    # Browser und der vorgelagerte nginx (puffert Requests) senden immer
    # Content-Length, deshalb ablehnen statt mitzählen (K164).
    if "transfer-encoding" in request.headers:
        return JSONResponse(
            status_code=411,
            content={"detail": "Content-Length fehlt: Anfragen mit Transfer-Encoding werden nicht angenommen"},
        )
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
app.include_router(dividends_router)
app.include_router(orders_router)
app.include_router(buckets_router)
app.include_router(eps_scanner_router)


def _health_details_allowed(request: Request) -> bool:
    """True, wenn der Caller ein gueltiges Access-Token mitschickt.

    Bewusst ohne DB-Lookup: der Health-Endpoint soll auch dann antworten, wenn
    die DB gerade weg ist — ein Token-Decode reicht, um "kein Fremder" zu
    entscheiden.
    """
    auth_header = request.headers.get("Authorization") or ""
    if not auth_header.startswith("Bearer "):
        return False
    return decode_access_token(auth_header[7:]) is not None


# Der Redis-Client ist synchron: Verbindungsaufbau und PING warten je bis 1 s.
# Im Thread mit Frist, damit ein hängendes Redis die Probe nicht mit anhält (K082).
_HEALTH_REDIS_TIMEOUT_S = 2.0
# Eigener Pool: im Standard-Pool wartet der PING hinter fremden Aufgaben (Yahoo-
# Abrufe über asyncio.to_thread). Die Frist läuft dann ab, und Health meldet
# degraded, obwohl Redis antwortet (Vollreview 11/2026, R-auth-2).
_health_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="health")


def _redis_ping() -> bool:
    """True nach erfolgreichem PING, False wenn es keinen Redis-Client gibt.

    Nach einem Fehler liefert ``_get_redis()`` für ``_REDIS_RETRY_INTERVAL``
    Sekunden None (Circuit-Breaker), obwohl ein Client existiert. Dann den Client
    direkt pingen: sonst gälte ein Ausfall als «kein Redis», und Health meldete
    ok (Vollreview 11/2026, R-auth-1).
    """
    from services import cache
    r = cache._get_redis() or cache._redis
    if not r:
        return False
    r.ping()
    return True


@app.get("/api/health")
@limiter.exempt
async def health(request: Request):
    """Liveness-Probe fuer Uptime-Monitore — oeffentlich bewusst detailarm.

    Version und eingesetzter Stack (Postgres/Redis) sind Fingerprinting-Material:
    ein unauthentifizierter Angreifer erfaehrt sonst die exakte Version und kann
    gezielt nach bekannten Luecken dazu suchen (Security-Report 2026-07-27,
    NIEDRIG #1). Oeffentlich gibt es deshalb nur `status`.

    `status` ist jetzt aussagekraeftig statt konstant "ok": faellt DB oder Redis
    aus, kommt "degraded" — ein Keyword-Monitor auf "ok" schlaegt also an, wo er
    vorher blind war. Wer ein gueltiges Access-Token mitschickt (Deploy-Smoke-Test,
    Debugging), sieht weiterhin version/db/redis.
    """
    db_status = "connected"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning(f"Health check: DB connection failed: {e}")
        db_status = "disconnected"
    redis_status = "connected"
    try:
        reachable = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(_health_executor, _redis_ping),
            timeout=_HEALTH_REDIS_TIMEOUT_S,
        )
        if not reachable:
            # Kein Redis-Client (REDIS_URL unbrauchbar) ist eine gueltige Betriebsart
            # (Cache optional) und damit KEIN degraded. Ein konfiguriertes Redis, das
            # nicht antwortet, ist ein Ausfall — auch wenn es nie erreichbar war.
            redis_status = "unavailable"
    except asyncio.TimeoutError:
        logger.warning("Health check: Redis ping timed out")
        redis_status = "disconnected"
    except Exception as e:
        logger.warning(f"Health check: Redis connection failed: {e}")
        redis_status = "disconnected"

    status = "ok" if db_status == "connected" and redis_status != "disconnected" else "degraded"
    if not _health_details_allowed(request):
        return {"status": status}

    from version import APP_VERSION
    return {"status": status, "version": APP_VERSION, "db": db_status, "redis": redis_status}


@app.get("/api/health/composite-scan")
@limiter.exempt
async def composite_scan_health(response: Response, db=Depends(get_db)):
    """Liveness/Health des Composite-Screening-Scans — unauth, fuer Monitore.

    Liefert ein Single-Field `status` (ok/stale/degraded/no_scan) plus per-
    Source- und per-Signal-Coverage, ohne Ergebnis-Payload. Gedacht fuer
    uptime-kuma o.ae., die keinen API-Token haben. Per-User-neutral, weil der
    Composite-Scan global ist (nicht user-scoped).

    `Cache-Control: no-store`, weil der Endpoint unauth hinter Cloudflare liegt
    (siehe Prod) — ein gecachter Liveness-Wert wuerde Monitore in die Irre
    fuehren (stale gilt als frisch). Garantiert frische Antwort fuer ALLE
    Konsumenten, nicht nur die mit Cache-Buster.
    """
    from services.screening.scan_health import get_composite_scan_health
    response.headers["Cache-Control"] = "no-store"
    return await get_composite_scan_health(db)


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
    from services.cache_service import is_refreshing, get_refresh_state, refresh_cache, _save_refresh_state_to_db, _load_refresh_state_from_db
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
        prev = await _load_refresh_state_from_db()
        await _save_refresh_state_to_db({
            "refreshing": False, "started_at": None, "ticker_count": 0,
            "status": "timeout", "last_refresh": prev.get("last_refresh"),
            "errors": ["Refresh abgebrochen nach 60s"],
        })
        result = {"status": "timeout", "error": "Abgebrochen nach 60s"}

    # Record daily snapshot after price refresh (keeps monthly returns up to date).
    # Timeout schützt davor, dass der Endpoint gesamthaft länger als der nginx-
    # Read-Timeout (120s) braucht und mit 504 abbricht.
    try:
        await asyncio.wait_for(record_snapshot(), timeout=30)
    except asyncio.TimeoutError:
        logger.warning("Snapshot after cache refresh timed out after 30s")
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
    # Die Fehlerliste nennt Quelle und Fehlerklasse: ein Betriebsdetail, nur für Admins.
    errors = (state.get("errors") or []) if user.is_admin else []
    return {**state, "errors": errors, "age_minutes": age_minutes}


# Yahoo sperrt die Server-IP bei parallelen Bursts für Stunden. Alle Suchanfragen
# des Prozesses teilen sich deshalb drei Slots.
_symbol_search_semaphore = asyncio.Semaphore(3)
_SYMBOL_SEARCH_NEGATIVE_TTL = 60  # Sekunden; ein Fehlschlag fragt Yahoo nicht sofort erneut
# Antwortet Yahoo langsam, sind die Slots lange belegt. Wartende geben nach
# dieser Frist mit leerer Trefferliste auf, statt sich samt ihrer DB-Verbindung
# zu stauen. Der Abruf selbst läuft ohne Wiederholung (fetch_json_once): drei
# Versuche mit Wartezeit hielten einen Slot bis zu einer halben Minute.
_SYMBOL_SEARCH_SLOT_WAIT_S = 5.0
# Lange Fondsnamen («iShares Core MSCI World UCITS ETF USD (Acc)») brauchen Platz.
_SYMBOL_SEARCH_MAX_QUERY_LEN = 64


@app.get("/api/search/symbols")
@limiter.limit(RL_SEARCH)
async def search_symbols(
    request: Request,
    q: str = Query("", max_length=_SYMBOL_SEARCH_MAX_QUERY_LEN, pattern=r"^[^\x00-\x1f\x7f]*$"),
    limit: int = Query(8, ge=1, le=20),
    user=Depends(get_current_user),
):
    """Search for stock/ETF symbols with autocomplete."""
    from services import cache as app_cache
    from services.api_utils import fetch_json_once

    q = q.strip()
    if not q:
        return {"results": []}

    # limit gehört in den Schlüssel: es bestimmt quotesCount und damit den Inhalt.
    # Ohne es kürzte ein Aufruf mit limit=1 die Treffer aller Nutzer (X33).
    cache_key = f"symbol_search:{q.lower()}:{limit}"
    cached = app_cache.get(cache_key)
    if cached is not None:
        return {"results": cached}

    try:
        await asyncio.wait_for(_symbol_search_semaphore.acquire(), timeout=_SYMBOL_SEARCH_SLOT_WAIT_S)
    except asyncio.TimeoutError:
        logger.warning("Symbol search skipped: no free Yahoo slot")
        return {"results": []}
    try:
        # Wer auf einen Slot gewartet hat, findet das Ergebnis oft schon im Cache.
        cached = app_cache.get(cache_key)
        if cached is not None:
            return {"results": cached}

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
        data = await fetch_json_once(url, params=params, headers=headers, timeout=5)

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
        app_cache.set(cache_key, [], ttl=_SYMBOL_SEARCH_NEGATIVE_TTL)
        return {"results": []}
    finally:
        _symbol_search_semaphore.release()


@app.get("/api/alerts")
async def get_alerts(db=Depends(get_db), user=Depends(get_current_user)):
    from services.portfolio_service import get_portfolio_summary_cached
    from services.market_analyzer import get_market_climate
    from services.alert_service import generate_alerts

    from sqlalchemy import select as sa_select
    from models.user import UserSettings
    from models.alert_preference import AlertPreference
    from services.settings_service import settings_to_dict as _settings_to_dict

    # Geteilter Cache mit /api/portfolio/summary. Cache-Vertrag (Review 2026-07-02,
    # M4+M16): portfolio_summary:{user_id} enthaelt IMMER die UNangereicherte
    # Summary (keine entschluesselten PII, keine active_alerts/change_pct_24h);
    # /summary reichert NACH dem Cache-Read pro Request an
    # (api/portfolio._enrich_summary). Lesen und Schreiben liegen in
    # get_portfolio_summary_cached (ein Schreiber, K060).
    summary = await get_portfolio_summary_cached(db, user.id)
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

    from services.bucket_service import load_buckets_map
    buckets_map = await load_buckets_map(db, user.id)
    # Bucket-Drift-Alert misst gegen das liquide Gesamt (Konzept B) — dieselbe
    # Basis wie der Allokations-Pie, damit Alert-% und Pie-% deckungsgleich sind.
    from services.bucket_performance_service import get_allocations_by_bucket
    bucket_allocations = await get_allocations_by_bucket(db, user.id)
    alerts = generate_alerts(
        summary.get("positions", []),
        climate,
        prefs,
        watchlist_tickers=watchlist_tickers,
        buckets_map=buckets_map,
        bucket_allocations=bucket_allocations,
        user_id=str(user.id),
    )

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
        "allocation_bucket_drift": "allocation",
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
