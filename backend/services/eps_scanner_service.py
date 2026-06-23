"""EPS-Scanner: Quartals-Reported-EPS laden, persistieren und auswerten.

Additives Feature — beruehrt KEINE Performance-/Renditeberechnung
(HEILIGE Regeln 1, 11).

Aufbau:
- Reine Berechnungslogik (compute_metrics + Helfer) — netzwerk-/DB-frei,
  voll unit-testbar.
- Fetch-/Persistenz-Schicht (Finnhub primaer, yfinance-Fallback) fuer den
  Worker-Job refresh_eps_quarterly.
- Abfrage-Schicht (get_scanner_results / get_status) fuer die API.

YoY = "4 Perioden zurueck" aus der Finnhub-Reihe (Doc OF-7, v1-Ansatz).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any

from dateutils import utcnow
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.app_setting import AppSetting
from models.eps_quarterly import EpsQuarterly
from models.user import UserSettings
from services.api_utils import fetch_json
from services.screening.sp500_universe import (
    company_name,
    gics_sector,
    resolve_sp500_universe,
)
from services.screening.universe import resolve_equity_universe

logger = logging.getLogger(__name__)

# --- Service-Konstanten / Defaults -----------------------------------------

DEFAULT_YOY_THRESHOLD = 25.0          # Prozent
DEFAULT_ACCELERATION_MARGIN = 5.0     # Prozentpunkte
DEFAULT_OUTLIER_MULTIPLIER = 5.0      # x Median

YOY_LAG = 4                           # Perioden zurueck fuer Vorjahresquartal
RECORD_WINDOW = 8                     # Quartale vor dem juengsten fuer Record-Hoch
OUTLIER_WINDOW = 6                    # Vorquartale fuer Median-Outlier-Guard
COMPUTE_WINDOW = 12                   # max. juengste Quartale fuer die Auswertung
DISPLAY_QUARTERS = 8                  # Quartale in der API-Response

FINNHUB_BASE = "https://finnhub.io/api/v1"
FINNHUB_RATE_PER_MIN = 30             # bewusst tief: laesst Headroom fuer die
                                      # Retries von retry_external (die am Limiter
                                      # vorbei laufen) — bei 55/min kippte ein
                                      # 429-Retry das 60/min-Fenster -> Kaskade
YFINANCE_FALLBACK_CONCURRENCY = 3     # Semaphore (feedback_yfinance_burst_429)

STATUS_SETTING_KEY = "eps_scanner_last_run"
STALE_AFTER_HOURS = 30                # job_status="stale" wenn last_run aelter


@dataclass(frozen=True)
class Thresholds:
    """Pro-User-Filter-Schwellen (mit Service-Defaults bei NULL)."""

    yoy_threshold: float = DEFAULT_YOY_THRESHOLD
    acceleration_margin: float = DEFAULT_ACCELERATION_MARGIN
    outlier_multiplier: float = DEFAULT_OUTLIER_MULTIPLIER


@dataclass(frozen=True)
class QuarterPoint:
    """Ein Quartalswert fuer die reine Berechnung."""

    period_end: date
    eps: float
    source: str
    fetched_at: datetime | None = None


# ---------------------------------------------------------------------------
# Reine Berechnungslogik (netzwerk-/DB-frei, voll testbar)
# ---------------------------------------------------------------------------

def _yoy_flag(basis: float, current: float) -> str:
    """YoY-Flag aus Basis (Vorjahresquartal) und aktuellem EPS."""
    if basis == 0:
        return "zero_basis"
    if basis > 0 and current > 0:
        return "pos_to_pos"
    if basis > 0 and current <= 0:
        return "pos_to_neg"
    if basis < 0 and current > 0:
        return "turnaround"
    return "neg_to_neg"  # basis < 0 and current <= 0


def _yoy_growth(flag: str, basis: float, current: float) -> float | None:
    """YoY-Wachstum in Prozent — nur fuer pos_to_pos definiert."""
    if flag != "pos_to_pos":
        return None
    return (current - basis) / abs(basis) * 100.0


def _yoy_series(eps: list[float]) -> list[tuple[str | None, float | None]]:
    """Pro Quartal (flag, growth_pct), ausgerichtet an `eps` (oldest→newest).

    Fuer Quartale ohne Vorjahresquartal (Index < YOY_LAG): (None, None).
    """
    out: list[tuple[str | None, float | None]] = []
    for i in range(len(eps)):
        if i - YOY_LAG < 0:
            out.append((None, None))
            continue
        basis = eps[i - YOY_LAG]
        current = eps[i]
        flag = _yoy_flag(basis, current)
        out.append((flag, _yoy_growth(flag, basis, current)))
    return out


def _outlier_flag(eps: list[float], multiplier: float) -> bool:
    """True wenn juengstes EPS > multiplier × Median der bis zu OUTLIER_WINDOW
    Vorquartale. Guard greift nur bei positivem Median (sonst nicht
    zuverlaessig von Turnaround unterscheidbar)."""
    if len(eps) < 2:
        return False
    window = eps[:-1][-OUTLIER_WINDOW:]
    if not window:
        return False
    med = median(window)
    if med <= 0:
        return False
    return eps[-1] > multiplier * med


def _streak_count(yoy: list[tuple[str | None, float | None]]) -> int:
    """Anzahl Quartale im Fenster mit pos_to_pos UND positivem YoY-Wachstum."""
    return sum(
        1 for flag, growth in yoy
        if flag == "pos_to_pos" and growth is not None and growth > 0
    )


def _super_quarter(
    latest_flag: str | None,
    latest_growth: float | None,
    yoy: list[tuple[str | None, float | None]],
    outlier: bool,
    thresholds: Thresholds,
) -> bool:
    """Super-Quartal-Kriterien A–D (alle muessen erfuellt sein).

    C entfaellt, wenn < 2 vorherige pos_to_pos-YoY-Raten existieren (Doc OF-2).
    """
    # A
    if latest_flag != "pos_to_pos" or latest_growth is None:
        return False
    # D
    if outlier:
        return False
    # B
    if latest_growth < thresholds.yoy_threshold:
        return False
    # C — Median der bis zu 3 vorherigen pos_to_pos-YoY-Raten (exkl. juengstes)
    prior_rates = [
        g for flag, g in yoy[:-1]
        if flag == "pos_to_pos" and g is not None
    ]
    prior_rates = prior_rates[-3:]
    if len(prior_rates) >= 2:
        if latest_growth < median(prior_rates) + thresholds.acceleration_margin:
            return False
    # < 2 Vorwerte → C entfaellt, A+B+D haben gehalten
    return True


def compute_metrics(quarters: list[QuarterPoint], thresholds: Thresholds) -> dict[str, Any]:
    """Berechnet alle Scanner-Kennzahlen fuer eine EPS-Reihe.

    `quarters` muss chronologisch aufsteigend sein (aeltestes zuerst).
    Gibt ein Dict ohne Ticker/Name/Sector zurueck (die ergaenzt die
    Abfrage-Schicht).
    """
    eps = [q.eps for q in quarters]
    quarter_count = len(quarters)

    yoy = _yoy_series(eps)
    latest_flag, latest_growth = (yoy[-1] if yoy else (None, None))
    outlier = _outlier_flag(eps, thresholds.outlier_multiplier)
    streak = _streak_count(yoy)
    super_q = _super_quarter(latest_flag, latest_growth, yoy, outlier, thresholds)

    # Record-Quartal (absolutes Niveau-Hoch, unabhaengig vom Super-Quartal)
    window = eps[:-1][-RECORD_WINDOW:]
    latest_eps = eps[-1] if eps else None
    record_quarter = bool(window) and latest_eps is not None and latest_eps > max(window)
    record_quarter_outlier = record_quarter and outlier
    record_quarter_turnaround = (
        record_quarter
        and latest_eps is not None
        and latest_eps > 0
        and min(window) < 0
    )

    # Data-Age aus dem juengsten fetched_at
    fetched = [q.fetched_at for q in quarters if q.fetched_at is not None]
    data_age_days: int | None = None
    if fetched:
        newest = max(fetched)
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)
        data_age_days = (datetime.now(timezone.utc) - newest).days

    display = quarters[-DISPLAY_QUARTERS:]
    return {
        "quarters": [
            {
                "period_end": q.period_end.isoformat(),
                "eps": round(q.eps, 4),
                "source": q.source,
            }
            for q in display
        ],
        "latest_eps": round(latest_eps, 4) if latest_eps is not None else None,
        "yoy_growth_pct": round(latest_growth, 2) if latest_growth is not None else None,
        "yoy_flag": latest_flag,
        "streak_count": streak,
        "super_quarter": super_q,
        "record_quarter": record_quarter,
        "record_quarter_outlier": record_quarter_outlier,
        "record_quarter_turnaround": record_quarter_turnaround,
        "outlier_flag": outlier,
        "data_age_days": data_age_days,
        "quarter_count": quarter_count,
    }


# ---------------------------------------------------------------------------
# Parsing (Provider-Antworten → QuarterPoints)
# ---------------------------------------------------------------------------

def _to_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    # NaN/Infinity abweisen: Decimal(str(float("nan"))) == Decimal("NaN")
    # wirft NICHT, wuerde aber sonst als gueltiger EPS-Wert durchrutschen
    # (z.B. das noch nicht gemeldete juengste Quartal bei yfinance).
    if not d.is_finite():
        return None
    return d


def parse_finnhub_eps(payload: dict | None) -> list[tuple[date, Decimal]]:
    """Extrahiere (period_end, eps) aus Finnhub stock/metric.

    Pfad: payload["series"]["quarterly"]["eps"] = [{period, v}, ...]
    (neuestes zuerst). Gibt aufsteigend sortierte, deduplizierte Liste zurueck.
    """
    if not isinstance(payload, dict):
        return []
    try:
        series = payload["series"]["quarterly"]["eps"]
    except (KeyError, TypeError):
        return []
    if not isinstance(series, list):
        return []
    out: dict[date, Decimal] = {}
    for row in series:
        if not isinstance(row, dict):
            continue
        period = row.get("period")
        val = _to_decimal(row.get("v"))
        if not period or val is None:
            continue
        try:
            pe = date.fromisoformat(str(period)[:10])
        except ValueError:
            continue
        out[pe] = val
    return sorted(out.items(), key=lambda x: x[0])


def _coerce_earnings_date(value: Any) -> date | None:
    """Parse ein yfinance-Earnings-Datum zu einem date. None bei Fehler.

    Deckt beide yfinance-Formate ab:
    - pandas Timestamp / datetime (aelterer DatetimeIndex) -> .date()
    - String "2026-04-14 ..." (ISO) oder "April 14, 2026 at 6 AM EDT"
      (neuere Spalte "Earnings Date").
    """
    if value is None:
        return None
    dt_method = getattr(value, "date", None)
    if callable(dt_method):
        try:
            return dt_method()
        except Exception:
            return None
    s = str(value).strip()
    if not s or s.lower() == "nat":
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    # "April 14, 2026 at 6 AM EDT" -> Teil vor " at "
    head = s.split(" at ")[0].strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def parse_yfinance_earnings(df: Any) -> list[tuple[date, Decimal]]:
    """Extrahiere (period_end, eps) aus yf.get_earnings_dates() DataFrame.

    Nutzt die Spalte "Reported EPS"; ueberspringt NaN (zukuenftige Termine).
    Das Earnings-Datum (Report-Datum, als period_end approximiert — Doc
    v1-Ansatz) kommt aus der Spalte "Earnings Date" (neuere yfinance) oder,
    falls die fehlt, aus dem DataFrame-Index (aelterer DatetimeIndex).
    """
    if df is None:
        return []
    try:
        if getattr(df, "empty", True):
            return []
    except Exception:
        return []
    columns = list(getattr(df, "columns", []))
    col = next((c for c in ("Reported EPS", "reportedEPS", "EPS") if c in columns), None)
    if col is None:
        return []
    date_col = next((c for c in ("Earnings Date", "earningsDate") if c in columns), None)
    out: dict[date, Decimal] = {}
    eps_series = df[col]
    date_series = df[date_col] if date_col else None
    for pos, (idx, val) in enumerate(eps_series.items()):
        dec = _to_decimal(val)
        if dec is None:
            continue
        raw_date = date_series.iloc[pos] if date_series is not None else idx
        pe = _coerce_earnings_date(raw_date)
        if pe is None:
            continue
        out[pe] = dec
    return sorted(out.items(), key=lambda x: x[0])


# ---------------------------------------------------------------------------
# Fetch (Provider)
# ---------------------------------------------------------------------------

async def fetch_finnhub_eps(ticker: str, api_key: str) -> list[tuple[date, Decimal]]:
    """Hole die Quartals-EPS-Reihe eines Tickers von Finnhub. [] bei Fehler/leer."""
    url = f"{FINNHUB_BASE}/stock/metric"
    try:
        # Token via Header (X-Finnhub-Token), NICHT als Query-Param: sonst
        # landet der System-Key bei httpx-Fehlern in der geloggten URL.
        data = await fetch_json(
            url,
            params={"metric": "all", "symbol": ticker},
            headers={"X-Finnhub-Token": api_key},
            timeout=15,
        )
    except Exception as e:
        logger.debug("Finnhub EPS fetch failed for %s: %s", ticker, e)
        return []
    return parse_finnhub_eps(data)


async def fetch_yfinance_eps(ticker: str) -> list[tuple[date, Decimal]]:
    """yfinance-Fallback (NUR ueber yf_patch-Wrapper via to_thread, Regel 7)."""
    from yf_patch import yf_earnings_dates

    try:
        df = await asyncio.to_thread(yf_earnings_dates, ticker, 16)
    except Exception as e:
        logger.debug("yfinance EPS fallback failed for %s: %s", ticker, e)
        return []
    return parse_yfinance_earnings(df)


# ---------------------------------------------------------------------------
# Persistenz
# ---------------------------------------------------------------------------

async def upsert_quarters(
    db: AsyncSession,
    ticker: str,
    points: list[tuple[date, Decimal]],
    source: str,
) -> int:
    """Upsert (ON CONFLICT DO UPDATE) je Quartal. Gibt Anzahl betroffener Rows."""
    if not points:
        return 0
    now = utcnow()
    affected = 0
    for period_end, eps in points:
        stmt = pg_insert(EpsQuarterly).values(
            ticker=ticker,
            period_end=period_end,
            eps=eps,
            source=source,
            fetched_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_eps_quarterly_ticker_period",
            set_={
                "eps": stmt.excluded.eps,
                "source": stmt.excluded.source,
                "fetched_at": stmt.excluded.fetched_at,
            },
        )
        result = await db.execute(stmt)
        affected += int(result.rowcount or 0)
    return affected


# ---------------------------------------------------------------------------
# Worker-Pipeline
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Einfacher Token-Bucket: max. `per_minute` Aufrufe pro 60s."""

    def __init__(self, per_minute: int) -> None:
        self._interval = 60.0 / max(1, per_minute)
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            wait = self._next - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = loop.time()
            self._next = now + self._interval


