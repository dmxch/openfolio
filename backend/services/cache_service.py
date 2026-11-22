import asyncio
import json
import logging
import math
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import pandas as pd
import yfinance as yf
from yf_patch import yf_download, yf_quote_currency
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.validation import is_market_ticker
from config import settings
from db import SyncSessionLocal, async_session
from models.app_config import AppConfig
from models.position import MANUAL_PRICE_SQL, AssetType, Position, has_manual_price
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

# --- Krypto-Kurse: eigener Namensraum ---
#
# Den Anzeige-Ticker einer Position wählt der Nutzer frei. CoinGecko-Kurse
# dürfen deshalb nie unter diesem Ticker in den geteilten Kurs-Namensraum
# (price_cache, price:<ticker>, positions.current_price per Ticker) gelangen:
# eine Position «AAPL» mit coingecko_id «bitcoin» überschrieb sonst den
# AAPL-Kurs aller Nutzer. Krypto-Kurse hängen an der coingecko_id. Der Doppelpunkt
# im Präfix ist in MARKET_TICKER_PATTERN nicht erlaubt, ein Yahoo-Symbol kann
# den Schlüssel also nicht treffen.
CRYPTO_PRICE_KEY_PREFIX = "CG:"
# price_cache.ticker ist kürzer als positions.ticker. Eine einzige zu lange
# Zeile liess den Sammel-UPSERT für alle Ticker scheitern. Die Grenze folgt dem
# Modell, damit sie mit einer Spaltenerweiterung mitwandert.
_PRICE_KEY_MAX_LEN = PriceCache.__table__.c.ticker.type.length
# Der Schlüssel «CG:<coingecko_id>» muss in price_cache.ticker passen. Eine
# längere ID bekäme vom Worker nie eine Zeile: DB-Rückgriff, Tagesänderung und
# Pending-Order-Kurs fehlten dann.
COINGECKO_ID_MAX_LEN = _PRICE_KEY_MAX_LEN - len(CRYPTO_PRICE_KEY_PREFIX)
COINGECKO_ID_PATTERN = rf"^[a-z0-9-]{{1,{COINGECKO_ID_MAX_LEN}}}$"
_COINGECKO_ID_RE = re.compile(COINGECKO_ID_PATTERN)


def is_coingecko_id(value: object) -> bool:
    """True, wenn value eine CoinGecko-ID nach COINGECKO_ID_PATTERN ist."""
    # fullmatch statt match: «$» akzeptiert in Python sonst ein Zeilenende am Schluss.
    return isinstance(value, str) and _COINGECKO_ID_RE.fullmatch(value) is not None


def crypto_price_key(coingecko_id: str) -> str:
    """Schlüssel eines CoinGecko-Kurses in price_cache («CG:<coingecko_id>»)."""
    return f"{CRYPTO_PRICE_KEY_PREFIX}{coingecko_id}"


def is_coingecko_priced(pos: Position) -> bool:
    """True, wenn die Position ihren Kurs von CoinGecko bezieht.

    Die coingecko_id zählt nur beim Typ crypto. Bei jedem anderen Typ ist sie
    ein Altbestand ohne Wirkung, die Position läuft dann über Yahoo.
    """
    return pos.type == AssetType.crypto and bool(pos.coingecko_id)


# Obergrenze von Numeric(14, 4): zehn Stellen vor dem Komma.
_PRICE_LIMIT = 1e10


def _price_decimals(key: str) -> int:
    """Nachkommastellen eines Kurses: 8 für FX-Paare und Krypto, sonst 4.

    JPYCHF=X liegt bei 0.0052. Vier Stellen lassen davon zwei signifikante
    übrig, der CHF-Wert einer JPY-Position sprang dadurch um rund 2 %.
    """
    return 8 if key.endswith("=X") or key.startswith(CRYPTO_PRICE_KEY_PREFIX) else 4


def _is_valid_price(price: object) -> bool:
    """True für einen endlichen Kurs unterhalb der Spaltengrenze."""
    try:
        value = float(price)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and abs(value) < _PRICE_LIMIT


def _drop_invalid_prices(results: dict, source: str) -> dict:
    """Entfernt Einträge mit ungültigem Kurs und warnt.

    NaN und Inf passieren Postgres als Numeric und stünden danach in
    positions.current_price; ein Kurs ab 1e10 bricht den UPSERT ab.
    """
    clean = {}
    for key, data in results.items():
        if isinstance(data, dict) and _is_valid_price(data.get("price")):
            clean[key] = data
        else:
            logger.warning("Skipping %s price for %s: not a finite price below 1e10", source, key)
    return clean


async def _upsert_price_rows(db: AsyncSession, rows: list[dict]) -> int:
    """UPSERT von price_cache-Zeilen. Liefert die Zahl der geschriebenen Zeilen.

    Zeilen, die das Statement für alle anderen scheitern liessen (Schlüssel
    länger als die Spalte, ungültiger Kurs), werden übersprungen und gemeldet.
    """
    valid = []
    for row in rows:
        if len(row["ticker"]) > _PRICE_KEY_MAX_LEN:
            logger.warning(
                "Skipping price_cache row for %s: key longer than %d characters",
                row["ticker"], _PRICE_KEY_MAX_LEN,
            )
        elif not _is_valid_price(row.get("close")):
            logger.warning("Skipping price_cache row for %s: not a finite price below 1e10", row["ticker"])
        else:
            valid.append(row)
    if not valid:
        return 0
    # Die Test-Suite läuft auf SQLite, das «ON CONFLICT ON CONSTRAINT» nicht kennt.
    if db.get_bind().dialect.name == "sqlite":
        stmt = sqlite_insert(PriceCache).values(valid)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "date"],
            set_={"close": stmt.excluded.close, "currency": stmt.excluded.currency, "source": stmt.excluded.source},
        )
    else:
        stmt = pg_insert(PriceCache).values(valid)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_ticker_date",
            set_={"close": stmt.excluded.close, "currency": stmt.excluded.currency, "source": stmt.excluded.source},
        )
    await db.execute(stmt)
    return len(valid)


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


