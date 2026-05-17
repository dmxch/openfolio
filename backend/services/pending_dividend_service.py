"""Dividenden-Tracker — Detection, Auto-Match und Auflösung der Quellensteuer.

Multi-User-faehig: jeder Query ist ``user_id``-gescoped, der Worker iteriert
explizit ueber ``DISTINCT user_id`` aus ``positions``. Heilige Regel #7
(yfinance NUR via ``yf_download()`` + ``asyncio.to_thread()``) wird im
``_detect_for_position``-Pfad strikt eingehalten.

Die Funktion ``_reconstruct_shares_at_date`` ist read-only und ruft
``recalculate_service`` NICHT auf (Heilige Regel #1) — sie zaehlt
Transaktionen lokal nach.

Konstanten siehe oben:
    DIVIDEND_MATCH_WINDOW_DAYS = 35   (R4 — monatliche REIT-Pendings sonst Overlap)
    DIVIDEND_LOOKBACK_INITIAL_DAYS = 90
    DIVIDEND_LOOKBACK_ROLLING_DAYS = 35
    _GLOBAL_YFINANCE_SEM = asyncio.Semaphore(20)   (R2a — globaler Throttle)
"""

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from string import Template
from typing import Iterable

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from constants.withholding import WITHHOLDING_BY_COUNTRY
from dateutils import utcnow
from models.alert_preference import AlertPreference
from models.pending_dividend import (
    PendingDividend,
    STATUS_CONFIRMED,
    STATUS_DISMISSED,
    STATUS_PENDING,
)
from models.position import AssetType, Position
from models.smtp_config import SmtpConfig
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.utils import get_fx_rate, get_historical_fx_rate
from yf_patch import yf_download

logger = logging.getLogger(__name__)


# --- Public constants -------------------------------------------------------

DIVIDEND_MATCH_WINDOW_DAYS = 35  # R4: pinpoint nearest pending in ±35d window
DIVIDEND_LOOKBACK_INITIAL_DAYS = 90
DIVIDEND_LOOKBACK_ROLLING_DAYS = 35


# --- Module-level concurrency ----------------------------------------------

# R2a: globaler Throttle, damit bei wachsender User-Base (50 User × 3 = 150
# parallele yf-Calls) kein Yahoo-Rate-Limit getriggert wird. Wird ZUSAETZLICH
# zur Per-User-Sem(3) gehalten (nested-Acquire: erst per-user, dann global).
_GLOBAL_YFINANCE_SEM: asyncio.Semaphore = asyncio.Semaphore(20)


# --- Withholding-Resolution -------------------------------------------------


def resolve_withholding(position: Position, user_settings: UserSettings) -> float:
    """Resolve effective withholding rate for a position.

    Aufloesungsreihenfolge (R1):
        1. position.dividend_withholding_pct (User-Override, Sticky)
        2. WITHHOLDING_BY_COUNTRY[isin[:2]] (ISIN-Country-Map)
        3. user_settings.dividend_withholding_default (User-Fallback)

    Returns ``float`` in [0.0, 1.0]; never ``None``.
    """
    if position.dividend_withholding_pct is not None:
        return float(position.dividend_withholding_pct)

    if position.isin and len(position.isin) >= 2:
        rate = WITHHOLDING_BY_COUNTRY.get(position.isin[:2].upper())
        if rate is not None:
            return float(rate)

    if user_settings is not None and user_settings.dividend_withholding_default is not None:
        return float(user_settings.dividend_withholding_default)

    # Hardcoded final fallback — should never hit thanks to NOT NULL DEFAULT.
    return 0.35


# --- Shares-at-Ex-Date Rekonstruktion --------------------------------------


def _reconstruct_shares_at_date(
    transactions: Iterable[Transaction],
    target_date: date,
) -> float:
    """Rekonstruiere die Stueckzahl an einem bestimmten Stichtag.

    Read-only. Beruehrt weder ``position.shares`` noch ``position.cost_basis_chf``
    (Heilige Regel #1). ``buy``/``delivery_in`` erhoehen den Bestand,
    ``sell``/``delivery_out`` reduzieren ihn. Andere Typen (dividend, fee, …)
    aendern den Bestand nicht.

    Erwartet, dass ``transactions`` aufsteigend nach ``date`` sortiert ist —
    wenn nicht, wird hier intern sortiert.
    """
    txns = sorted(
        transactions,
        key=lambda t: (t.date, t.created_at or datetime.min),
    )
    shares = 0.0
    for txn in txns:
        if txn.date > target_date:
            break
        if txn.type in (TransactionType.buy, TransactionType.delivery_in):
            shares += float(txn.shares)
        elif txn.type in (TransactionType.sell, TransactionType.delivery_out):
            shares = max(0.0, shares - float(txn.shares))
        # alle anderen Typen ignorieren
    return shares