async def resolve_scanner_universe(db: AsyncSession) -> list[str]:
    """Scanner-Universe = S&P 500 ∪ Portfolio/Watchlist-Equities.

    So sind auch gehaltene/beobachtete Nicht-S&P-500-Titel abgedeckt (z.B.
    ADRs wie TSM). resolve_equity_universe filtert bereits auf US-Equities.
    """
    sp500 = set(resolve_sp500_universe())
    held = set(await resolve_equity_universe(db))
    return sorted(sp500 | held)


async def refresh_eps_quarterly(db: AsyncSession) -> dict[str, Any]:
    """Worker-Pipeline: Finnhub-Batch + yfinance-Fallback fuer das Scanner-
    Universum (S&P 500 + Portfolio/Watchlist-Holdings).

    Schreibt den Job-Status nach AppSetting[STATUS_SETTING_KEY].
    """
    from config import settings

    tickers = await resolve_scanner_universe(db)
    api_key = (settings.finnhub_system_api_key or "").strip()
    key_configured = bool(api_key)

    finnhub_ok: set[str] = set()
    fallback_list: list[str] = []

    if key_configured:
        limiter = _RateLimiter(FINNHUB_RATE_PER_MIN)
        for ticker in tickers:
            await limiter.acquire()
            try:
                points = await fetch_finnhub_eps(ticker, api_key)
            except Exception:
                logger.exception("Finnhub fetch crashed for %s", ticker)
                fallback_list.append(ticker)
                continue
            if points:
                try:
                    await upsert_quarters(db, ticker, points, "finnhub")
                    await db.commit()
                    finnhub_ok.add(ticker)
                except Exception:
                    await db.rollback()
                    logger.exception("Finnhub upsert failed for %s", ticker)
                    fallback_list.append(ticker)
            else:
                fallback_list.append(ticker)
        logger.info(
            "EPS-Scanner Finnhub batch: %d/%d ok, %d to fallback",
            len(finnhub_ok), len(tickers), len(fallback_list),
        )
    else:
        logger.warning(
            "EPS-Scanner: FINNHUB_SYSTEM_API_KEY not configured — "
            "skipping Finnhub batch, all tickers go to yfinance fallback"
        )
        fallback_list = list(tickers)

    # yfinance-Fallback mit Semaphore (Regel feedback_yfinance_burst_429)
    yfinance_ok: set[str] = set()
    sem = asyncio.Semaphore(YFINANCE_FALLBACK_CONCURRENCY)

    async def _fallback_one(ticker: str) -> None:
        async with sem:
            try:
                points = await fetch_yfinance_eps(ticker)
            except Exception:
                logger.warning("yfinance fallback crashed for %s", ticker, exc_info=True)
                return
            if not points:
                logger.warning("EPS-Scanner: no EPS data for %s (Finnhub+yfinance empty)", ticker)
                return
            # Jede Coroutine braucht ihre eigene Session (feedback_async_session_per_gather_branch)
            from db import async_session
            async with async_session() as fb_db:
                try:
                    await upsert_quarters(fb_db, ticker, points, "yfinance")
                    await fb_db.commit()
                    yfinance_ok.add(ticker)
                except Exception:
                    await fb_db.rollback()
                    logger.exception("yfinance upsert failed for %s", ticker)

    if fallback_list:
        await asyncio.gather(*(_fallback_one(t) for t in fallback_list))

    fetched = finnhub_ok | yfinance_ok
    missing = [t for t in tickers if t not in fetched]

    status_payload = {
        "last_run": utcnow().isoformat(),
        "tickers_total": len(tickers),
        "tickers_fetched": len(fetched),
        "tickers_finnhub": len(finnhub_ok),
        "tickers_yfinance_fallback": len(yfinance_ok),
        "tickers_missing": len(missing),
        "missing_tickers": missing[:15],
        "finnhub_key_configured": key_configured,
        "job_status": "completed",
    }
    await _write_status(db, status_payload)
    logger.info(
        "EPS-Scanner refresh done: fetched=%d finnhub=%d yfinance=%d missing=%d",
        len(fetched), len(finnhub_ok), len(yfinance_ok), len(missing),
    )
    return status_payload


