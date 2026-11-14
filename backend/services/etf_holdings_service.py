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
import math
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dateutils import utcnow
from constants.etf_holdings_sources import ISHARES_HOLDINGS_URLS
from models.etf_holding import EtfHolding
from models.position import Position
from services import cache
from services.analysis_config import CORE_OVERLAP_HOLDINGS_TTL_DAYS
from services.api_utils import fetch_json
from services.etf_adapters import EtfRef, get_adapter
from services.etf_adapters._resolve import resolve_isins
from services.etf_holdings_ishares import fetch_ishares_holdings

logger = logging.getLogger(__name__)


_FMP_BASE = "https://financialmodelingprep.com/stable"

# Assetklassen, die eine Holdings-Durchsicht tragen: börsengehandelte ETFs UND
# Bond-ETFs/-Fonds. Der Selektor bleibt bewusst der Typ und wird NICHT auf is_etf
# umgestellt — der Import setzt is_etf nie, das würde den Look-Through aller
# importierten ETFs still abschalten.
LOOKTHROUGH_POSITION_TYPES: tuple[str, ...] = ("etf", "bond")

# ISIN->Ticker-Anreicherung (OpenFIGI) fuer Adapter, die nur eine ISIN liefern:
# NUR die groessten Holdings aufloesen (Overlap + Sektor-Fallback interessieren
# nur relevante Positionen), damit die keyless-OpenFIGI-Rate (25 req/60s) nicht
# gesprengt wird. Der lange Schwanz bleibt auf dem ISIN-Key (Land/Sektor sind bei
# diesen Anbietern ohnehin meist Issuer-nativ und unabhaengig von der Aufloesung).
_ENRICH_MAX_HOLDINGS = 50
_ENRICH_MIN_WEIGHT_PCT = 0.5

# Guard fuer das Loeschen weggefallener Holdings: nur wenn der neue Fetch
# plausibel vollstaendig ist (Mindestanzahl Rows UND nicht drastisch kleiner
# als der Bestand), darf DELETE laufen — ein kaputter/teilweiser Fetch darf
# die Tabelle nicht leeren.
_STALE_DELETE_MIN_ROWS = 10
_STALE_DELETE_MIN_RATIO = 0.5  # neue Menge >= 50% der bisherigen Rows

# asyncpg erlaubt hoechstens 32'767 Bind-Parameter je Statement, der Upsert
# braucht 9 je Zeile: ein Fonds mit mehr als 3640 Holdings liesse sich in einem
# einzigen Statement nie speichern. 1000 Zeilen je Block lassen Luft fuer neue Spalten.
_UPSERT_CHUNK_ROWS = 1000


def _stale_delete_allowed(new_count: int, existing_count: int) -> bool:
    """True wenn der neue Fetch vollstaendig genug wirkt, um weggefallene
    Holdings des ETFs zu loeschen (M11-Guard)."""
    if new_count < _STALE_DELETE_MIN_ROWS:
        return False
    if existing_count > 0 and new_count < existing_count * _STALE_DELETE_MIN_RATIO:
        return False
    return True


def is_us_etf(ticker: str) -> bool:
    """US-ETF-Detection: ticker enthält keinen Punkt.

    OEF, SPY, VOO, IVV → US. CHSPI.SW, SWDA.L, JPNA.L, SSV.TO → Non-US.
    Diese Heuristik ist FMP-konform: alle FMP-coverten ETFs haben
    Suffix-freie Ticker; Listings auf .SW/.L/.TO sind separate
    Wertpapiere, die FMP typischerweise nicht im Holdings-Endpoint hat.
    """
    return "." not in ticker