def _divisor_and_currency(ticker: str) -> tuple[float, str] | None:
    """(Pence-Divisor, Währungs-Label) für einen Kurs, der in price_cache geht.

    None bei einem .L-Ticker, dessen Kurswährung gerade unbekannt ist (Yahoo-
    Fehler, Ticker-Lock länger als die Frist belegt). Ohne sie lässt sich ein
    Pence-Kurs nicht von einem Pfund-Kurs trennen: mit Divisor 1.0 stünde der
    Kurs 100-fach zu hoch im Cache, und der Backfill korrigiert eine geschriebene
    Zeile nie (on_conflict_do_nothing). Wer einen Kurs schreibt, überspringt
    den Ticker bei None.

    Eine einzige Abfrage für beide Werte: Divisor und Label können sich so
    nicht widersprechen. Blocking bei Cache-Miss — aus async nur via to_thread.
    """
    if not ticker.endswith(".L"):
        return 1.0, get_ticker_currency(ticker)
    cur = _quote_currency(ticker)
    if not cur:
        return None
    if cur == "GBp":
        return 100.0, "GBP"
    return 1.0, cur


def _pence_divisor(ticker: str) -> float:
    """1.0 oder 100.0 — Divisor für Pence-quotierte .L-Ticker (GBp/GBX).

    yfinance liefert viele LSE-Titel in Pence ("GBp"). Ohne Division wäre
    jede Live-Bewertung 100× zu hoch (Review 2026-06-10, H2 — die GBX-
    Erkennung existierte vorher nur im Snapshot-Regen-Pfad). Unbekannte
    Quote-Währung → 1.0 (kein Raten).
    """
    quote = _divisor_and_currency(ticker)
    return quote[0] if quote else 1.0


def _resolved_currency(ticker: str) -> str:
    """Währungs-Label für Cache-Zeilen: echte Quote-Währung wenn bekannt
    (GBp → GBP, da Preise nach _pence_divisor in Pfund liegen), sonst
    Suffix-Heuristik."""
    quote = _divisor_and_currency(ticker)
    return quote[1] if quote else get_ticker_currency(ticker)


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


# Ungültige Symbole nur einmal je Prozess melden, nicht bei jedem 60-s-Lauf.
_warned_invalid_symbols: set[str] = set()


def _valid_yahoo_symbols(symbols) -> list[str]:
    """Filtert Symbole, die nicht MARKET_TICKER_PATTERN entsprechen.

    yfinance trennt Zeichenketten an Komma und Leerzeichen: ein gespeicherter
    Ticker «AA,AB,AC» löste sonst drei Abrufe aus. Bestandsdaten aus der Zeit
    vor der Eingabeprüfung laufen deshalb hier durch denselben Filter.
    """
    valid = []
    for symbol in dict.fromkeys(symbols):
        if is_market_ticker(symbol):
            valid.append(symbol)
        elif symbol not in _warned_invalid_symbols:
            _warned_invalid_symbols.add(symbol)
            logger.warning("Skipping invalid yahoo symbol %r", symbol)
    return valid


async def collect_all_tickers(db: AsyncSession) -> dict:
    """Collect all tickers needed from positions, watchlist, sectors, FX, etc."""
    yahoo_tickers = set()
    crypto_ids: set[str] = set()

    # Active positions
    result = await db.execute(select(Position).where(Position.is_active == True))  # noqa: E712
    positions = result.scalars().all()
    for pos in positions:
        if pos.type in _NON_YAHOO_TYPES:
            continue
        if has_manual_price(pos):
            # Von Hand gepflegter Kurs (Modus und Preisquelle manual): weder
            # laden noch überschreiben. pricing_mode manual allein genügt nicht,
            # siehe has_manual_price.
            continue
        if pos.type == AssetType.crypto:
            # Krypto läuft nur über CoinGecko, geschlüsselt nach coingecko_id.
            if is_coingecko_id(pos.coingecko_id):
                crypto_ids.add(pos.coingecko_id)
            else:
                # Fehlende oder ungültige CoinGecko-ID: Datenfehler — überspringen,
                # statt einen Pseudo-Ticker an Yahoo zu senden.
                logger.warning(f"Skipping crypto position without valid coingecko_id: {pos.ticker} (id={pos.id})")
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
        "yahoo_tickers": sorted(_valid_yahoo_symbols(yahoo_tickers)),
        "fx_pairs": FX_PAIRS,
        # CoinGecko-IDs, dedupliziert. Der Anzeige-Ticker der Position spielt
        # für Krypto-Kurse keine Rolle.
        "crypto": sorted(crypto_ids),
        # Spot-Ticker aller aktiven Edelmetall-Positionen (Gold/Silber/Platin/Palladium).
        # Wird vom Worker genutzt um pro Metall den Live-CHF-Preis zu holen.
        "metal_spot_tickers": sorted({
            pos.ticker for pos in positions
            if pos.gold_org and not has_manual_price(pos)
        }),
        "positions": positions,
    }


def _download_yahoo_batch(tickers: list[str]) -> dict:
    """Download prices for all yahoo tickers in one batch. Runs in thread."""
    # Nur geprüfte Symbole und als Liste: yfinance zerlegt eine Zeichenkette an
    # Komma und Leerzeichen in beliebig viele Einzelabrufe.
    all_tickers = _valid_yahoo_symbols(tickers)
    if not all_tickers:
        return {}

    results = {}

    try:
        data = yf_download(all_tickers, period="5d", progress=False, group_by="ticker")
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
                    quote = _divisor_and_currency(ticker)
                    if quote is None:
                        logger.warning("Skipping price for %s: quote currency unknown", ticker)
                        continue
                    divisor, currency = quote
                    current = float(close.iloc[-1]) / divisor
                    prev = (float(close.iloc[-2]) / divisor) if len(close) > 1 else current
                    change_pct = ((current / prev) - 1) * 100 if prev else 0
                    results[ticker] = {
                        "price": round(current, _price_decimals(ticker)),
                        "currency": currency,
                        "change_pct": round(change_pct, 2),
                    }
            except (KeyError, IndexError) as e:
                logger.debug(f"Could not extract price data for {ticker}: {e}")
                continue
    except Exception as e:
        logger.error(f"Yahoo batch download failed: {e}")

    return results