# --- Auto-Match -------------------------------------------------------------


async def try_auto_match_transaction(
    db: AsyncSession,
    txn: Transaction,
    user_id: uuid.UUID,
) -> PendingDividend | None:
    """Auto-Match einer neuen `dividend`-Transaktion an die naechstgelegene
    offene Pending-Dividende derselben Position innerhalb ±35d.

    Wenn ein Treffer existiert: Pending wird auf `confirmed` gesetzt und
    ``matched_transaction_id`` befuellt. Best-effort, Fehler werden vom
    aufrufenden Hook geschluckt.
    """
    if txn.type != TransactionType.dividend:
        return None

    window_start = txn.date - timedelta(days=DIVIDEND_MATCH_WINDOW_DAYS)
    window_end = txn.date + timedelta(days=DIVIDEND_MATCH_WINDOW_DAYS)

    # ORDER BY ABS(ex_date - txn.date) — naechstgelegene zuerst (R4).
    # In PG ist `date - date` ein Integer (Tage), so dass `func.abs` direkt
    # funktioniert.
    abs_diff = func.abs(PendingDividend.ex_date - txn.date)

    result = await db.execute(
        select(PendingDividend)
        .where(
            PendingDividend.user_id == user_id,
            PendingDividend.position_id == txn.position_id,
            PendingDividend.status == STATUS_PENDING,
            PendingDividend.ex_date >= window_start,
            PendingDividend.ex_date <= window_end,
        )
        .order_by(abs_diff.asc())
        .limit(1)
    )
    pending = result.scalars().first()
    if pending is None:
        return None

    pending.status = STATUS_CONFIRMED
    pending.matched_transaction_id = txn.id
    pending.updated_at = utcnow()
    await db.commit()
    logger.info(
        "dividend_auto_match user=%s position=%s txn_date=%s ex_date=%s",
        user_id, txn.position_id, txn.date, pending.ex_date,
    )
    return pending


async def try_auto_match_transactions_bulk(
    db: AsyncSession,
    txns: list[Transaction],
    user_id: uuid.UUID,
) -> int:
    """Bulk-Variante fuer den CSV-Import-Hook. Liefert Anzahl Matches."""
    matches = 0
    for txn in txns:
        try:
            res = await try_auto_match_transaction(db, txn, user_id)
            if res is not None:
                matches += 1
        except Exception as e:
            logger.warning(
                "dividend_bulk_match_failed txn=%s error=%s", txn.id, e
            )
    return matches