# Maximale Laenge der AppSetting.value-Spalte (geteilte String(500)-Spalte).
_APP_SETTING_VALUE_MAX = 500


def _serialize_status(payload: dict[str, Any]) -> str:
    """Serialisiere den Status so, dass er in AppSetting.value (String(500)) passt.

    Das diagnostische missing_tickers-Sample wird bei Bedarf weiter gekuerzt,
    damit _write_status im Degraded-Fall (viele fehlende Ticker) keine
    StringDataRightTruncationError wirft.
    """
    value = json.dumps(payload)
    if len(value) <= _APP_SETTING_VALUE_MAX:
        return value
    trimmed = dict(payload)
    sample = list(trimmed.get("missing_tickers") or [])
    while sample:
        sample.pop()
        trimmed["missing_tickers"] = sample
        value = json.dumps(trimmed)
        if len(value) <= _APP_SETTING_VALUE_MAX:
            break
    return value


async def _write_status(db: AsyncSession, payload: dict[str, Any]) -> None:
    stmt = pg_insert(AppSetting).values(
        key=STATUS_SETTING_KEY,
        value=_serialize_status(payload),
        updated_at=utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at},
    )
    await db.execute(stmt)
    await db.commit()


# ---------------------------------------------------------------------------
# Abfrage-Schicht (API)
# ---------------------------------------------------------------------------