# --- Yahoo-Abruf in Blöcken ---
#
# Ein einziger Download für alle Ticker wuchs linear mit der Nutzerzahl. Riss er
# die Frist, ging das ganze Ergebnis verloren, der Thread lief weiter und der
# nächste Lauf startete einen zweiten daneben. Deshalb: Blöcke, jeder sofort
# gespeichert, eine Gesamtfrist unter dem wait_for der Aufrufer und ein Lock,
# das einen zweiten Download-Thread verhindert.
_YAHOO_BLOCK_SIZE = 50
# Der Admin-Endpunkt wartet 60 s auf refresh_cache, der Worker 120 s.
YAHOO_BUDGET_DEFAULT_S = 45.0
YAHOO_BUDGET_WORKER_S = 90.0
_yahoo_download_lock = threading.Lock()
# Start-Block des nächsten Laufs. Reicht die Frist nicht für alle Blöcke,
# beginnt der nächste Lauf dort, wo dieser aufgehört hat. Ohne das bekämen
# die hinteren Blöcke nie einen Kurs.
_yahoo_block_cursor = 0


def _download_yahoo_block(tickers: list[str]) -> dict | None:
    """Lädt einen Block. None, wenn noch ein früherer Download-Thread läuft.

    asyncio.wait_for beendet nur das Warten, nicht den Thread. Das Lock gehört
    dem Thread, bis yfinance zurückkehrt.
    """
    if not _yahoo_download_lock.acquire(blocking=False):
        return None
    try:
        return _download_yahoo_batch(tickers)
    finally:
        _yahoo_download_lock.release()


def _plan_yahoo_blocks(tickers: list[str]) -> tuple[list[list[str]], int]:
    """Teilt die Ticker in Blöcke. Liefert (Blöcke, Zahl der rotierenden Blöcke).

    FX-Paare und Markt-Indizes stehen immer im ersten Block: ohne FX-Kurs lässt
    sich keine Fremdwährungsposition bewerten. Die übrigen Blöcke rotieren.
    """
    wanted = set(tickers)
    priority = [t for t in dict.fromkeys(FX_PAIRS + MARKET_TICKERS) if t in wanted]
    rest = sorted(wanted.difference(priority))
    rest_blocks = [rest[i:i + _YAHOO_BLOCK_SIZE] for i in range(0, len(rest), _YAHOO_BLOCK_SIZE)]
    if rest_blocks:
        start = _yahoo_block_cursor % len(rest_blocks)
        rest_blocks = rest_blocks[start:] + rest_blocks[:start]
    return ([priority] if priority else []) + rest_blocks, len(rest_blocks)


async def _store_yahoo_block(
    db: AsyncSession, block_results: dict, today: date, position_tickers: set[str]
) -> int:
    """Schreibt die Kurse eines Blocks in App-Cache, price_cache und Positionen."""
    rows = []
    price_rows: list[tuple[str, float]] = []
    for ticker, data in block_results.items():
        if ticker == "^VIX":
            vix_val = data["price"]
            prev_close = vix_val / (1 + data["change_pct"] / 100) if data["change_pct"] else vix_val
            cache.set("vix", {
                "value": round(vix_val, 2),
                "change": round(vix_val - prev_close, 2),
                "level": "low" if vix_val < 15 else "normal" if vix_val < 20 else "elevated" if vix_val < 30 else "high",
            })
        elif ticker not in FX_PAIRS:  # FX-Paare landen gesammelt in fx_rates
            cache.set(f"price:{ticker}", {
                "price": data["price"],
                "currency": data.get("currency", "USD"),
                "change_pct": data["change_pct"],
            })
        rows.append({
            "ticker": ticker,
            "date": today,
            "close": data["price"],
            "currency": data.get("currency", "USD"),
            "source": "yahoo",
        })
        if ticker in FX_PAIRS or ticker in MARKET_TICKERS:
            continue
        # Nur Ticker mit Positions-Match: Watchlist-Ticker brauchen kein UPDATE.
        if ticker in position_tickers:
            price_rows.append((ticker, data["price"]))
    upserted = await _upsert_price_rows(db, rows)
    await _update_position_prices_batch(db, price_rows)
    await db.commit()
    return upserted


async def _refresh_yahoo_blocks(
    db: AsyncSession, tickers: list[str], budget: float, today: date, position_tickers: set[str]
) -> tuple[dict, int, str | None]:
    """Lädt die Yahoo-Ticker blockweise und speichert jeden Block sofort.

    Liefert (Kurse, Zahl der price_cache-Zeilen, Fehlerklasse oder None). Ein
    Fehler bricht nur die restlichen Blöcke ab, gespeicherte Blöcke bleiben.
    """
    global _yahoo_block_cursor
    blocks, rotating = _plan_yahoo_blocks(tickers)
    results: dict = {}
    upserted = 0
    error: str | None = None
    done = 0
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget

    for block in blocks:
        remaining = deadline - loop.time()
        if remaining <= 0:
            error = "BudgetExhausted"
            logger.error("Yahoo refresh: time budget of %.0fs used up after %d/%d blocks", budget, done, len(blocks))
            break
        try:
            block_results = await asyncio.wait_for(
                asyncio.to_thread(_download_yahoo_block, block), timeout=remaining
            )
        except asyncio.TimeoutError:
            error = "TimeoutError"
            logger.error("Yahoo refresh: block %d/%d timed out", done + 1, len(blocks))
            break
        if block_results is None:
            error = "DownloadStillRunning"
            logger.error("Yahoo refresh skipped: an earlier download thread is still running")
            break
        done += 1
        block_results = _drop_invalid_prices(block_results, "yahoo")
        if block_results:
            upserted += await _store_yahoo_block(db, block_results, today, position_tickers)
            results.update(block_results)

    if rotating:
        has_priority = len(blocks) > rotating
        rotated_done = max(0, done - 1) if has_priority else done
        _yahoo_block_cursor = (_yahoo_block_cursor + rotated_done) % rotating
    if error is None and tickers and not results:
        # Yahoo antwortet bei einer IP-Sperre mit leeren Daten statt mit einem Fehler.
        error = "NoData"
        logger.error("Yahoo refresh: no prices for %d tickers", len(tickers))
    return results, upserted, error