async def _get_any_user_fmp_key(db: AsyncSession) -> str | None:
    """FMP-Key für den globalen ETF-Refresh (ETF-Holdings sind nicht user-spezifisch).

    Der System-Key (FMP_SYSTEM_API_KEY) gilt zuerst, sonst der Key des ältesten
    aktiven Admin-Kontos. Der Key eines anderen Nutzers speist keinen globalen
    Job (K095). Der Funktionsname ist historisch.
    """
    from services.settings_service import get_system_api_key

    return await get_system_api_key(db, "fmp_api_key")


def _source_identity(ref: EtfRef) -> tuple[str | None, str | None]:
    """Welche Holdings-Quelle ein Ref waehlt: (Quelle, ISIN fuer den Abruf).

    Name und ISIN einer Position sind freie Nutzerfelder, und genau sie steuern
    Adapter und Abruf-URL. Zwei Refs mit gleicher Identitaet laden denselben Fonds.
    Die Reihenfolge entspricht dem Routing in refresh_etf_holdings: Adapter vor
    FMP. (None, None) heisst: die Angaben waehlen keine Quelle.
    """
    adapter = get_adapter(ref)
    if adapter is None:
        # FMP laedt nur ueber den Ticker, die ISIN spielt dort keine Rolle.
        return ("FMP", None) if is_us_etf(ref.ticker) else (None, None)
    uses_isin = getattr(adapter, "uses_isin", True)
    return (adapter.name, ref.isin_valid if uses_isin else None)


def _pick_etf_ref(ticker: str, positions: list[EtfRef]) -> tuple[EtfRef, dict | None]:
    """Waehlt aus den Positionen eines Tickers den Ref fuer den Abruf.

    ``positions`` ist nach Alter sortiert, die aelteste zuerst. Rueckgabe:
    (Ref, Konflikt oder None). Die Regeln stehen bei _resolve_active_etf_refs.
    """
    # ISIN des Tickers: die der aeltesten Position mit gueltiger ISIN. Eine ISIN,
    # die das Format nicht erfuellt, waehlt nie eine Quelle und gilt als leer.
    ticker_isin = next((p.isin_valid for p in positions if p.isin_valid), None)

    # (Ref fuer den Abruf, Position): alle, die eine Quelle waehlen, aelteste zuerst.
    votes: list[tuple[EtfRef, EtfRef]] = []
    rejected: list[dict[str, str | None]] = []

    def _reject(source: str | None, isin: str | None) -> None:
        claim = {"source": source, "isin": isin}
        if claim not in rejected:
            rejected.append(claim)

    for pos in positions:
        if pos.isin_valid and pos.isin_valid != ticker_isin:
            # Andere ISIN als die aelteste: die Position unterliegt.
            _reject(_source_identity(pos)[0], pos.isin_valid)
            continue
        ref = pos
        if _source_identity(ref)[0] is None and not pos.isin_valid and ticker_isin:
            # Die eigenen Angaben waehlen keine Quelle und die ISIN fehlt: die ISIN
            # des Tickers gilt. Ein US-Ticker erbt nie, er hat mit FMP eine Quelle.
            ref = EtfRef(ticker=ticker, isin=ticker_isin, name=pos.name)
        if _source_identity(ref)[0] is not None:
            votes.append((ref, pos))

    # Ohne Stimme hat der Ticker keine Quelle: refresh_etf_holdings meldet no_source.
    chosen, origin = votes[0] if votes else (positions[0], positions[0])
    chosen_identity = _source_identity(chosen)
    chosen_isin = chosen_identity[1] or ticker_isin
    inherited_isin_refuted = False
    for ref, pos in votes[1:]:
        identity = _source_identity(ref)
        if identity == chosen_identity:
            continue
        _reject(*identity)
        if chosen is not origin and ref is pos:
            inherited_isin_refuted = True
    if inherited_isin_refuted:
        # Die aelteste Stimme traegt nur die geerbte ISIN, und eine Position mit
        # dieser ISIN waehlt eine andere Quelle: die ISIN gehoert nicht zum Fonds
        # der aeltesten Position. Ihre Angabe gewinnt, sie bleibt aber ohne ISIN.
        chosen, chosen_isin = origin, None
    if not rejected:
        return chosen, None
    return chosen, {
        "etf_ticker": ticker,
        "positions": len(positions),
        "chosen": {"source": chosen_identity[0], "isin": chosen_isin},
        "rejected": rejected,
    }