async def resolve_thresholds(db: AsyncSession, user_id: Any) -> Thresholds:
    """Lese die Pro-User-Schwellen (NULL → Service-Defaults)."""
    row = (
        await db.execute(
            select(
                UserSettings.eps_scanner_yoy_threshold,
                UserSettings.eps_scanner_acceleration_margin,
                UserSettings.eps_scanner_outlier_multiplier,
            ).where(UserSettings.user_id == user_id)
        )
    ).first()
    if not row:
        return Thresholds()
    yoy, accel, outlier = row
    return Thresholds(
        yoy_threshold=float(yoy) if yoy is not None else DEFAULT_YOY_THRESHOLD,
        acceleration_margin=float(accel) if accel is not None else DEFAULT_ACCELERATION_MARGIN,
        outlier_multiplier=float(outlier) if outlier is not None else DEFAULT_OUTLIER_MULTIPLIER,
    )


async def update_thresholds(
    db: AsyncSession,
    user_id: Any,
    yoy: float | None,
    accel: float | None,
    outlier: float | None,
) -> Thresholds:
    """Persistiere User-Schwellen in user_settings. NULL-Werte bleiben unveraendert."""
    s = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalars().first()
    if not s:
        s = UserSettings(user_id=user_id)
        db.add(s)
    if yoy is not None:
        s.eps_scanner_yoy_threshold = Decimal(str(yoy))
    if accel is not None:
        s.eps_scanner_acceleration_margin = Decimal(str(accel))
    if outlier is not None:
        s.eps_scanner_outlier_multiplier = Decimal(str(outlier))
    await db.commit()
    return await resolve_thresholds(db, user_id)


