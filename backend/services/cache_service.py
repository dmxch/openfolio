import asyncio
import json
import logging
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
from yf_patch import yf_download, yf_quote_currency
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import SyncSessionLocal, async_session
from models.position import AssetType, Position
from models.price_cache import PriceCache
from models.watchlist import WatchlistItem
from services import cache
from services.sector_analyzer import SECTOR_ETFS

# Position-Types, die keine Yahoo-tradeable Instrumente sind und deshalb nicht
# in den Yahoo-Batch gehören (Cash-Konten, PE, Immobilien, Vorsorge).
_NON_YAHOO_TYPES = {
    AssetType.cash,
    AssetType.private_equity,
    AssetType.real_estate,
    AssetType.pension,
}

logger = logging.getLogger(__name__)


def _quote_currency(ticker: str) -> str | None:
    """Echte Quote-Währung eines Tickers via yfinance fast_info (7d-Cache).

    LSE-Suffix .L sagt NICHTS über die Währung: SWDA.L quotiert in Pence
    (GBp), EIMI.L in USD. None = unbekannt (yf-Fehler), wird nicht gecached.
    Blocking bei Cache-Miss (yf-Call) — aus async nur via to_thread.
    """
    key = f"quote_currency:{ticker}"
    cur = cache.get(key)
    if cur is None:
        cur = yf_quote_currency(ticker)
        if cur is None:
            return None
        if cur.upper() == "GBX":
            cur = "GBp"
        cache.set(key, cur, ttl=7 * 86400)
    return cur


def _pence_divisor(ticker: str) -> float:
    """1.0 oder 100.0 — Divisor für Pence-quotierte .L-Ticker (GBp/GBX).

    yfinance liefert viele LSE-Titel in Pence ("GBp"). Ohne Division wäre
    jede Live-Bewertung 100× zu hoch (Review 2026-06-10, H2 — die GBX-
    Erkennung existierte vorher nur im Snapshot-Regen-Pfad). Unbekannte
    Quote-Währung → 1.0 (kein Raten).
    """
    if not ticker.endswith(".L"):
        return 1.0
    return 100.0 if _quote_currency(ticker) == "GBp" else 1.0


def _resolved_currency(ticker: str) -> str:
    """Währungs-Label für Cache-Zeilen: echte Quote-Währung wenn bekannt
    (GBp → GBP, da Preise nach _pence_divisor in Pfund liegen), sonst
    Suffix-Heuristik."""
    if ticker.endswith(".L"):
        cur = _quote_currency(ticker)
        if cur == "GBp":
            return "GBP"
        if cur:
            return cur
    return get_ticker_currency(ticker)


def get_ticker_currency(ticker: str) -> str:
    """Derive currency from ticker suffix instead of hardcoding USD."""
    if ticker.endswith(".SW"):
        return "CHF"
    elif ticker.endswith(".L"):
        return "GBP"
    elif ticker.endswith(".TO"):
        return "CAD"
    elif ticker.endswith(".AS") or ticker.endswith(".DE"):
        return "EUR"
    elif "=X" in ticker:
        return "FX"
    else:
        return "USD"


# --- Shared refresh state via app_config DB table ---

_REFRESH_STATE_KEY = "cache_refresh_state"

# Local in-memory lock to prevent concurrent refreshes within the same worker
_refresh_lock = threading.Lock()
_local_refreshing = False


async def _load_refresh_state_from_db() -> dict:
    """Load refresh state from app_config table (shared across all workers)."""
    try:
        async with async_session() as db:
            result = await db.execute(
                text("SELECT value FROM app_config WHERE key = :key"),
                {"key": _REFRESH_STATE_KEY},
            )
            row = result.scalar()
            if row:
                return json.loads(row)
    except Exception as e:
        logger.debug(f"Failed to load refresh state from DB: {e}")
    return {
        "last_refresh": None,
        "started_at": None,
        "ticker_count": 0,
        "status": "idle",
        "refreshing": False,
        "errors": [],
    }


async def _save_refresh_state_to_db(state: dict):
    """Persist refresh state to app_config table."""
    try:
        from models.app_config import AppConfig
        async with async_session() as db:
            now = datetime.now(timezone.utc)
            stmt = pg_insert(AppConfig).values(
                key=_REFRESH_STATE_KEY,
                value=json.dumps(state, default=str),
                updated_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at},
            )
            await db.execute(stmt)
            await db.commit()
    except Exception as e:
        logger.warning(f"Failed to save refresh state to DB: {e}")