# CoinGecko nimmt die IDs in der URL entgegen; ein Block hält sie kurz.
_COINGECKO_IDS_PER_REQUEST = 100


async def _fetch_crypto_batch(coingecko_ids: list[str]) -> dict:
    """Fetch crypto prices from CoinGecko. Ergebnis geschlüsselt nach coingecko_id."""
    ids = sorted({cg_id for cg_id in coingecko_ids if is_coingecko_id(cg_id)})
    if not ids:
        return {}

    from services.api_utils import fetch_json_coingecko
    url = f"{settings.coingecko_base_url}/simple/price"
    results = {}

    for start in range(0, len(ids), _COINGECKO_IDS_PER_REQUEST):
        chunk = ids[start:start + _COINGECKO_IDS_PER_REQUEST]
        try:
            params = {"ids": ",".join(chunk), "vs_currencies": "chf", "include_24hr_change": "true"}
            data = await fetch_json_coingecko(url, params=params)
        except Exception as e:
            logger.error(f"CoinGecko batch fetch failed: {e}")
            continue
        if not isinstance(data, dict):
            logger.error("CoinGecko batch fetch returned no object")
            continue
        for cg_id in chunk:
            # Jeder Coin einzeln: ein fehlendes «chf» oder ein null bei der
            # Tagesänderung verwarf sonst alle folgenden Coins.
            try:
                coin = data.get(cg_id)
                if not coin:
                    continue
                price = float(coin["chf"])
                change = coin.get("chf_24h_change")
                results[cg_id] = {
                    "price": price,
                    "currency": "CHF",
                    "change_pct": round(float(change), 2) if change is not None else 0,
                    "source": "coingecko",
                }
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Could not parse CoinGecko price for {cg_id}: {e!r}")

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
    if has_manual_price(pos):
        return False  # von Hand gepflegter Kurs bleibt unangetastet
    try:
        is_crypto = pos.type == AssetType.crypto
        if is_crypto:
            if not is_coingecko_id(pos.coingecko_id):
                return False  # Crypto ohne gültige coingecko_id — kein Provider
            results = await _fetch_crypto_batch([pos.coingecko_id])
            data = results.get(pos.coingecko_id)
            # Nie der Anzeige-Ticker: price_cache teilen sich alle Nutzer.
            key = crypto_price_key(pos.coingecko_id)
        else:
            key = pos.yfinance_ticker or pos.ticker
            if not is_market_ticker(key):
                return False
            results = await asyncio.to_thread(_download_yahoo_batch, [key])
            data = results.get(key)

        if not data or not _is_valid_price(data.get("price")):
            return False

        await _upsert_price_rows(db, [{
            "ticker": key,
            "date": date.today(),
            "close": data["price"],
            "currency": data.get("currency", "USD"),
            "source": data.get("source", "yahoo"),
        }])
        pos.current_price = data["price"]
        await db.commit()

        if is_crypto:
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
            if pos.type not in _NON_YAHOO_TYPES and not pos.gold_org and pos.type != AssetType.crypto:
                await backfill_price_history(db, pos.yfinance_ticker or pos.ticker)
    except Exception:
        logger.warning(f"Background price seed failed for position {position_id}", exc_info=True)


# Sammel-Seed nach einem Import. Grenzen gegen Dauerfeuer auf den Kursanbieter
# (Audit 22.11.2026): hoechstens ein Block je Lauf, Pausen zwischen den Einzelabrufen,
# ein Lauf zur selben Zeit je Prozess und kein zweiter Lauf fuer denselben Nutzer.
IMPORT_SEED_MAX_TICKERS = _YAHOO_BLOCK_SIZE
IMPORT_SEED_WINDOW = timedelta(minutes=30)
IMPORT_SEED_PAUSE_S = 0.5
_IMPORT_SEED_LOCK_TRIES = 3
_IMPORT_SEED_LOCK_WAIT_S = 5.0
# Gesamtfrist je Lauf. Ein haengender Abruf hielte sonst den Einzellaeufer und den
# Merker des Nutzers bis zum Neustart fest, und kein Import bekaeme mehr Kurse.
IMPORT_SEED_BUDGET_S = 600.0