async def _load_status(db: AsyncSession) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(AppSetting.value).where(AppSetting.key == STATUS_SETTING_KEY)
        )
    ).scalar_one_or_none()
    if not row:
        return None
    try:
        return json.loads(row)
    except (ValueError, TypeError):
        return None


async def get_ticker_result(db: AsyncSession, user_id: Any, ticker: str) -> dict[str, Any] | None:
    """Berechne die EPS-Metriken fuer EINEN Ticker. None, wenn keine Daten.

    Fuer das EPS-Scanner-Kontext-Widget auf der Aktiendetailseite. Nutzt die
    User-Schwellen (Super-Quartal). Keine PII.
    """
    sym = (ticker or "").strip().upper()
    if not sym:
        return None
    thresholds = await resolve_thresholds(db, user_id)
    qrows = (
        await db.execute(
            select(EpsQuarterly)
            .where(EpsQuarterly.ticker == sym)
            .order_by(EpsQuarterly.period_end)
        )
    ).scalars().all()
    if not qrows:
        return None
    recent = list(qrows)[-COMPUTE_WINDOW:]
    points = [
        QuarterPoint(
            period_end=q.period_end,
            eps=float(q.eps),
            source=q.source,
            fetched_at=q.fetched_at,
        )
        for q in recent
    ]
    if not points:
        return None
    metrics = compute_metrics(points, thresholds)
    metrics["ticker"] = sym
    metrics["name"] = company_name(sym) or sym
    metrics["sector"] = gics_sector(sym)
    return metrics