async def _resolve_active_etf_refs(db: AsyncSession) -> tuple[list[EtfRef], list[dict]]:
    """Alle aktiven User-ETFs als EtfRef (ticker + isin + name) fuers Routing,
    dazu die Konflikte der Quellenwahl.

    Umfasst Aktien- UND Bond-ETFs (LOOKTHROUGH_POSITION_TYPES): auch ein Bond-ETF
    hat ein Holdings-Verzeichnis (Emittenten/Länder), das die Durchsicht braucht.

    etf_holdings ist pro Ticker global, Name und ISIN einer Position sind aber
    freie Nutzerfelder. Je Ticker entsteht genau ein Ref (K094, Zwischenregel bis
    die Holdings je Fonds-ISIN gespeichert werden):

    1. Kein Ticker faellt aus, weil eine Position keine ISIN oder keinen
       Markennamen traegt. Waehlen die Angaben einer Position keine Quelle,
       zaehlt sie nicht mit. Fehlt ihr nur die ISIN, gilt die ISIN des Tickers.
    2. Tragen Positionen verschiedene gueltige ISINs oder waehlen ihre Angaben
       verschiedene Quellen, gewinnt die Angabe der aeltesten Position
       (created_at, dann id). Ein neu angelegtes Konto lenkt die Quelle eines
       schon gefuehrten Tickers so nicht um und friert sie nicht ein. Bei einem
       US-Ticker ist FMP diese Quelle, auch ohne ISIN und Markennamen.
    3. Jeder solche Konflikt steht als WARNING im Log und in der Rueckgabe.

    Restrisiko: Traegt bei einem Nicht-US-Ticker noch keine Position eine ISIN,
    bestimmt die erste Position mit ISIN die Quelle fuer alle ohne ISIN.
    """
    result = await db.execute(
        select(Position.ticker, Position.isin, Position.name)
        .where(
            Position.type.in_(LOOKTHROUGH_POSITION_TYPES),
            Position.is_active.is_(True),
        )
        .order_by(Position.ticker, Position.created_at, Position.id)
    )
    # ticker -> Refs der Positionen, aelteste zuerst
    by_ticker: dict[str, list[EtfRef]] = {}
    for ticker, isin, name in result.all():
        if not ticker:
            continue
        by_ticker.setdefault(ticker, []).append(EtfRef(ticker=ticker, isin=isin, name=name))

    refs: list[EtfRef] = []
    conflicts: list[dict] = []
    for ticker, positions in by_ticker.items():
        ref, conflict = _pick_etf_ref(ticker, positions)
        refs.append(ref)
        if conflict is not None:
            logger.warning(
                "etf_holdings_refresh: %s, %d positions select different holdings "
                "sources: oldest wins with %s, rejected %s",
                ticker, conflict["positions"], conflict["chosen"], conflict["rejected"],
            )
            conflicts.append(conflict)
    return refs, conflicts


async def _get_active_etf_refs(db: AsyncSession) -> list[EtfRef]:
    """Nur die Refs aus _resolve_active_etf_refs, ein Ref je Ticker."""
    refs, _conflicts = await _resolve_active_etf_refs(db)
    return refs