# Keep a synchronous in-memory snapshot for the legacy API (updated from DB)
_refresh_state = {
    "last_refresh": None,
    "started_at": None,
    "ticker_count": 0,
    "status": "idle",
    "refreshing": False,
    "errors": [],
}


async def get_refresh_state() -> dict:
    state = await _load_refresh_state_from_db()
    if state.get("refreshing") and state.get("started_at"):
        try:
            started = datetime.fromisoformat(state["started_at"].replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            state["elapsed_seconds"] = int(elapsed)
            # Auto-clear stale refreshing state (>120s = something crashed)
            if elapsed > 120:
                state["refreshing"] = False
                state["status"] = "timeout"
                state["started_at"] = None
                state["errors"] = ["Refresh abgebrochen (Timeout)"]
                await _save_refresh_state_to_db(state)
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not parse started_at timestamp in get_refresh_state: {e}")
    return state


async def is_refreshing() -> bool:
    state = await _load_refresh_state_from_db()
    if state.get("refreshing") and state.get("started_at"):
        try:
            started = datetime.fromisoformat(state["started_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - started).total_seconds() > 120:
                return False
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not parse started_at timestamp in is_refreshing: {e}")
    return state.get("refreshing", False)


# JPY gehört dazu: services/utils unterstützt JPY voll, aber ohne Worker-
# Refresh fehlte JPYCHF im shared fx_rates-Dict und der Snapshot-Pfad fiel
# still auf fx=1.0 zurück → JPY-Positionen ~167× zu hoch bewertet
# (Review 2026-06-10, M4).
FX_PAIRS = ["USDCHF=X", "EURCHF=X", "CADCHF=X", "GBPCHF=X", "JPYCHF=X"]
MARKET_TICKERS = ["^GSPC", "^VIX", "SPY", "GC=F", "SI=F", "DX-Y.NYB", "^TNX"]


async def collect_all_tickers(db: AsyncSession) -> dict:
    """Collect all tickers needed from positions, watchlist, sectors, FX, etc."""
    yahoo_tickers = set()
    crypto = []

    # Active positions
    result = await db.execute(select(Position).where(Position.is_active == True))  # noqa: E712
    positions = result.scalars().all()
    for pos in positions:
        if pos.type in _NON_YAHOO_TYPES:
            continue
        if pos.coingecko_id:
            crypto.append((pos.coingecko_id, pos.ticker))
        elif pos.type == AssetType.crypto:
            # Crypto-Position ohne CoinGecko-ID: Datenfehler — überspringen,
            # statt einen Pseudo-Ticker an Yahoo zu senden.
            logger.warning(f"Skipping crypto position without coingecko_id: {pos.ticker} (id={pos.id})")
            continue
        elif pos.gold_org:
            # Edelmetall: Spot-CHF-Preis kommt via _fetch_metals (Gold.org oder
            # USD-Futures × FX). Die Futures ebenfalls in den yahoo-Batch
            # aufnehmen, damit _fetch_metals den Redis-/DB-Cache findet statt
            # synchrone yfinance-Einzel-Calls zu machen.
            from services.precious_metals_service import get_metal_futures
            fut = get_metal_futures(pos.ticker)
            if fut:
                yahoo_tickers.add(fut[0])
        else:
            ticker = pos.yfinance_ticker or pos.ticker
            yahoo_tickers.add(ticker)

    # Watchlist
    result = await db.execute(select(WatchlistItem).where(WatchlistItem.is_active == True))  # noqa: E712
    watchlist = result.scalars().all()
    for item in watchlist:
        yahoo_tickers.add(item.ticker)

    # Sector ETFs + market indices
    yahoo_tickers.update(SECTOR_ETFS.keys())
    yahoo_tickers.update(MARKET_TICKERS)

    return {
        "yahoo_tickers": list(yahoo_tickers),
        "fx_pairs": FX_PAIRS,
        "crypto": crypto,
        # Spot-Ticker aller aktiven Edelmetall-Positionen (Gold/Silber/Platin/Palladium).
        # Wird vom Worker genutzt um pro Metall den Live-CHF-Preis zu holen.
        "metal_spot_tickers": sorted({pos.ticker for pos in positions if pos.gold_org}),
        "positions": positions,
    }


def _download_yahoo_batch(tickers: list[str]) -> dict:
    """Download prices for all yahoo tickers in one batch. Runs in thread."""
    if not tickers:
        return {}

    results = {}
    all_tickers = tickers
    ticker_str = " ".join(all_tickers)

    try:
        data = yf_download(ticker_str, period="5d", progress=False, group_by="ticker")
        if data.empty:
            return results

        # group_by="ticker" liefert eine MultiIndex-Spalte (ticker, "Close") —
        # auch bei nur einem Ticker. Single-Level-Spalten (data["Close"]) gibt es
        # nur, wenn yfinance ausnahmsweise ohne Ticker-Ebene zurueckkommt.
        multi = isinstance(data.columns, pd.MultiIndex)
        for ticker in all_tickers:
            try:
                if multi:
                    close = data[ticker]["Close"].dropna()
                else:
                    close = data["Close"].dropna()
                if len(close) > 0:
                    divisor = _pence_divisor(ticker)
                    current = float(close.iloc[-1]) / divisor
                    prev = (float(close.iloc[-2]) / divisor) if len(close) > 1 else current
                    change_pct = ((current / prev) - 1) * 100 if prev else 0
                    results[ticker] = {
                        "price": round(current, 4),
                        "currency": _resolved_currency(ticker),
                        "change_pct": round(change_pct, 2),
                    }
            except (KeyError, IndexError) as e:
                logger.debug(f"Could not extract price data for {ticker}: {e}")
                continue
    except Exception as e:
        logger.error(f"Yahoo batch download failed: {e}")

    return results


async def _fetch_crypto_batch(crypto_list: list[tuple[str, str]]) -> dict:
    """Fetch all crypto prices from CoinGecko in one request."""
    if not crypto_list:
        return {}

    results = {}
    ids = ",".join(cg_id for cg_id, _ in crypto_list)

    try:
        from services.api_utils import fetch_json_coingecko
        url = f"{settings.coingecko_base_url}/simple/price"
        params = {"ids": ids, "vs_currencies": "chf", "include_24hr_change": "true"}
        data = await fetch_json_coingecko(url, params=params)

        for cg_id, ticker in crypto_list:
            if cg_id in data:
                coin = data[cg_id]
                results[ticker] = {
                    "price": coin["chf"],
                    "currency": "CHF",
                    "change_pct": round(coin.get("chf_24h_change", 0), 2),
                    "source": "coingecko",
                }
    except Exception as e:
        logger.error(f"CoinGecko batch fetch failed: {e}")

    return results


def _fetch_metals(spot_tickers: list[str]) -> dict:
    """Fetch live CHF prices for all precious-metal positions. Runs in thread.

    Returns a dict keyed by spot ticker (z.B. 'XAUCHF=X') with the CHF price.
    Gold nutzt Gold.org; Silber/Platin/Palladium nutzen yfinance-Futures × FX
    (siehe services.price_service.get_metal_price_chf).
    """
    from services.price_service import get_metal_price_chf
    out = {}
    for ticker in spot_tickers:
        # fx_rates im Worker erst nach dem yahoo-Batch vollstaendig — get_metal_price_chf
        # faellt notfalls auf den DB-Cache von USDCHF=X zurueck (fallback_days=5).
        result = get_metal_price_chf(ticker)
        if result:
            out[ticker] = {**result, "source": "metal_spot"}
    return out


async def _run_with_timeout(coro, timeout: int, label: str):
    """Run a coroutine with a timeout, returning the result or an exception."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"{label} timed out after {timeout}s")


async def seed_position_price(db: AsyncSession, pos: Position) -> bool:
    """Best-effort Sofort-Fetch fuer eine einzelne (neu angelegte) Position.

    Holt synchron ueber den passenden Provider einen Live-Kurs und schreibt ihn in
    price_cache, positions.current_price und den In-Memory-Cache. Umgeht damit das
    is_extended_hours-Gate des Workers: eine ausserhalb der Handelszeiten angelegte
    Position bleibt sonst bis zum naechsten Refresh-Fenster kurslos.

    Liefert True, wenn ein Kurs geschrieben wurde. Wirft nie — der Caller soll den
    Position-Create nicht an einem fehlgeschlagenen Kurs-Fetch scheitern lassen.
    """
    if pos.type in _NON_YAHOO_TYPES or pos.gold_org:
        return False
    try:
        if pos.coingecko_id:
            results = await _fetch_crypto_batch([(pos.coingecko_id, pos.ticker)])
            key = pos.ticker
        elif pos.type == AssetType.crypto:
            return False  # Crypto ohne coingecko_id — kein Provider
        else:
            key = pos.yfinance_ticker or pos.ticker
            results = await asyncio.to_thread(_download_yahoo_batch, [key])

        data = results.get(key)
        if not data:
            return False

        stmt = pg_insert(PriceCache).values([{
            "ticker": key,
            "date": date.today(),
            "close": data["price"],
            "currency": data.get("currency", "USD"),
            "source": data.get("source", "yahoo"),
        }])
        stmt = stmt.on_conflict_do_update(
            constraint="uq_ticker_date",
            set_={"close": stmt.excluded.close, "currency": stmt.excluded.currency, "source": stmt.excluded.source},
        )
        await db.execute(stmt)
        pos.current_price = data["price"]
        await db.commit()

        if pos.coingecko_id:
            cache.set(f"crypto:{pos.coingecko_id}", {
                "price": data["price"], "currency": data.get("currency", "CHF"),
                "change_pct": data.get("change_pct", 0),
            })
        else:
            cache.set(f"price:{key}", {
                "price": data["price"], "currency": data.get("currency", "USD"),
                "change_pct": data.get("change_pct", 0),
            })
        logger.info(f"Seeded live price for new position {pos.ticker} ({key}): {data['price']}")
        return True
    except Exception:
        logger.warning(f"Could not seed live price for new position {pos.ticker}", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        return False


def trigger_position_price_seed(position_id: uuid.UUID) -> None:
    """Fire-and-forget Sofort-Fetch fuer eine neu angelegte Position.

    Laeuft im Hintergrund mit eigener DB-Session (blockiert die API-Response nicht
    und teilt nicht die Request-Transaktion). Mirror von trigger_snapshot_regen.
    """
    asyncio.create_task(_seed_safe(position_id))


async def _seed_safe(position_id: uuid.UUID) -> None:
    """Lade die Position in einer eigenen Session und seede ihren Live-Kurs."""
    try:
        async with async_session() as db:
            pos = await db.get(Position, position_id)
            if pos is None or not pos.is_active:
                return
            await seed_position_price(db, pos)
            # Historie gleich mit — sonst startet der DB-Fallback fuer
            # MA-/MRS-Analysen bei 1 Zeile und braucht Monate zum Auffuellen
            # (Befund TSM 2026-06-10: MRS leer, weil yf im Web-Prozess klemmte
            # und price_cache erst ab Kaufdatum gefuellt war).
            if pos.type not in _NON_YAHOO_TYPES and not pos.gold_org and not pos.coingecko_id:
                await backfill_price_history(db, pos.yfinance_ticker or pos.ticker)
    except Exception:
        logger.warning(f"Background price seed failed for position {position_id}", exc_info=True)


async def backfill_price_history(db: AsyncSession, ticker: str, period: str = "2y") -> int:
    """Backfill daily closes fuer einen Ticker in price_cache (idempotent, on_conflict_do_nothing).

    Zweck: der DB-Fallback von ``_get_close_series`` traegt nur, wenn genug
    Historie liegt — MRS braucht >= 14 Wochen, die 200-DMA 200 Tage. Ohne
    Backfill akkumuliert price_cache erst ab Anlage-Datum der Position.
    Liefert die Anzahl geschriebener Zeilen (0 bei Fehler — wirft nie).
    """
    import pandas as pd
    from models.price_cache import PriceCache
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    try:
        data = await asyncio.to_thread(lambda: yf_download(ticker, period=period, progress=False))
        if data.empty:
            logger.warning(f"Price history backfill: yfinance returned empty for {ticker}")
            return 0
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()
        if close.empty:
            return 0

        currency = await asyncio.to_thread(_resolved_currency, ticker)
        divisor = await asyncio.to_thread(_pence_divisor, ticker)
        rows = [
            {
                "ticker": ticker,
                "date": (dt.date() if hasattr(dt, "date") else dt),
                "close": round(float(price) / divisor, 4),
                "currency": currency,
                "source": "yahoo",
            }
            for dt, price in close.items()
        ]
        stmt = pg_insert(PriceCache).values(rows).on_conflict_do_nothing()
        await db.execute(stmt)
        await db.commit()
        logger.info(f"Backfilled {len(rows)} historical closes for {ticker} ({period})")
        return len(rows)
    except Exception:
        logger.warning(f"Price history backfill failed for {ticker}", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        return 0


# Chunk-Groesse fuer das gebatchte positions.current_price-UPDATE — haelt die
# Anzahl Bind-Parameter pro Statement klein (2 Parameter pro Ticker).
_PRICE_UPDATE_CHUNK = 500


async def _update_position_prices_batch(
    db: AsyncSession, price_rows: list[tuple[str, float]]
) -> None:
    """Batch-Update von positions.current_price in EINEM Statement pro Chunk.

    Ersetzt den frueheren per-Ticker-UPDATE-Loop (1 DB-Roundtrip pro
    Universum-Ticker inkl. Watchlist). Beide Match-Spalten werden wie zuvor
    beruecksichtigt (ticker UND yfinance_ticker); bei Doppel-Match gewinnt
    deterministisch yfinance_ticker — das ist der aufgeloeste Daten-Ticker
    (vgl. collect_all_tickers). CASE-Variante statt UPDATE .. FROM (VALUES ..),
    damit das Statement auch auf SQLite (Test-Suite) laeuft. gold_org-Positionen
    sind ausgenommen (Edelmetall-Spotpreise werden separat gesetzt).
    """
    if not price_rows:
        return
    for start in range(0, len(price_rows), _PRICE_UPDATE_CHUNK):
        chunk = price_rows[start:start + _PRICE_UPDATE_CHUNK]
        params: dict[str, object] = {}
        yf_whens: list[str] = []
        ticker_whens: list[str] = []
        ticker_binds: list[str] = []
        for i, (ticker, price) in enumerate(chunk):
            params[f"t{i}"] = ticker
            params[f"p{i}"] = price
            yf_whens.append(f"WHEN yfinance_ticker = :t{i} THEN CAST(:p{i} AS NUMERIC)")
            ticker_whens.append(f"WHEN ticker = :t{i} THEN CAST(:p{i} AS NUMERIC)")
            ticker_binds.append(f":t{i}")
        in_list = ", ".join(ticker_binds)
        stmt = text(
            "UPDATE positions SET current_price = COALESCE("
            f"CASE {' '.join(yf_whens)} END, "
            f"CASE {' '.join(ticker_whens)} END) "
            f"WHERE (ticker IN ({in_list}) OR yfinance_ticker IN ({in_list})) "
            "AND gold_org = false AND is_active = true"
        )
        await db.execute(stmt, params)


async def refresh_cache(db: AsyncSession, silent: bool = False) -> dict:
    """Main refresh: batch-download all prices and populate DB + in-memory cache.

    Args:
        silent: If True, don't update the refreshing state in DB (used by Worker
                to avoid the CacheStatus spinner triggering on every 60s cycle).
    """
    global _local_refreshing
    with _refresh_lock:
        if _local_refreshing:
            return {"status": "already_refreshing"}
        _local_refreshing = True

    try:
        # Check shared DB state (another worker might be refreshing)
        db_state = await _load_refresh_state_from_db()
        if db_state.get("refreshing"):
            try:
                started = datetime.fromisoformat(db_state["started_at"].replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - started).total_seconds() < 120:
                    return {"status": "already_refreshing", "started_at": db_state["started_at"]}
            except (ValueError, TypeError) as e:
                logger.debug(f"Could not parse started_at in refresh_cache check: {e}")

        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not silent:
            await _save_refresh_state_to_db({
                "refreshing": True, "status": "refreshing", "started_at": started_at,
                "last_refresh": db_state.get("last_refresh"), "ticker_count": 0, "errors": [],
            })
        errors = []

        tickers_info = await collect_all_tickers(db)
        all_yahoo = tickers_info["yahoo_tickers"] + tickers_info["fx_pairs"]

        logger.info(f"Refreshing {len(all_yahoo)} yahoo tickers, {len(tickers_info['crypto'])} crypto...")

        # Run all fetches in parallel with individual timeouts
        from services.property_service import fetch_saron_rate
        yahoo_task = _run_with_timeout(asyncio.to_thread(_download_yahoo_batch, all_yahoo), 120, "Yahoo")
        crypto_task = _run_with_timeout(_fetch_crypto_batch(tickers_info["crypto"]), 10, "CoinGecko")
        async def _noop(): return {}
        metal_spot_tickers = tickers_info["metal_spot_tickers"]
        metals_task = (
            _run_with_timeout(asyncio.to_thread(_fetch_metals, metal_spot_tickers), 15, "Metals")
            if metal_spot_tickers else _noop()
        )
        saron_task = _run_with_timeout(fetch_saron_rate(), 10, "SARON")

        try:
            yahoo_results, crypto_results, metal_results, saron_result = await asyncio.gather(
                yahoo_task, crypto_task, metals_task, saron_task, return_exceptions=True
            )

            if isinstance(yahoo_results, Exception):
                logger.error(f"Yahoo batch failed: {yahoo_results}")
                errors.append(f"Yahoo: {yahoo_results}")
                yahoo_results = {}
            if isinstance(crypto_results, Exception):
                logger.error(f"Crypto batch failed: {crypto_results}")
                errors.append(f"Crypto: {crypto_results}")
                crypto_results = {}
            if isinstance(metal_results, Exception):
                logger.error(f"Metal fetch failed: {metal_results}")
                errors.append(f"Metals: {metal_results}")
                metal_results = {}
            if isinstance(saron_result, Exception):
                errors.append(f"SARON: {saron_result}")
            elif saron_result:
                logger.info(f"SARON updated: {saron_result['rate']}% ({saron_result['date']})")

            # Merge all results. Metal-Keys sind Spot-Ticker wie 'XAUCHF=X' und
            # werden unten separat behandelt (eigener Cache-Key + gezielter UPDATE).
            all_results = {}
            all_results.update(yahoo_results)
            all_results.update(crypto_results)
            all_results.update(metal_results)
            metal_tickers_set = set(metal_spot_tickers)

            # Populate in-memory cache and prepare batch UPSERT
            today = date.today()
            upsert_values = []

            for ticker, data in all_results.items():
                # Populate in-memory cache
                if ticker == "^VIX":
                    vix_val = data["price"]
                    prev_close = vix_val / (1 + data["change_pct"] / 100) if data["change_pct"] else vix_val
                    cache.set("vix", {
                        "value": round(vix_val, 2),
                        "change": round(vix_val - prev_close, 2),
                        "level": "low" if vix_val < 15 else "normal" if vix_val < 20 else "elevated" if vix_val < 30 else "high",
                    })
                elif ticker in FX_PAIRS:
                    pass  # handled below
                elif data.get("source") == "coingecko":
                    # Find coingecko_id for this ticker
                    for cg_id, t in tickers_info["crypto"]:
                        if t == ticker:
                            cache.set(f"crypto:{cg_id}", {
                                "price": data["price"],
                                "currency": "CHF",
                                "change_pct": data["change_pct"],
                            })
                            break
                elif ticker in metal_tickers_set:
                    payload = {
                        "price": data["price"],
                        "currency": "CHF",
                        "change_pct": data["change_pct"],
                    }
                    cache.set(f"metal_chf:{ticker}", payload)
                    # Legacy-Key fuer bestehende Reader (snapshot_service:67,
                    # get_gold_price_chf-Cache). Nur Gold schreibt hier.
                    if ticker == "XAUCHF=X":
                        cache.set("gold_chf", payload)
                else:
                    cache.set(f"price:{ticker}", {
                        "price": data["price"],
                        "currency": data.get("currency", "USD"),
                        "change_pct": data["change_pct"],
                    })

                # Collect for batch UPSERT
                source = data.get("source", "yahoo")
                upsert_values.append({
                    "ticker": ticker,
                    "date": today,
                    "close": data["price"],
                    "currency": data.get("currency", "USD"),
                    "source": source,
                })

            # Batch UPSERT into DB (single statement instead of N individual inserts)
            upserted = 0
            if upsert_values:
                stmt = pg_insert(PriceCache).values(upsert_values)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_ticker_date",
                    set_={"close": stmt.excluded.close, "currency": stmt.excluded.currency, "source": stmt.excluded.source},
                )
                await db.execute(stmt)
                upserted = len(upsert_values)

            # Build FX rates dict from yahoo results and cache it
            fx_rates = {"CHF": 1.0}
            fx_map = {"USDCHF=X": "USD", "EURCHF=X": "EUR", "CADCHF=X": "CAD", "GBPCHF=X": "GBP", "JPYCHF=X": "JPY"}
            for fx_ticker, ccy in fx_map.items():
                if fx_ticker in yahoo_results:
                    fx_rates[ccy] = yahoo_results[fx_ticker]["price"]
            if len(fx_rates) > 1:
                cache.set("fx_rates", fx_rates)

            # H-4: Update positions.current_price from cache results.
            # LOW-price-refresh-batch: EIN gebatchtes Statement statt einem
            # UPDATE pro Universum-Ticker; nur Ticker mit potenziellem
            # Positions-Match (ticker ODER yfinance_ticker) einbeziehen —
            # Watchlist-only-Ticker erzeugen keinen Roundtrip mehr.
            position_match_tickers: set[str] = set()
            for pos in tickers_info["positions"]:
                if pos.gold_org:
                    continue  # Edelmetall: Spotpreis-Pfad unten
                position_match_tickers.add(pos.ticker)
                if pos.yfinance_ticker:
                    position_match_tickers.add(pos.yfinance_ticker)

            price_rows: list[tuple[str, float]] = []
            for ticker, data in all_results.items():
                if ticker in FX_PAIRS or ticker in MARKET_TICKERS:
                    continue
                if ticker in metal_tickers_set:
                    # Spot-Preis pro Metall: gezielt die passende Edelmetall-Position updaten.
                    await db.execute(
                        text("UPDATE positions SET current_price = :price WHERE ticker = :spot AND gold_org = true AND is_active = true"),
                        {"price": data["price"], "spot": ticker},
                    )
                    continue
                # gold_org-Positionen werden oben via metal_tickers_set gesetzt.
                # Hier ausschliessen, damit z.B. GC=F (im yahoo-Batch wegen Gold)
                # nicht den CHF-Spotpreis in Gold-Positionen ueberschreibt.
                if ticker in position_match_tickers:
                    price_rows.append((ticker, data["price"]))
            await _update_position_prices_batch(db, price_rows)

            # H-4b: Currency mismatch detection (stocks only — ETFs often trade
            # in a different currency than their fund currency, e.g. USD-denominated
            # ETFs listed on LSE trade in GBP)
            from models.position import AssetType
            currency_mismatches = []
            for pos in tickers_info["positions"]:
                if pos.coingecko_id or pos.gold_org:
                    continue
                if pos.type in (AssetType.etf, AssetType.cash, AssetType.pension, AssetType.real_estate):
                    continue
                # Skip closed positions (shares = 0)
                if float(pos.shares or 0) <= 0:
                    continue
                yf_ticker = pos.yfinance_ticker or pos.ticker
                if yf_ticker in all_results:
                    yf_currency = all_results[yf_ticker].get("currency", "USD")
                    if yf_currency != pos.currency:
                        # Skip known LSE USD ETFs: .L tickers often report GBP
                        # but many Irish/Luxembourg ETFs trade in USD
                        if yf_ticker.endswith(".L") and pos.currency == "USD":
                            continue
                        currency_mismatches.append({
                            "ticker": pos.ticker,
                            "yf_ticker": yf_ticker,
                            "pos_currency": pos.currency,
                            "yf_currency": yf_currency,
                        })
                        logger.warning(
                            f"CURRENCY MISMATCH: {pos.ticker} position={pos.currency}, "
                            f"yfinance({yf_ticker})={yf_currency} — wrong ticker?"
                        )
            if currency_mismatches:
                cache.set("currency_mismatches", currency_mismatches)
            else:
                cache.set("currency_mismatches", [])

            # H-3: Clean up old cache entries (keep 400 days for 200-DMA calculation)
            cutoff = date.today() - timedelta(days=400)
            await db.execute(text("DELETE FROM price_cache WHERE date < :cutoff"), {"cutoff": cutoff})

            await db.commit()

            last_refresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            final_state = {
                "last_refresh": last_refresh,
                "started_at": None,
                "ticker_count": upserted,
                "status": "ok",
                "refreshing": False,
                "errors": errors,
            }
            await _save_refresh_state_to_db(final_state)

            logger.info(f"Cache refresh complete: {upserted} tickers updated, {len(errors)} errors")
            return {
                "status": "ok",
                "tickers_refreshed": upserted,
                "last_refresh": last_refresh,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Cache refresh failed: {e}")
            prev = await _load_refresh_state_from_db()
            await _save_refresh_state_to_db({
                "last_refresh": prev.get("last_refresh"), "started_at": None, "ticker_count": 0,
                "status": "error", "refreshing": False, "errors": [str(e)],
            })
            return {"status": "error", "error": str(e)}
    finally:
        with _refresh_lock:
            _local_refreshing = False


def get_cached_price_sync(ticker: str, fallback_days: int = 2) -> dict | None:
    """Synchronous DB lookup for use from ThreadPoolExecutor context."""
    today = date.today()
    start_date = today - timedelta(days=fallback_days)

    try:
        with SyncSessionLocal() as session:
            result = session.execute(
                select(PriceCache)
                .where(PriceCache.ticker == ticker, PriceCache.date >= start_date)
                .order_by(PriceCache.date.desc())
                .limit(1)
            )
            row = result.scalars().first()
            if row:
                return {
                    "price": round(float(row.close), 4),
                    "currency": row.currency,
                    "stale": row.date < today,
                    "date": row.date.isoformat(),
                }
    except Exception as e:
        logger.debug(f"DB cache lookup failed for {ticker}: {e}")

    return None


def get_cached_prices_batch_sync(tickers: list[str], fallback_days: int = 5) -> dict[str, dict]:
    """Batch sync lookup — single DB session for multiple tickers (M-5)."""
    today = date.today()
    start_date = today - timedelta(days=fallback_days)
    result_dict: dict[str, dict] = {}

    if not tickers:
        return result_dict

    try:
        with SyncSessionLocal() as session:
            rows = session.execute(
                select(PriceCache.ticker, PriceCache.close, PriceCache.currency, PriceCache.date)
                .where(PriceCache.ticker.in_(tickers), PriceCache.date >= start_date)
                .order_by(PriceCache.date.desc())
            ).all()
            # First hit per ticker is the most recent (due to ORDER BY date DESC)
            for ticker, close, currency, dt in rows:
                if ticker not in result_dict:
                    result_dict[ticker] = {
                        "price": round(float(close), 4),
                        "currency": currency,
                        "stale": dt < today,
                        "date": dt.isoformat(),
                    }
    except Exception as e:
        logger.debug(f"Batch DB cache lookup failed: {e}")

    return result_dict


def get_close_series_from_db(ticker: str, period: str = "1y") -> pd.Series | None:
    """Load close price series from price_cache DB as a pandas Series (sync)."""
    import pandas as pd

    days_map = {"1y": 365, "2y": 730, "6mo": 180, "3mo": 90}
    days = days_map.get(period, 365)
    start_date = date.today() - timedelta(days=days)

    try:
        with SyncSessionLocal() as session:
            result = session.execute(
                select(PriceCache.date, PriceCache.close)
                .where(PriceCache.ticker == ticker, PriceCache.date >= start_date)
                .order_by(PriceCache.date.asc())
            )
            rows = result.all()
            if not rows:
                return None
            dates = [r[0] for r in rows]
            closes = [float(r[1]) for r in rows]
            return pd.Series(closes, index=pd.DatetimeIndex(dates), name="Close")
    except Exception as e:
        logger.debug(f"DB close series failed for {ticker}: {e}")
        return None


async def seed_historical_prices(db: AsyncSession) -> None:
    """Seed historical price data for market tickers if DB has fewer than 210 days.
    This enables moving average calculations (50/100/150/200 DMA)."""
    import pandas as pd

    SEED_TICKERS = ["^GSPC", "^VIX"]

    for ticker in SEED_TICKERS:
        # Check how many rows we have (SQL COUNT instead of full load)
        from sqlalchemy import func as sqlfunc
        result = await db.execute(
            select(sqlfunc.count()).select_from(PriceCache).where(PriceCache.ticker == ticker)
        )
        count = result.scalar() or 0
        if count >= 210:
            continue

        logger.info(f"Seeding historical data for {ticker} ({count} rows in DB, need 210+)...")
        try:
            data = await asyncio.to_thread(
                lambda: yf_download(ticker, period="1y", progress=False)
            )
            if data.empty:
                logger.warning(f"Could not seed {ticker}: yfinance returned empty data")
                continue

            close = data["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            close = close.dropna()

            rows = []
            for dt, price in close.items():
                d = dt.date() if hasattr(dt, 'date') else dt
                rows.append({
                    "ticker": ticker,
                    "date": d,
                    "close": round(float(price), 4),
                    "currency": "USD",
                    "source": "yahoo",
                })
            seeded = len(rows)

            if rows:
                stmt = pg_insert(PriceCache).values(rows).on_conflict_do_nothing()
                await db.execute(stmt)

            await db.commit()
            logger.info(f"Seeded {seeded} historical prices for {ticker}")
        except Exception as e:
            logger.warning(f"Failed to seed historical data for {ticker}: {e}")