async def get_scanner_results(
    db: AsyncSession,
    user_id: Any,
    *,
    super_quarter_only: bool = False,
    record_quarter_only: bool = False,
    min_quarters: int = 6,
    sectors: list[str] | None = None,
    search: str | None = None,
    sort_by: str = "yoy_growth",
    sort_asc: bool = False,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    """Berechne und filtere die Scanner-Ergebnisse fuer einen User."""
    thresholds = await resolve_thresholds(db, user_id)

    rows = (
        await db.execute(
            select(EpsQuarterly).order_by(
                EpsQuarterly.ticker, EpsQuarterly.period_end
            )
        )
    ).scalars().all()

    by_ticker: dict[str, list[EpsQuarterly]] = {}
    for r in rows:
        by_ticker.setdefault(r.ticker, []).append(r)

    results: list[dict[str, Any]] = []
    for ticker, qrows in by_ticker.items():
        qrows.sort(key=lambda x: x.period_end)
        recent = qrows[-COMPUTE_WINDOW:]
        points = [
            QuarterPoint(
                period_end=q.period_end,
                eps=float(q.eps),
                source=q.source,
                fetched_at=q.fetched_at,
            )
            for q in recent
        ]
        if not points:
            continue
        metrics = compute_metrics(points, thresholds)
        metrics["ticker"] = ticker
        metrics["name"] = company_name(ticker) or ticker
        metrics["sector"] = gics_sector(ticker)
        results.append(metrics)

    # Filter
    filtered = [r for r in results if r["quarter_count"] >= min_quarters]
    if super_quarter_only:
        filtered = [r for r in filtered if r["super_quarter"]]
    if record_quarter_only:
        filtered = [r for r in filtered if r["record_quarter"]]
    if sectors:
        sset = {s.strip() for s in sectors if s and s.strip()}
        filtered = [r for r in filtered if r.get("sector") in sset]
    if search and search.strip():
        q = search.strip().lower()
        filtered = [
            r for r in filtered
            if q in r["ticker"].lower() or q in (r.get("name") or "").lower()
        ]

    # Sortierung
    sort_keys = {
        "ticker": lambda r: r["ticker"],
        "yoy_growth": lambda r: (r["yoy_growth_pct"] is not None, r["yoy_growth_pct"] or 0.0),
        "streak_count": lambda r: r["streak_count"],
        "latest_eps": lambda r: (r["latest_eps"] is not None, r["latest_eps"] or 0.0),
    }
    key_fn = sort_keys.get(sort_by, sort_keys["yoy_growth"])
    filtered.sort(key=key_fn, reverse=not sort_asc)

    total = len(filtered)
    start = (page - 1) * per_page
    page_rows = filtered[start:start + per_page]

    status = await _load_status(db)
    data_refreshed_at = status.get("last_run") if status else None
    if data_refreshed_at is None and rows:
        newest = max(r.fetched_at for r in rows)
        data_refreshed_at = newest.isoformat()

    return {
        "as_of": utcnow().isoformat(),
        "data_refreshed_at": data_refreshed_at,
        "thresholds": {
            "super_quarter_yoy_pct": thresholds.yoy_threshold,
            "acceleration_margin_pp": thresholds.acceleration_margin,
            "outlier_multiplier": thresholds.outlier_multiplier,
        },
        "results": page_rows,
        "total": total,
        "page": page,
        "per_page": per_page,
    }


async def get_status(db: AsyncSession) -> dict[str, Any]:
    """Daten-Freshness-Status fuer GET /api/eps-scanner/status."""
    from config import settings

    status = await _load_status(db)
    key_configured = bool((settings.finnhub_system_api_key or "").strip())
    if not status:
        return {
            "last_job_run": None,
            "tickers_total": len(resolve_sp500_universe()),
            "tickers_fetched": 0,
            "tickers_finnhub": 0,
            "tickers_yfinance_fallback": 0,
            "tickers_missing": 0,
            "missing_tickers": [],
            "finnhub_key_configured": key_configured,
            "job_status": "never_run",
        }

    job_status = status.get("job_status", "completed")
    last_run = status.get("last_run")
    if last_run:
        try:
            lr = datetime.fromisoformat(last_run)
            if lr.tzinfo is None:
                lr = lr.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - lr).total_seconds() / 3600.0
            if age_h > STALE_AFTER_HOURS:
                job_status = "stale"
        except ValueError:
            pass

    return {
        "last_job_run": last_run,
        "tickers_total": status.get("tickers_total", 0),
        "tickers_fetched": status.get("tickers_fetched", 0),
        "tickers_finnhub": status.get("tickers_finnhub", 0),
        "tickers_yfinance_fallback": status.get("tickers_yfinance_fallback", 0),
        "tickers_missing": status.get("tickers_missing", 0),
        "missing_tickers": status.get("missing_tickers", []),
        "finnhub_key_configured": key_configured,
        "job_status": job_status,
    }