async def get_bond_etf_tickers(db: AsyncSession) -> set[str]:
    """Ticker aller aktiven Anleihen-Positionen (Bond-ETFs/-Fonds).

    Consumer der etf_holdings-Tabelle brauchen diese Menge, um Bond-Holdings aus
    jeder Sektor-Rechnung herauszuhalten — Anleihen sind strukturell sektorlos.
    Die Assetklasse ist eine Eigenschaft des Instruments, nicht des Users: ein
    Ticker gilt als Bond-ETF, sobald ihn irgendein User als bond führt (die
    etf_holdings-Rows sind ebenfalls user-agnostisch pro Ticker gekeyt).
    """
    result = await db.execute(
        select(Position.ticker)
        .where(Position.type == "bond", Position.is_active.is_(True))
        .distinct()
    )
    return {ticker for (ticker,) in result.all() if ticker}


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
    # Gewicht wie in make_holding_row absichern: float-coercen (FMP kann Strings
    # liefern) UND nicht-endliche/<=0 verwerfen. Ein NaN/Inf-Gewicht passierte sonst
    # den Guard (nan/inf <= 0 ist False), wuerde persistiert und korrumpierte die
    # Laender-Durchsicht (/country-lookthrough 500). Symmetrisch zum Adapter-Pfad.
    weight = row.get("weightPercentage")
    if weight is None:
        return None
    try:
        weight = float(weight)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(weight) or weight <= 0:
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
        "weight_pct": weight,
        "as_of": as_of_date,
    }


async def _enrich_isin_rows(rows: list[dict]) -> list[dict]:
    """ISIN-gekeyte Rows (holding_ticker == holding_isin) fuer die groessten Holdings
    per OpenFIGI auf einen yfinance-Ticker heben (in-place). Best-effort + gebunden.

    Bringt Overlap-Reverse-Lookup + Sektor-Classify-Fallback fuer Anbieter, die nur
    ISINs liefern (Xtrackers/SPDR/HSBC/Fidelity). Fehler/Timeouts sind nicht fatal —
    die Row bleibt dann auf dem ISIN-Key (Land/Sektor sind meist Issuer-nativ)."""
    candidates = [
        r for r in rows
        if r.get("holding_isin") and r.get("holding_ticker") == r.get("holding_isin")
        and (r.get("weight_pct") or 0) >= _ENRICH_MIN_WEIGHT_PCT
    ]
    if not candidates:
        return rows
    top = sorted(candidates, key=lambda r: r.get("weight_pct") or 0, reverse=True)
    top = top[:_ENRICH_MAX_HOLDINGS]
    try:
        mapping = await resolve_isins([r["holding_isin"] for r in top])
    except Exception:
        logger.exception("etf_holdings_refresh: ISIN-Anreicherung fehlgeschlagen")
        return rows
    for r in top:
        yf = mapping.get(r["holding_isin"])
        if yf:
            r["holding_ticker"] = yf[:30]
    return rows


def _coerce_ref(ref: "EtfRef | str") -> EtfRef:
    """Akzeptiere EtfRef ODER blossen Ticker-String (Rueckwaerts-Kompat/Tests)."""
    if isinstance(ref, EtfRef):
        return ref
    return EtfRef(ticker=str(ref), isin=None, name=None)