async def unmatch_on_transaction_delete(
    db: AsyncSession,
    txn_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    """Wenn eine `dividend`-Transaktion geloescht wird, setze die zugehoerige
    Pending-Dividende auf ``pending`` zurueck. Die DB-FK ON DELETE SET NULL
    setzt ``matched_transaction_id`` selbst — wir ergaenzen den Status-Reset.

    Liefert Anzahl der zurueckgesetzten Pending-Dividenden (idR 0 oder 1).
    """
    result = await db.execute(
        select(PendingDividend).where(
            PendingDividend.matched_transaction_id == txn_id,
            PendingDividend.user_id == user_id,
        )
    )
    pendings = result.scalars().all()
    count = 0
    for p in pendings:
        if p.status == STATUS_DISMISSED:
            # Edge: explizit nicht zuruecksetzen (theoretisch unmoeglich,
            # da Confirm und Dismiss exklusiv sind, aber bei Direct-DB-
            # Manipulation existiert der Pfad).
            continue
        p.status = STATUS_PENDING
        p.updated_at = utcnow()
        count += 1
    if count > 0:
        await db.commit()
    return count


# --- Worker-Detection -------------------------------------------------------


async def run_dividend_detection(db: AsyncSession) -> dict:
    """Worker-Entry-Point. Iteriert pro User getrennt; pro User wird ein
    Sub-Loop mit Per-User-Sem(3) und globalem Sem(20) ueber dessen aktive
    stock/etf-Positionen gefahren.

    Hinweis: ``db`` wird hier nur fuer das initiale ``DISTINCT user_id``-
    Lookup genutzt. Jede ``_detect_for_position``-Coroutine oeffnet ihre
    eigene ``async_session()`` — AsyncSession ist nicht thread-/concurrency-
    safe fuer parallele commit()s.
    """
    from db import async_session

    stats = {
        "created": 0,
        "matched": 0,
        "skipped": 0,
        "skipped_split": 0,
        "errors": 0,
    }

    # Distinct active stock/ETF user_ids
    user_ids_result = await db.execute(
        select(Position.user_id).where(
            Position.is_active.is_(True),
            Position.type.in_([AssetType.stock, AssetType.etf]),
            Position.shares > 0,
        ).distinct()
    )
    user_ids = [row[0] for row in user_ids_result.all()]
    logger.info("dividend_detection_start users=%s", len(user_ids))

    for uid in user_ids:
        try:
            await _detect_for_user(uid, stats, async_session)
        except Exception:
            stats["errors"] += 1
            logger.exception("dividend_detection_user_failed user=%s", uid)

    logger.info(
        "dividend_detection_done created=%s matched=%s skipped=%s "
        "skipped_split=%s errors=%s",
        stats["created"], stats["matched"], stats["skipped"],
        stats["skipped_split"], stats["errors"],
    )
    return stats


async def _detect_for_user(
    user_id: uuid.UUID,
    stats: dict,
    session_factory,
) -> None:
    """Detection-Loop fuer einen einzelnen User.

    ``session_factory`` ist ``db.async_session`` — wir oeffnen pro
    Position eine separate Session, damit parallele commit()s sich nicht
    in die Quere kommen.
    """
    # Snapshot der Positionen + Lookback-Entscheidung in einer kurzlebigen
    # Session — danach geben wir sie wieder frei.
    async with session_factory() as snap_db:
        pos_result = await snap_db.execute(
            select(Position).where(
                Position.user_id == user_id,
                Position.is_active.is_(True),
                Position.type.in_([AssetType.stock, AssetType.etf]),
                Position.shares > 0,
            )
        )
        positions = pos_result.scalars().all()
        if not positions:
            return

        has_any = await snap_db.scalar(
            select(func.count())
            .select_from(PendingDividend)
            .where(PendingDividend.user_id == user_id)
        )
        # Detach: SQLAlchemy-Objekte sind nach Session-Close abgekoppelt — wir
        # verwenden die Werte nur read-only in den Coroutinen.
        snapshot = [
            {
                "id": p.id,
                "ticker": p.ticker,
                "yfinance_ticker": p.yfinance_ticker,
                "currency": p.currency,
            }
            for p in positions
        ]

    lookback_days = (
        DIVIDEND_LOOKBACK_ROLLING_DAYS if (has_any or 0) > 0
        else DIVIDEND_LOOKBACK_INITIAL_DAYS
    )
    since_date = date.today() - timedelta(days=lookback_days)

    sem_user = asyncio.Semaphore(3)
    coros = [
        _detect_for_position(
            session_factory,
            user_id,
            pos,
            since_date,
            sem_user,
            _GLOBAL_YFINANCE_SEM,
            stats,
        )
        for pos in snapshot
    ]
    await asyncio.gather(*coros, return_exceptions=False)


async def _detect_for_position(
    session_factory,
    user_id: uuid.UUID,
    position: dict,
    since_date: date,
    sem_user: asyncio.Semaphore,
    sem_global: asyncio.Semaphore,
    stats: dict,
) -> None:
    """Detection fuer eine einzelne Position.

    WICHTIG (Heilige Regel #7 + Plan ⚠): Nutzt ``yf_download(actions=True)``
    via ``asyncio.to_thread`` — KEIN direktes ``yf.Ticker(t).dividends``!
    Yahoo blockt den Default-User-Agent (Chrome 39), ``yf_download`` setzt
    Chrome 131 + frische ``requests.Session``.

    Eigene DB-Session pro Position (AsyncSession ist nicht concurrency-safe
    fuer parallele commit()s).

    yfinance accepts only the period set ``['1d','5d','1mo','3mo','6mo',
    '1y',...]``. We always request ``3mo`` (the next valid step above 35d)
    and filter tighter on ``since_date`` application-side.
    """
    ticker = position.get("yfinance_ticker") or position.get("ticker")
    if not ticker:
        stats["skipped"] += 1
        return

    # Pseudo-Ticker (Cash, PE, Pension, Real-Estate) NICHT an yfinance schicken.
    # Diese werden vom is_active/type-Filter im Caller bereits ausgeschlossen,
    # aber Defense-in-Depth: short-circuit bei unbekanntem Format.
    if " " in ticker or ticker.startswith("$"):
        stats["skipped"] += 1
        return

    position_id = position["id"]
    div_currency = position.get("currency") or "USD"

    # yfinance accepts only ['1d','5d','1mo','3mo','6mo','1y',...]. Both
    # Initial-Seeding (90d) and Rolling (35d) are mapped to '3mo' — the next
    # valid step above 35d. since_date filters tighter on the application side.
    period = "3mo"

    async with sem_user:
        async with sem_global:
            try:
                df = await asyncio.to_thread(
                    yf_download,
                    ticker,
                    period=period,
                    actions=True,
                )
            except Exception as e:
                stats["errors"] += 1
                logger.warning(
                    "dividend_yfinance_error ticker=%s user=%s error=%s",
                    ticker, user_id, e,
                )
                return

    if df is None or df.empty:
        stats["skipped"] += 1
        return

    # Single-Ticker yf_download liefert Multi-Index-Columns mit dem Ticker
    # als level=1 ('Dividends', ticker) und ('Stock Splits', ticker). Falls
    # ein Single-Level-Format zurueckkommt (yfinance-Versions-Drift), lesen
    # wir die Spalte direkt.
    divs_series = _extract_column(df, "Dividends", ticker)
    splits_series = _extract_column(df, "Stock Splits", ticker)
    if divs_series is None:
        stats["skipped"] += 1
        return

    # Splits im Lookback-Fenster → Position skippen (R2). yfinance liefert
    # split-adjustierte Dividenden, unsere Shares sind nominal — Mischung
    # waere falsch. User erfasst die geskippten Dividenden manuell.
    if splits_series is not None:
        splits_in_window = splits_series[splits_series > 0]
        if not splits_in_window.empty:
            first_split = splits_in_window.index[0]
            split_date = (
                first_split.date()
                if hasattr(first_split, "date") else first_split
            )
            logger.warning(
                "split_skip ticker=%s user=%s split_date=%s",
                ticker, user_id, split_date,
            )
            stats["skipped_split"] += 1
            return

    # Dividenden-Events
    div_events = divs_series[divs_series > 0]
    if div_events.empty:
        stats["skipped"] += 1
        return

    # Auf since_date filtern
    div_events = div_events[div_events.index.date >= since_date]
    if div_events.empty:
        stats["skipped"] += 1
        return

    # FX-Rate fuer "expected_gross_chf" (Worker-Snapshot, beim Confirm wird
    # via R5 die historische FX neu berechnet)
    fx_rate_now = get_fx_rate(div_currency, "CHF") or 1.0

    # Pro-Position eine eigene Session — verhindert IllegalStateChange-Errors
    # bei parallelem commit() ueber gather().
    async with session_factory() as db:
        # Transaktionen einmal laden (read-only fuer shares-Rekonstruktion)
        txn_result = await db.execute(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.position_id == position_id,
            ).order_by(Transaction.date.asc(), Transaction.created_at.asc())
        )
        all_txns = list(txn_result.scalars().all())

        for ex_ts, dps in div_events.items():
            ex_date = ex_ts.date() if hasattr(ex_ts, "date") else ex_ts
            dps_float = float(dps)
            if dps_float <= 0:
                continue

            # Bereits vorhanden? (UNIQUE schuetzt zusaetzlich)
            existing = await db.execute(
                select(PendingDividend).where(
                    PendingDividend.user_id == user_id,
                    PendingDividend.position_id == position_id,
                    PendingDividend.ex_date == ex_date,
                )
            )
            if existing.scalars().first() is not None:
                continue

            shares_at = _reconstruct_shares_at_date(all_txns, ex_date)
            if shares_at <= 0:
                stats["skipped"] += 1
                continue

            expected_gross_chf = round(shares_at * dps_float * fx_rate_now, 2)
            if expected_gross_chf <= 0:
                stats["skipped"] += 1
                continue

            # Auto-Match-Check: existiert eine `dividend`-Transaktion innerhalb
            # ±35d, die noch keinem Pending zugeordnet ist?
            match_start = ex_date - timedelta(days=DIVIDEND_MATCH_WINDOW_DAYS)
            match_end = ex_date + timedelta(days=DIVIDEND_MATCH_WINDOW_DAYS)
            match_result = await db.execute(
                select(Transaction).where(
                    Transaction.user_id == user_id,
                    Transaction.position_id == position_id,
                    Transaction.type == TransactionType.dividend,
                    Transaction.date >= match_start,
                    Transaction.date <= match_end,
                ).order_by(
                    func.abs(Transaction.date - ex_date).asc()
                ).limit(1)
            )
            existing_txn = match_result.scalars().first()

            # Stelle sicher, dass die Transaktion nicht schon einem anderen
            # Pending-Eintrag zugeordnet ist (zwei monatliche REIT-Pendings
            # duerfen nicht denselben Match-Partner schnappen).
            if existing_txn is not None:
                already = await db.scalar(
                    select(func.count())
                    .select_from(PendingDividend)
                    .where(
                        PendingDividend.matched_transaction_id == existing_txn.id
                    )
                )
                if already and already > 0:
                    existing_txn = None

            new_pending = PendingDividend(
                user_id=user_id,
                position_id=position_id,
                ex_date=ex_date,
                dividend_per_share=Decimal(str(round(dps_float, 6))),
                currency=div_currency,
                shares_at_ex_date=Decimal(str(round(shares_at, 8))),
                expected_gross_chf=Decimal(str(expected_gross_chf)),
                status=STATUS_CONFIRMED if existing_txn else STATUS_PENDING,
                matched_transaction_id=existing_txn.id if existing_txn else None,
            )
            db.add(new_pending)
            try:
                await db.commit()
            except IntegrityError:
                # Race: anderer Worker-Run / paralleler Insert hat den UNIQUE
                # bereits beansprucht. Nicht fatal.
                await db.rollback()
                continue

            if existing_txn:
                stats["matched"] += 1
            else:
                stats["created"] += 1