async def seed_missing_prices_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    pause_s: float = IMPORT_SEED_PAUSE_S,
    after_prices: Callable[[], None] | None = None,
) -> dict[str, int]:
    """Sofort-Fetch fuer die frisch angelegten Positionen eines Nutzers ohne Kurs.

    Der Import legt viele Positionen auf einmal an. Ausserhalb des Abruf-Fensters
    (abends, Wochenende) blieben sie bis zum naechsten Morgen ohne Kurs, ohne Namen
    und ohne Historie.

    - Nur Positionen aus den letzten ``IMPORT_SEED_WINDOW``: Ein dauerhaft kursloser
      Ticker (delistet, falsches Symbol) wird nicht bei jedem Import neu abgefragt.
    - Hoechstens ``IMPORT_SEED_MAX_TICKERS`` Ticker, gehaltene zuerst. Den Rest holt
      der regulaere Abruf des Workers.
    - Kurse ueber ``_download_yahoo_block``: derselbe Block-Pfad und dieselbe Sperre
      wie der Abruf im selben Prozess. Die Sperre gilt je Prozess: Der Worker und ein
      zweiter API-Prozess koennen gleichzeitig je einen Block laden. Ist die Sperre
      nach mehreren Versuchen besetzt, endet der Lauf ohne Namen und Historie.
    - Namen und Historie nacheinander mit Pause.
    - Nach dem Laden nur noch einfache Werte und gezielte UPDATEs: ``backfill_price_history``
      kann die Session zurueckrollen, ORM-Objekte waeren danach nicht mehr lesbar.

    ``after_prices`` laeuft direkt nach dem Speichern der Kurse (Cache des Nutzers
    leeren), nicht erst nach Namen und Historie. Wirft nie; liefert Zaehler.
    """
    counts = {"positions": 0, "priced": 0, "named": 0, "history": 0, "skipped": 0}
    try:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - IMPORT_SEED_WINDOW
        result = await db.execute(
            select(Position).where(
                Position.user_id == user_id,
                Position.is_active.is_(True),
                Position.current_price.is_(None),
                Position.created_at >= cutoff,
            )
        )
        # key -> Liste einfacher Werte je Position: (id, name, ticker, gehalten)
        yahoo: dict[str, list[tuple[uuid.UUID, str, str, bool]]] = {}
        crypto: dict[str, list[uuid.UUID]] = {}
        for pos in result.scalars().all():
            if pos.type in _NON_YAHOO_TYPES or pos.gold_org or has_manual_price(pos):
                continue
            if pos.type == AssetType.crypto:
                if is_coingecko_id(pos.coingecko_id):
                    crypto.setdefault(pos.coingecko_id, []).append(pos.id)
                continue
            key = pos.yfinance_ticker or pos.ticker
            if is_market_ticker(key):
                yahoo.setdefault(key, []).append((pos.id, pos.name or "", pos.ticker, (pos.shares or 0) > 0))

        # Gehaltene zuerst, dann alphabetisch; ueber der Grenze bleibt der Rest dem Worker.
        ordered = sorted(yahoo, key=lambda k: (not any(held for *_, held in yahoo[k]), k))
        keys = ordered[:IMPORT_SEED_MAX_TICKERS]
        counts["skipped"] = sum(len(yahoo[k]) for k in ordered[IMPORT_SEED_MAX_TICKERS:])
        counts["positions"] = sum(len(yahoo[k]) for k in keys) + sum(len(v) for v in crypto.values())
        if not counts["positions"]:
            return counts

        rows: list[dict] = []
        cached: list[tuple[str, dict]] = []
        if keys:
            data = None
            for attempt in range(_IMPORT_SEED_LOCK_TRIES):
                data = await asyncio.to_thread(_download_yahoo_block, keys)
                if data is not None:
                    break
                if attempt + 1 < _IMPORT_SEED_LOCK_TRIES:
                    await asyncio.sleep(_IMPORT_SEED_LOCK_WAIT_S if pause_s else 0)
            if data is None:
                # Im selben Prozess laeuft schon ein Download. Dann auch keine
                # Einzelabrufe fuer Namen und Historie: Den Rest holt der regulaere Abruf.
                logger.info("Price seed after import skipped for user %s: download busy", user_id)
                counts["skipped"] += counts["positions"]
                counts["positions"] = 0
                return counts
            for key in keys:
                quote = (data or {}).get(key)
                if not quote or not _is_valid_price(quote.get("price")):
                    continue
                ids = [pid for pid, *_ in yahoo[key]]
                rows.append({"ticker": key, "date": date.today(), "close": quote["price"],
                             "currency": quote.get("currency", "USD"), "source": quote.get("source", "yahoo")})
                await db.execute(
                    update(Position)
                    .where(Position.id.in_(ids), Position.current_price.is_(None))
                    .values(current_price=quote["price"])
                )
                cached.append((f"price:{key}", {"price": quote["price"], "currency": quote.get("currency", "USD"),
                                               "change_pct": quote.get("change_pct", 0)}))
                counts["priced"] += len(ids)
        if crypto:
            data = await _fetch_crypto_batch(list(crypto))
            for cg_id, ids in crypto.items():
                quote = data.get(cg_id)
                if not quote or not _is_valid_price(quote.get("price")):
                    continue
                # Nie der Anzeige-Ticker: price_cache teilen sich alle Nutzer.
                rows.append({"ticker": crypto_price_key(cg_id), "date": date.today(), "close": quote["price"],
                             "currency": quote.get("currency", "USD"), "source": quote.get("source", "yahoo")})
                await db.execute(
                    update(Position)
                    .where(Position.id.in_(ids), Position.current_price.is_(None))
                    .values(current_price=quote["price"])
                )
                cached.append((f"crypto:{cg_id}", {"price": quote["price"], "currency": quote.get("currency", "CHF"),
                                                  "change_pct": quote.get("change_pct", 0)}))
                counts["priced"] += len(ids)
        if rows:
            await _upsert_price_rows(db, rows)
        await db.commit()
        for cache_key, value in cached:
            cache.set(cache_key, value)
        if after_prices is not None and counts["priced"]:
            after_prices()

        # Namen: Der Import kennt oft nur den Ticker. Das UPDATE greift nur, solange der
        # Name noch dem Ticker gleicht; ein inzwischen von Hand gesetzter Name bleibt.
        from services.ticker_info_service import get_ticker_info_cached
        for key in keys:
            unnamed = [(pid, name) for pid, name, ticker, _ in yahoo[key] if not name or name in (ticker, key)]
            if not unnamed:
                continue
            await asyncio.sleep(pause_s)
            try:
                info = await get_ticker_info_cached(key)
            except Exception:
                continue
            new_name = (info.get("shortName") or info.get("longName") or "").strip()[:200]
            if not new_name:
                continue
            for pid, old_name in unnamed:
                done = await db.execute(
                    update(Position).where(Position.id == pid, Position.name == old_name).values(name=new_name)
                )
                counts["named"] += done.rowcount or 0
            await db.commit()

        # Historie fuer MA-/MRS-Analysen, nur fuer gehaltene Titel.
        held_keys = [key for key in keys if any(held for *_, held in yahoo[key])]
        for key in held_keys:
            await asyncio.sleep(pause_s)
            counts["history"] += 1 if await backfill_price_history(db, key) else 0

        logger.info("Seeded prices after import for user %s: %s", user_id, counts)
    except Exception:
        logger.warning("Price seed after import failed for user %s", user_id, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
    return counts


_seed_tasks: set[asyncio.Task] = set()
_seed_running_users: set[uuid.UUID] = set()
_seed_rerun_users: set[uuid.UUID] = set()
_seed_run_lock: asyncio.Lock | None = None


def trigger_import_price_seed(user_id: uuid.UUID) -> None:
    """Fire-and-forget: Kurse, Namen und Historie fuer die Positionen eines Imports.

    Eigene DB-Session, blockiert die Antwort des Imports nicht. Laeuft fuer den Nutzer
    schon ein Lauf, startet kein zweiter; der laufende wiederholt sich danach einmal,
    damit die Positionen des zweiten Imports nicht leer ausgehen.
    """
    if user_id in _seed_running_users:
        _seed_rerun_users.add(user_id)
        return
    _seed_running_users.add(user_id)
    task = asyncio.create_task(_seed_user_safe(user_id))
    _seed_tasks.add(task)
    task.add_done_callback(_seed_tasks.discard)


async def _seed_user_safe(user_id: uuid.UUID) -> None:
    global _seed_run_lock
    if _seed_run_lock is None:
        _seed_run_lock = asyncio.Lock()

    def _invalidate() -> None:
        from api.portfolio import invalidate_portfolio_cache
        invalidate_portfolio_cache(str(user_id))

    try:
        while True:
            _seed_rerun_users.discard(user_id)
            # Ein Lauf zur selben Zeit je Prozess: Mehrere Importe stapeln sich hier
            # und treffen den Kursanbieter nacheinander.
            async with _seed_run_lock:
                async with async_session() as db:
                    try:
                        counts = await asyncio.wait_for(
                            seed_missing_prices_for_user(db, user_id, after_prices=_invalidate),
                            timeout=IMPORT_SEED_BUDGET_S,
                        )
                    except asyncio.TimeoutError:
                        # wait_for beendet nur das Warten, nicht den Thread des Abrufs: Dessen
                        # Sperre bleibt, bis er zurueckkehrt; spaetere Laeufe enden dann sofort.
                        logger.warning("Price seed after import timed out for user %s", user_id)
                        counts = {}
            if counts.get("named"):
                _invalidate()
            if user_id not in _seed_rerun_users:
                break
    except Exception:
        logger.warning("Background price seed after import failed for user %s", user_id, exc_info=True)
    finally:
        _seed_running_users.discard(user_id)
        _seed_rerun_users.discard(user_id)


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

    if not is_market_ticker(ticker):
        return 0  # kein Yahoo-Symbol (Freitext, Komma, Leerzeichen)
    try:
        data = await asyncio.to_thread(lambda: yf_download([ticker], period=period, progress=False))
        if data.empty:
            logger.warning(f"Price history backfill: yfinance returned empty for {ticker}")
            return 0
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()
        if close.empty:
            return 0

        quote = await asyncio.to_thread(_divisor_and_currency, ticker)
        if quote is None:
            logger.warning("Price history backfill skipped for %s: quote currency unknown", ticker)
            return 0
        divisor, currency = quote
        rows = [
            {
                "ticker": ticker,
                "date": (dt.date() if hasattr(dt, "date") else dt),
                "close": round(float(price) / divisor, _price_decimals(ticker)),
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
    Universum-Ticker inkl. Watchlist). Jede Position matcht nur ueber ihren
    wirksamen Ticker — yfinance_ticker, sonst ticker (vgl. collect_all_tickers).
    Frueher griff bei fehlendem yfinance_ticker-Kurs der Anzeige-Ticker: hielt
    Nutzer A «CFR» mit yfinance_ticker «CFR.SW» und stand bei Nutzer B «CFR»
    (Cullen/Frost) auf der Watchlist, bekam A bei einem Ausfall von CFR.SW den
    USD-Kurs von B. CASE-Variante statt UPDATE .. FROM (VALUES ..), damit das
    Statement auch auf SQLite (Test-Suite) laeuft.

    Ausgenommen sind: gold_org (Edelmetall-Spotpreise werden separat gesetzt),
    manuell gepflegte Kurse, Typen ohne Yahoo-Kurs und Krypto mit coingecko_id
    (Kurs kommt ueber _update_crypto_position_prices).
    """
    if not price_rows:
        return
    effective = "COALESCE(NULLIF(yfinance_ticker, ''), ticker)"
    # SQLAlchemy speichert Enum-Spalten mit dem Namen des Members.
    non_yahoo = ", ".join(f"'{name}'" for name in sorted(t.name for t in _NON_YAHOO_TYPES))
    for start in range(0, len(price_rows), _PRICE_UPDATE_CHUNK):
        chunk = price_rows[start:start + _PRICE_UPDATE_CHUNK]
        params: dict[str, object] = {}
        whens: list[str] = []
        ticker_binds: list[str] = []
        for i, (ticker, price) in enumerate(chunk):
            params[f"t{i}"] = ticker
            params[f"p{i}"] = price
            whens.append(f"WHEN {effective} = :t{i} THEN CAST(:p{i} AS NUMERIC)")
            ticker_binds.append(f":t{i}")
        in_list = ", ".join(ticker_binds)
        stmt = text(
            f"UPDATE positions SET current_price = CASE {' '.join(whens)} END "
            # Die erste Bedingung folgt aus der zweiten; sie haelt die Indizes
            # idx_positions_ticker und idx_positions_yf_ticker nutzbar.
            f"WHERE (ticker IN ({in_list}) OR yfinance_ticker IN ({in_list})) "
            f"AND {effective} IN ({in_list}) "
            "AND gold_org = false AND is_active = true "
            f"AND NOT {MANUAL_PRICE_SQL} "
            f"AND type NOT IN ({non_yahoo}) "
            "AND NOT (type = 'crypto' AND coingecko_id IS NOT NULL AND coingecko_id <> '')"
        )
        await db.execute(stmt, params)


async def _update_crypto_position_prices(
    db: AsyncSession, price_rows: list[tuple[str, float]]
) -> None:
    """Setzt positions.current_price fuer Krypto-Positionen ueber die coingecko_id.

    Der Anzeige-Ticker bleibt aussen vor: er ist frei waehlbar und darf keinen
    Kurs auf Positionen anderer Nutzer ziehen.
    """
    if not price_rows:
        return
    for start in range(0, len(price_rows), _PRICE_UPDATE_CHUNK):
        chunk = price_rows[start:start + _PRICE_UPDATE_CHUNK]
        params: dict[str, object] = {}
        whens: list[str] = []
        id_binds: list[str] = []
        for i, (coingecko_id, price) in enumerate(chunk):
            params[f"c{i}"] = coingecko_id
            params[f"p{i}"] = price
            whens.append(f"WHEN coingecko_id = :c{i} THEN CAST(:p{i} AS NUMERIC)")
            id_binds.append(f":c{i}")
        stmt = text(
            f"UPDATE positions SET current_price = CASE {' '.join(whens)} END "
            f"WHERE coingecko_id IN ({', '.join(id_binds)}) AND type = 'crypto' "
            f"AND is_active = true AND NOT {MANUAL_PRICE_SQL}"
        )
        await db.execute(stmt, params)


_SARON_MAX_AGE = timedelta(hours=6)


async def _saron_due(db: AsyncSession) -> bool:
    """True, wenn der gespeicherte SARON-Satz fehlt oder aelter als 6 Stunden ist.

    Der Satz aendert sich hoechstens einmal am Tag; der Refresh laeuft jede Minute.
    """
    try:
        updated_at = (
            await db.execute(select(AppConfig.updated_at).where(AppConfig.key == "saron_rate"))
        ).scalar()
    except Exception as e:
        logger.debug(f"Could not read SARON age: {e}")
        return True
    if updated_at is None:
        return True
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated_at > _SARON_MAX_AGE


def _provider_error(label: str, exc: BaseException) -> str:
    """Fehlertext fuer den Refresh-Status: Quelle und Fehlerklasse, keine Details.

    Den Status liest jeder angemeldete Nutzer. str() einer Datenbank-Exception
    enthaelt das Statement samt Tickern und Kursen fremder Nutzer.
    """
    return f"{label}: Abruf fehlgeschlagen ({type(exc).__name__})"


async def refresh_cache(
    db: AsyncSession, silent: bool = False, yahoo_budget: float = YAHOO_BUDGET_DEFAULT_S
) -> dict:
    """Main refresh: batch-download all prices and populate DB + in-memory cache.

    Args:
        silent: If True, don't update the refreshing state in DB (used by Worker
                to avoid the CacheStatus spinner triggering on every 60s cycle).
        yahoo_budget: Gesamtfrist fuer den Yahoo-Teil in Sekunden. Muss unter dem
                wait_for des Aufrufers liegen, sonst verwirft dieser den Lauf.
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

        try:
            tickers_info = await collect_all_tickers(db)
            positions = tickers_info["positions"]
            all_yahoo = tickers_info["yahoo_tickers"] + tickers_info["fx_pairs"]
            crypto_ids = tickers_info["crypto"]

            logger.info(f"Refreshing {len(all_yahoo)} yahoo tickers, {len(crypto_ids)} crypto...")

            # H-4: positions.current_price aus den Yahoo-Kursen. Nur Ticker mit
            # Positions-Match einbeziehen — Watchlist-only-Ticker erzeugen keinen
            # Roundtrip. Massgeblich ist der wirksame Ticker der Position.
            position_match_tickers: set[str] = set()
            for pos in positions:
                if pos.gold_org or pos.type in _NON_YAHOO_TYPES:
                    continue  # Edelmetall: Spotpreis-Pfad unten
                if has_manual_price(pos) or is_coingecko_priced(pos):
                    continue
                position_match_tickers.add(pos.yfinance_ticker or pos.ticker)

            today = date.today()

            # Run all fetches in parallel with individual timeouts. Nur der
            # Yahoo-Zweig benutzt die Session; er speichert jeden Block sofort.
            from services.property_service import fetch_saron_rate
            async def _noop(): return {}
            yahoo_task = _refresh_yahoo_blocks(db, all_yahoo, yahoo_budget, today, position_match_tickers)
            crypto_task = _run_with_timeout(_fetch_crypto_batch(crypto_ids), 10, "CoinGecko")
            metal_spot_tickers = tickers_info["metal_spot_tickers"]
            metals_task = (
                _run_with_timeout(asyncio.to_thread(_fetch_metals, metal_spot_tickers), 15, "Metals")
                if metal_spot_tickers else _noop()
            )
            saron_task = (
                _run_with_timeout(fetch_saron_rate(), 10, "SARON")
                if await _saron_due(db) else _noop()
            )

            yahoo_part, crypto_results, metal_results, saron_result = await asyncio.gather(
                yahoo_task, crypto_task, metals_task, saron_task, return_exceptions=True
            )

            if isinstance(yahoo_part, BaseException):
                # Download-Fehler faengt der Yahoo-Zweig selbst ab. Was hier
                # ankommt, ist ein Datenbankfehler: Lauf abbrechen.
                raise yahoo_part
            yahoo_results, upserted, yahoo_error = yahoo_part
            if yahoo_error:
                errors.append(f"Yahoo: Abruf unvollständig ({yahoo_error})")
            if isinstance(crypto_results, Exception):
                logger.error(f"Crypto batch failed: {crypto_results}")
                errors.append(_provider_error("Crypto", crypto_results))
                crypto_results = {}
            if isinstance(metal_results, Exception):
                logger.error(f"Metal fetch failed: {metal_results}")
                errors.append(_provider_error("Metals", metal_results))
                metal_results = {}
            if isinstance(saron_result, Exception):
                logger.error(f"SARON fetch failed: {saron_result}")
                errors.append(_provider_error("SARON", saron_result))
            elif saron_result:
                logger.info(f"SARON updated: {saron_result['rate']}% ({saron_result['date']})")

            crypto_results = _drop_invalid_prices(crypto_results, "coingecko")
            metal_results = _drop_invalid_prices(metal_results, "metal")

            # Krypto und Edelmetall: eigene Cache-Schluessel, eigene Zeilen in
            # price_cache und gezielte UPDATEs. Sie mischen sich nie mit den
            # Yahoo-Kursen: CoinGecko-Kurse haengen an der coingecko_id, nicht
            # am Anzeige-Ticker der Position.
            extra_rows = []
            crypto_prices: list[tuple[str, float]] = []
            for cg_id, data in crypto_results.items():
                cache.set(f"crypto:{cg_id}", {
                    "price": data["price"],
                    "currency": "CHF",
                    "change_pct": data["change_pct"],
                })
                extra_rows.append({
                    "ticker": crypto_price_key(cg_id),
                    "date": today,
                    "close": data["price"],
                    "currency": "CHF",
                    "source": "coingecko",
                })
                crypto_prices.append((cg_id, data["price"]))
            for ticker, data in metal_results.items():
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
                extra_rows.append({
                    "ticker": ticker,
                    "date": today,
                    "close": data["price"],
                    "currency": data.get("currency", "USD"),
                    "source": data.get("source", "yahoo"),
                })
                # Spot-Preis pro Metall: gezielt die passende Edelmetall-Position updaten.
                await db.execute(
                    text(
                        "UPDATE positions SET current_price = :price WHERE ticker = :spot "
                        f"AND gold_org = true AND is_active = true AND NOT {MANUAL_PRICE_SQL}"
                    ),
                    {"price": data["price"], "spot": ticker},
                )
            upserted += await _upsert_price_rows(db, extra_rows)
            await _update_crypto_position_prices(db, crypto_prices)

            # Build FX rates dict from yahoo results and cache it
            fx_rates = {"CHF": 1.0}
            fx_map = {"USDCHF=X": "USD", "EURCHF=X": "EUR", "CADCHF=X": "CAD", "GBPCHF=X": "GBP", "JPYCHF=X": "JPY"}
            for fx_ticker, ccy in fx_map.items():
                if fx_ticker in yahoo_results:
                    fx_rates[ccy] = yahoo_results[fx_ticker]["price"]
            if len(fx_rates) > 1:
                cache.set("fx_rates", fx_rates)

            # H-4b: Currency mismatch detection (stocks only — ETFs and bond ETFs
            # often trade in a different currency than their fund currency, e.g.
            # USD-denominated ETFs listed on LSE trade in GBP)
            currency_mismatches = []
            for pos in positions:
                if is_coingecko_priced(pos) or pos.gold_org:
                    continue
                if pos.type in (AssetType.etf, AssetType.bond, AssetType.cash, AssetType.pension, AssetType.real_estate):
                    continue
                # Skip closed positions (shares = 0)
                if float(pos.shares or 0) <= 0:
                    continue
                yf_ticker = pos.yfinance_ticker or pos.ticker
                if yf_ticker in yahoo_results:
                    yf_currency = yahoo_results[yf_ticker].get("currency", "USD")
                    if yf_currency != pos.currency:
                        # Skip known LSE USD ETFs: .L tickers often report GBP
                        # but many Irish/Luxembourg ETFs trade in USD
                        if yf_ticker.endswith(".L") and pos.currency == "USD":
                            continue
                        currency_mismatches.append({
                            "user_id": str(pos.user_id),
                            "ticker": pos.ticker,
                            "yf_ticker": yf_ticker,
                            "pos_currency": pos.currency,
                            "yf_currency": yf_currency,
                        })
                        logger.warning(
                            f"CURRENCY MISMATCH: {pos.ticker} position={pos.currency}, "
                            f"yfinance({yf_ticker})={yf_currency} — wrong ticker?"
                        )
            # Nach einem unvollstaendigen Yahoo-Lauf fehlen Ticker; die Liste
            # bliebe dann zu kurz und Warnungen verschwaenden bis zum naechsten Lauf.
            if not yahoo_error:
                cache.set("currency_mismatches", currency_mismatches)

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
                # Fehlerklasse des Yahoo-Teils oder None. Der Worker meldet sie
                # an die Job-Health: «ok» heisst hier nur, dass der Lauf endete.
                "yahoo_error": yahoo_error,
            }

        except Exception as e:
            # Details nur ins Log. Der Status ist fuer jeden angemeldeten Nutzer lesbar.
            logger.error(f"Cache refresh failed: {e}", exc_info=True)
            message = f"Refresh fehlgeschlagen ({type(e).__name__})"
            prev = await _load_refresh_state_from_db()
            await _save_refresh_state_to_db({
                "last_refresh": prev.get("last_refresh"), "started_at": None, "ticker_count": 0,
                "status": "error", "refreshing": False, "errors": [message],
            })
            return {"status": "error", "error": message}
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
                    "price": round(float(row.close), _price_decimals(ticker)),
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
                        "price": round(float(close), _price_decimals(ticker)),
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
                lambda: yf_download([ticker], period="1y", progress=False)
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