async def refresh_etf_holdings(
    db: AsyncSession, ref: "EtfRef | str", api_key: str,
) -> dict:
    """Refresh die Holdings eines einzelnen ETFs via passendem Issuer-Adapter (oder FMP).

    Routing: erst die keylose Adapter-Registry (iShares/Xtrackers/SPDR/Amundi/JPM/
    HSBC/Fidelity — nach Marke+ISIN), dann US-FMP als Fallback, sonst Skip.
    Skip wenn der letzte Pull < CORE_OVERLAP_HOLDINGS_TTL_DAYS zurueckliegt
    (idempotent fuer den woechentlichen Cron). UPSERT pro Holding-Row.
    """
    ref = _coerce_ref(ref)
    etf_ticker = ref.ticker

    # --- Source-Routing: keylose Issuer-Adapter vor US-FMP, sonst Skip ---
    adapter = get_adapter(ref)
    if adapter is not None:
        source = "adapter"
    elif is_us_etf(etf_ticker):
        source = "fmp"
    else:
        logger.info("etf_holdings_refresh: skip ETF ohne Holdings-Quelle %s", etf_ticker)
        return {"etf_ticker": etf_ticker, "skipped": True, "reason": "no_source"}

    # TTL-Check (beide Quellen): wann wurde dieser ETF zuletzt aktualisiert?
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

    now = utcnow()
    rows_map: dict[tuple[str, str], dict] = {}

    if source == "adapter":
        # Keyloser Issuer-Adapter (iShares/Xtrackers/SPDR/Amundi/JPM/HSBC/Fidelity).
        try:
            parsed_rows = await adapter.fetch(ref)
        except Exception:
            logger.exception("etf_holdings_refresh: adapter %s fetch raised for %s",
                             adapter.name, etf_ticker)
            return {"etf_ticker": etf_ticker, "error": f"{adapter.name.lower()}_fetch_failed"}
        if parsed_rows is None:
            return {"etf_ticker": etf_ticker, "error": f"{adapter.name.lower()}_fetch_failed"}
        # Bounded ISIN->Ticker-Anreicherung fuer nur-ISIN-Rows (Overlap/Sektor-Fallback).
        parsed_rows = await _enrich_isin_rows(parsed_rows)
        for p in parsed_rows:
            p["updated_at"] = now
            rows_map[(etf_ticker, p["holding_ticker"])] = p
        src_label = adapter.name
    else:
        # FMP-Call (Stable-API — der v3 /etf-holder Endpoint gibt 403 zurück;
        # Stable nutzt symbol als Param statt Path-Variable.)
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
        # Parse + dedup; FMP gibt Cash-Buckets mit asset == etf_ticker (Self-Ref) raus.
        for raw in data:
            if not isinstance(raw, dict):
                continue
            parsed = _parse_fmp_holding(raw)
            if parsed is None or parsed["asset"] == etf_ticker:
                continue
            rows_map[(etf_ticker, parsed["asset"])] = {
                "etf_ticker": etf_ticker,
                "holding_ticker": parsed["asset"],
                "holding_name": parsed["name"],
                "weight_pct": parsed["weight_pct"],
                "as_of": parsed["as_of"],
                "holding_isin": None,        # FMP-US-Pfad liefert weder ISIN noch Land
                "holding_country": None,
                "holding_sector": None,      # -> classify_tickers_bulk-Fallback (US gut abgedeckt)
                "updated_at": now,
            }
        src_label = "FMP"

    rows = list(rows_map.values())
    if not rows:
        logger.warning(
            "etf_holdings_refresh: %s [%s] returned no parseable rows, "
            "existing holdings stay unchanged",
            etf_ticker, src_label,
        )
        return {"etf_ticker": etf_ticker, "error": "no_parseable_rows"}

    # Bestand VOR dem Upsert zaehlen — Input fuer den Stale-Delete-Guard.
    existing_count = (
        await db.execute(
            select(func.count()).select_from(EtfHolding)
            .where(EtfHolding.etf_ticker == etf_ticker)
        )
    ).scalar() or 0

    # UPSERT (gemeinsam fuer beide Quellen, inkl. holding_isin/holding_country),
    # in Bloecken und in derselben Transaktion (siehe _UPSERT_CHUNK_ROWS).
    for start in range(0, len(rows), _UPSERT_CHUNK_ROWS):
        stmt = pg_insert(EtfHolding).values(rows[start:start + _UPSERT_CHUNK_ROWS])
        stmt = stmt.on_conflict_do_update(
            index_elements=["etf_ticker", "holding_ticker"],
            set_={
                "holding_name": stmt.excluded.holding_name,
                "weight_pct": stmt.excluded.weight_pct,
                "as_of": stmt.excluded.as_of,
                "holding_isin": stmt.excluded.holding_isin,
                "holding_country": stmt.excluded.holding_country,
                "holding_sector": stmt.excluded.holding_sector,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await db.execute(stmt)

    # M11: Aus dem Index gefallene Holdings loeschen — sonst akkumulieren stale
    # Rows mit alten Gewichten (Gewichtssumme > 100%, Phantom-Exposure im
    # Look-Through/Overlap). Gleiche Transaktion wie der Upsert; der Guard
    # verhindert, dass ein unplausibel kleiner Fetch die Tabelle leert.
    deleted = 0
    if _stale_delete_allowed(len(rows), existing_count):
        new_tickers = [r["holding_ticker"] for r in rows]
        del_result = await db.execute(
            delete(EtfHolding).where(
                EtfHolding.etf_ticker == etf_ticker,
                EtfHolding.holding_ticker.not_in(new_tickers),
            )
        )
        deleted = int(del_result.rowcount or 0)
    elif existing_count > len(rows):
        logger.warning(
            "etf_holdings_refresh: %s stale-delete skipped (fetch %d rows vs. "
            "%d existing — plausibly incomplete)",
            etf_ticker, len(rows), existing_count,
        )

    await db.commit()

    logger.info(
        "etf_holdings_refresh: %s [%s] persisted %d holdings, deleted %d stale (as_of=%s)",
        etf_ticker, src_label, len(rows), deleted, rows[0].get("as_of"),
    )
    return {
        "etf_ticker": etf_ticker,
        "source": src_label,
        "count": len(rows),
        "stale_deleted": deleted,
        "as_of": rows[0]["as_of"].isoformat() if rows[0].get("as_of") else None,
    }


async def refresh_all_user_etfs(db: AsyncSession) -> dict:
    """Refresh alle aktiven User-ETFs in einem Durchgang.

    Robust: per-ETF-Failures werden geloggt, andere ETFs laufen weiter.
    Ohne FMP-Key wird NICHT komplett abgebrochen — die keylosen Quellen (iShares)
    laufen trotzdem; nur die FMP-(US-)ETFs scheitern dann einzeln.

    ``conflicts`` nennt die Ticker, deren Positionen verschiedene Quellen waehlen.
    Sie werden trotzdem aktualisiert, mit der Angabe der aeltesten Position
    (siehe _resolve_active_etf_refs).
    """
    api_key = await _get_any_user_fmp_key(db) or ""
    if not api_key:
        logger.warning(
            "etf_holdings_refresh: kein FMP-Key — nur keylose Quellen (iShares) werden refreshed"
        )

    etfs, conflicts = await _resolve_active_etf_refs(db)
    if not etfs:
        return {"refreshed": [], "skipped": [], "conflicts": conflicts, "etf_count": 0}

    refreshed: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for ref in etfs:
        etf_ticker = ref.ticker if isinstance(ref, EtfRef) else str(ref)
        try:
            result = await refresh_etf_holdings(db, ref, api_key)
            if result.get("skipped"):
                skipped.append(result)
            elif result.get("error"):
                # WARNING je ETF: sonst steht ein Dauerfehler (z. B. geaendertes
                # Feed-Format) nur als Teil einer INFO-Zeile im Worker-Log.
                logger.warning(
                    "etf_holdings_refresh: %s failed: %s", etf_ticker, result["error"],
                )
                errors.append(result)
            else:
                refreshed.append(result)
        except Exception as e:
            logger.exception("etf_holdings_refresh: unexpected error for %s", etf_ticker)
            errors.append({"etf_ticker": etf_ticker, "error": str(e)})
            # Session nach einem (transienten) DB-Fehler bereinigen — sonst bleibt
            # sie im failed-transaction-state und ALLE Folge-ETFs werfen
            # PendingRollbackError (gleiches Muster wie dividend_forecast_service).
            try:
                await db.rollback()
            except Exception:
                logger.exception("etf_holdings_rollback_failed etf=%s", etf_ticker)

    return {
        "refreshed": refreshed,
        "skipped": skipped,
        "errors": errors,
        "conflicts": conflicts,
        "etf_count": len(etfs),
    }