def _extract_column(
    df: pd.DataFrame,
    name: str,
    ticker: str,
) -> pd.Series | None:
    """Tolerant column-extraction fuer yf_download(actions=True).

    Single-ticker calls liefern manchmal einen einfachen Column-Index
    (Spalte ``name``), manchmal MultiIndex ``(name, ticker)``. Diese Helper
    abstrahiert den Versions-Drift.
    """
    try:
        if isinstance(df.columns, pd.MultiIndex):
            # versuch ('Dividends', ticker), fallback erste Ticker-Spalte
            if (name, ticker) in df.columns:
                return df[(name, ticker)]
            try:
                sub = df.xs(name, axis=1, level=0)
                if isinstance(sub, pd.DataFrame) and not sub.empty:
                    return sub.iloc[:, 0]
            except (KeyError, ValueError):
                return None
            return None
        if name in df.columns:
            return df[name]
    except Exception as e:
        logger.debug("extract_column_failed name=%s ticker=%s error=%s", name, ticker, e)
    return None


# --- Weekly Email Digest (R6) ----------------------------------------------


async def _send_weekly_pending_dividends_digest() -> dict:
    """Versende einen wochentlichen Digest aller offenen Pending-Dividenden
    pro User. Email an User mit ``category="pending_dividend"`` +
    ``notify_email=True``, ntfy-Push an User mit ``notify_push=True``.

    Worker-Entry-Point — erstellt eigene DB-Session.
    Liefert Stats-Dict (gesendet/uebersprungen/errors) fuer Logging.
    """
    from db import async_session
    from services import cache as redis_cache
    from services.email_service import send_email
    from services.ntfy_service import send_push_aggregated

    stats = {"sent": 0, "skipped": 0, "errors": 0, "pushed": 0}

    async with async_session() as db:
        # Alle User mit aktiver Notification (Email ODER Push) fuer pending_dividend
        pref_result = await db.execute(
            select(AlertPreference).where(
                AlertPreference.category == "pending_dividend",
                AlertPreference.is_enabled.is_(True),
            )
        )
        prefs = pref_result.scalars().all()
        # Filter: mindestens ein Notification-Kanal aktiv. Niemals User mischen
        # — pro pref iterieren, damit Multi-User-Bucket-Isolation gewahrt bleibt.
        prefs = [p for p in prefs if p.notify_email or p.notify_push]
        if not prefs:
            return stats

        for pref in prefs:
            try:
                count = await db.scalar(
                    select(func.count())
                    .select_from(PendingDividend)
                    .where(
                        PendingDividend.user_id == pref.user_id,
                        PendingDividend.status == STATUS_PENDING,
                    )
                )
                if not count:
                    stats["skipped"] += 1
                    continue

                user = await db.get(User, pref.user_id)
                if not user or not user.is_active or not user.email:
                    stats["skipped"] += 1
                    continue

                # Pending-Liste mit Position-Meta
                rows = await db.execute(
                    select(PendingDividend, Position)
                    .join(Position, Position.id == PendingDividend.position_id)
                    .where(
                        PendingDividend.user_id == pref.user_id,
                        PendingDividend.status == STATUS_PENDING,
                    )
                    .order_by(PendingDividend.ex_date.desc())
                    .limit(50)
                )
                items = rows.all()
                if not items:
                    stats["skipped"] += 1
                    continue

                # Email-Pfad: nur wenn notify_email gesetzt ist.
                if pref.notify_email:
                    smtp_cfg = await db.get(SmtpConfig, pref.user_id)
                    subject, body = _build_digest_email(items, user_email=user.email)

                    ok = await send_email(user.email, subject, body, smtp_cfg=smtp_cfg)
                    if ok:
                        stats["sent"] += 1
                    else:
                        stats["errors"] += 1

                # Push-Pfad: laeuft NACH dem Email-Pfad. Severity 'info' weil
                # Dividenden-Digest nicht akut ist. Per-Aggregat-Dedup in
                # ntfy_service stellt sicher, dass pro User+Tag nur ein Push
                # rausgeht — auch wenn der Job (versehentlich) mehrfach laeuft.
                if pref.notify_push:
                    from models.ntfy_config import NtfyConfig
                    ntfy_cfg = await db.get(NtfyConfig, pref.user_id)
                    if ntfy_cfg:
                        push_alerts: list[dict] = []
                        for pending, position in items:
                            ticker = position.ticker
                            ex_date_str = pending.ex_date.strftime("%d.%m.%Y")
                            gross = float(pending.expected_gross_chf)
                            push_alerts.append({
                                "title": f"Offene Dividende: {ticker}",
                                "message": f"Ex-Date {ex_date_str} — ~ CHF {gross:.2f}",
                                "severity": "info",
                            })
                        send_push_aggregated(
                            ntfy_cfg=ntfy_cfg,
                            category="pending_dividend",
                            alerts=push_alerts,
                            redis_client=redis_cache,
                            force_aggregate=True,
                        )
                        stats["pushed"] += 1
            except Exception:
                stats["errors"] += 1
                logger.exception(
                    "pending_dividend_digest_failed user=%s", pref.user_id
                )

    logger.info(
        "pending_dividend_digest_done sent=%s pushed=%s skipped=%s errors=%s",
        stats["sent"], stats["pushed"], stats["skipped"], stats["errors"],
    )
    return stats


# Template-Pfad: backend/templates/email/pending_dividends_digest.html
_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "templates" / "email" / "pending_dividends_digest.html"
)


def _load_digest_template() -> Template:
    """Read the HTML template from disk. Cheap enough to do per-call
    (digest runs once a week per user); avoids stale-cache surprises in tests.
    """
    with _TEMPLATE_PATH.open("r", encoding="utf-8") as fh:
        return Template(fh.read())


def _build_digest_email(
    items: list[tuple],
    *,
    user_email: str | None = None,
    dashboard_url: str | None = None,
) -> tuple[str, str]:
    """Erstelle Subject + HTML-Body fuer den Digest. Reine Text-Funktion,
    keine I/O ausser Template-Read — Tests koennen sie pur aufrufen.
    """
    from config import settings

    n = len(items)
    subject = f"OpenFolio: {n} offene Dividende{'n' if n != 1 else ''}"

    rows_html_parts = []
    for pending, position in items:
        ticker = position.ticker
        name = position.name or ticker
        ex_date_str = pending.ex_date.strftime("%d.%m.%Y")
        gross = float(pending.expected_gross_chf)
        rows_html_parts.append(
            "<tr style=\"border-bottom:1px solid #333;\">"
            f"<td style=\"padding:8px;color:#fff;font-weight:bold;\">{ticker}</td>"
            f"<td style=\"padding:8px;color:#9ca3af;\">{name}</td>"
            f"<td style=\"padding:8px;color:#9ca3af;\">{ex_date_str}</td>"
            f"<td style=\"padding:8px;color:#10b981;text-align:right;\">~ CHF {gross:.2f}</td>"
            "</tr>"
        )
    rows_html = "".join(rows_html_parts)

    body = _load_digest_template().safe_substitute(
        rows_html=rows_html,
        user_email=user_email or "",
        dashboard_url=dashboard_url or settings.frontend_url,
    )
    return subject, body
