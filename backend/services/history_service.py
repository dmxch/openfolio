"""Portfolio history reconstruction — daily portfolio value + benchmark."""
import asyncio
import logging
import threading
import time
import uuid
from collections import defaultdict
from datetime import date, timedelta
from types import SimpleNamespace

import yfinance as yf
from yf_patch import yf_download, yf_to_thread
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType
from services import cache
from services.portfolio_service import (
    portfolio_cache_version,
    release_db_connection,
    single_flight,
)
from services.utils import get_fx_rates_batch

logger = logging.getLogger(__name__)

CACHE_TTL = 900  # 15 min
# Antwort ohne eine einzige Kursreihe (Yahoo-Ausfall): nur kurz halten, damit
# der nächste Aufruf sie heilt, statt 15 Minuten Einstandswerte zu zeigen.
DEGRADED_CACHE_TTL = 60

# Höchstens zwei Kurs-Downloads der Historie je Prozess (K008). Jeder lädt alle
# Ticker eines Depots nacheinander und belegt dafür einen Thread des
# Default-Executors; ohne Grenze füllen wenige Nutzer den Pool und treiben
# Yahoo in die IP-Sperre. Gewartet wird auf dem Event-Loop, nicht in einem
# Thread: ein wartender Request kostet so keinen Pool-Thread.
_YF_DOWNLOAD_SLOTS = threading.BoundedSemaphore(2)
_DOWNLOAD_SLOT_POLL_SECONDS = 0.05
_DOWNLOAD_SLOT_WAIT_SECONDS = 60.0


async def _acquire_download_slot() -> bool:
    """Wartet auf einen freien Download-Platz. False, wenn keiner frei wird."""
    deadline = time.monotonic() + _DOWNLOAD_SLOT_WAIT_SECONDS
    while not _YF_DOWNLOAD_SLOTS.acquire(blocking=False):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_DOWNLOAD_SLOT_POLL_SECONDS)
    return True

from constants.cashflow import INFLOW_TYPES, OUTFLOW_TYPES


def _leeres_ergebnis() -> dict:
    """Leere Antwort MIT den Metadaten-Feldern.

    Die Doku verspricht ``downsampled``/``sample_interval_days`` vorbehaltlos;
    ein Konsument, der ``resp["downsampled"]`` liest, darf am leeren Portfolio
    oder am yfinance-Fehlerpfad nicht brechen.
    """
    return {"data": [], "summary": {}, "downsampled": False, "sample_interval_days": 1}


async def _history_inception(
    db: AsyncSession,
    user_id: uuid.UUID | None,
    bucket_id: uuid.UUID | None,
    end_date: date,
) -> tuple[bool, date | None]:
    """``(hat Positionen, Inception)`` aus Aggregat-Abfragen.

    Dieselbe Regel wie die Klemmung in ``_compute_portfolio_history`` (früheste
    Transaktion des Nutzers, frühestes Edelmetall-Kaufdatum, sonst Anlagedatum
    der Positionen), aber ohne das Ledger zu laden: der Wert geht in den
    Cache-Schlüssel ein und wird deshalb bei JEDEM Aufruf gebraucht, auch bei
    einem Cache-Treffer.
    """
    from models.precious_metal_item import PreciousMetalItem
    from services.precious_metals_service import METAL_TICKERS

    pos_query = select(
        Position.ticker, Position.user_id, Position.type, Position.gold_org,
        Position.is_active, Position.shares, Position.created_at,
    )
    if user_id is not None:
        pos_query = pos_query.where(Position.user_id == user_id)
    if bucket_id is not None:
        pos_query = pos_query.where(Position.bucket_id == bucket_id)
    rows = (await db.execute(pos_query)).all()
    if not rows:
        return False, None

    txn_query = select(func.min(Transaction.date))
    if user_id is not None:
        txn_query = txn_query.where(Transaction.user_id == user_id)
    first_txn = (await db.execute(txn_query)).scalar()
    candidates: list[date] = [first_txn] if first_txn else []

    ticker_to_metal = {v: k for k, v in METAL_TICKERS.items()}
    metal_owners = {
        (r.user_id, ticker_to_metal[r.ticker])
        for r in rows
        if r.gold_org and r.is_active and float(r.shares or 0) > 0
        and r.type not in (AssetType.private_equity, AssetType.real_estate)
        and r.ticker in ticker_to_metal
    }
    metal_dates = []
    for owner_id, metal_type in metal_owners:
        first_purchase = (await db.execute(
            select(func.min(PreciousMetalItem.purchase_date)).where(
                PreciousMetalItem.user_id == owner_id,
                PreciousMetalItem.metal_type == metal_type,
                PreciousMetalItem.is_sold == False,  # noqa: E712
                PreciousMetalItem.weight_grams > 0,
                PreciousMetalItem.purchase_date <= end_date,
            )
        )).scalar()
        if first_purchase:
            metal_dates.append(first_purchase)
    if metal_dates:
        candidates.append(min(metal_dates))

    if not candidates:
        created = [r.created_at.date() for r in rows if r.created_at is not None]
        if created:
            candidates.append(min(created))
    return True, (min(candidates) if candidates else None)


async def get_portfolio_history(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    benchmark: str = "^GSPC",
    user_id: uuid.UUID | None = None,
    downsample: bool = True,
    liquid: bool = False,
    bucket_id: uuid.UUID | None = None,
) -> dict:
    # downsample=False liefert die ungedownsamplete tägliche Rekonstruktion (raw=true).
    # Notwendig für empirische Auswertungen (Faktor-Regression, Event-Study), die jede
    # echte Tagesbeobachtung brauchen. Es wird KEINE synthetische Historie erzeugt — die
    # Kurve reicht weiterhin nur bis zur echten Inception (min(transaction_dates)).
    #
    # liquid=True schliesst zusätzlich Cash UND Vorsorge (pension) aus — uebrig bleibt das
    # Rendite-Risikobuch (stock/etf/crypto/commodity, inkl. Gold+BTC). Default-Verhalten
    # zaehlt Vorsorge als Cash mit (Konvention wie PortfolioSnapshot); der konstante
    # Null-Rendite-Ballast daempft sonst Faktor-Betas/Vol. PE + real_estate sind in beiden
    # Faellen ausgeschlossen.
    #
    # bucket_id setzt die Rekonstruktion auf die Positionen EINES Buckets ein
    # (Membership = aktueller Position.bucket_id). Damit teilt sich der
    # Bucket-Drawdown exakt die cash-flow-bereinigte portfolio_indexed-Methodik
    # wie das Gesamt-Portfolio — Ein-/Auszahlungen taeuschen keinen Drawdown vor.

    # Fenster klemmen, BEVOR der Cache-Schluessel entsteht (K024/K029). start und
    # end sind frei waehlbar: ohne Klemmung erzwingt jeder neue Wert eine volle
    # Rekonstruktion, und ein Enddatum in der Zukunft liess die Tagesschleife bis
    # zum Jahr 9999 laufen. Jedes Fenster vor der Inception und jedes Ende nach
    # heute faellt so auf denselben Schluessel.
    today = date.today()
    if end_date > today:
        end_date = today
    if start_date > end_date:
        return _leeres_ergebnis()
    has_positions, inception = await _history_inception(db, user_id, bucket_id, end_date)
    if not has_positions:
        return _leeres_ergebnis()
    if inception is not None:
        if end_date < inception:
            return _leeres_ergebnis()
        if start_date < inception:
            start_date = inception

    # Praefix-Suffix ":bchf" markiert die Benchmark-Waehrungsumstellung — unter
    # dem alten Schluessel liegen Reihen mit Benchmark in Notierungswaehrung.
    # Ohne Umbenennung liefe der Deploy bis zum TTL-Ablauf gegen alte Zahlen.
    # Die Versionsmarke entwertet den Eintrag nach Buchung und Regen (K039).
    cache_key = (
        f"portfolio_history:{user_id}:v{portfolio_cache_version(user_id)}"
        f":{start_date}:{end_date}:{benchmark}"
        f":ds{int(downsample)}:lq{int(liquid)}:bk{bucket_id or ''}:bchf:inc"
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Gleichzeitige Aufrufe mit demselben Schluessel (die Performance-Seite
    # stellt mehrere) rechnen einmal und teilen das Ergebnis (K008). Wer dabei
    # nur wartet, soll keine Connection halten (K016).
    await release_db_connection(db)
    return await single_flight(
        cache_key,
        lambda: _compute_portfolio_history(
            db, start_date, end_date, benchmark, user_id, downsample, liquid,
            bucket_id, cache_key,
        ),
    )


def _pids_held_in_window(
    holdings_changes: dict,
    seeded_holdings: dict[str, float],
    start_date: date,
    end_date: date,
) -> set[str]:
    """Positionen, die an mindestens einem Tag des Fensters Bestand haben.

    Nur sie brauchen Kurse. Addiert in derselben Reihenfolge wie der Replay,
    damit Rundungsreste gleich ausfallen: erst alle Aenderungen vor dem Fenster,
    dann Tag fuer Tag.
    """
    holdings: dict[str, float] = defaultdict(float)
    for pid, shares in seeded_holdings.items():
        holdings[pid] = shares
    held: set[str] = set()
    window_open = False
    for d in sorted(holdings_changes):
        if d > end_date:
            break
        if d >= start_date and not window_open:
            held.update(pid for pid, shares in holdings.items() if shares > 0)
            window_open = True
        for pid, delta in holdings_changes[d]:
            holdings[pid] += delta
        if window_open:
            held.update(pid for pid, _ in holdings_changes[d] if holdings[pid] > 0)
    if not window_open:
        held.update(pid for pid, shares in holdings.items() if shares > 0)
    return held


def _build_price_series(
    price_data, all_tickers: list[str], price_divisor: dict[str, float]
) -> dict[str, list[tuple[str, float]]] | None:
    """Kursreihen je Ticker als sortierte ``(Datum, Kurs)``-Liste. Reine Funktion.

    ``None``: der Download fuer genau einen Ticker lieferte keine Close-Spalte.
    """
    if price_data is None:
        return {}
    if len(all_tickers) == 1:
        single_ticker = all_tickers[0]
        if "Close" in price_data.columns:
            import pandas as pd
            close_df = price_data[["Close"]].copy()
            close_df.columns = pd.MultiIndex.from_tuples([("Close", single_ticker)])
        else:
            return None
    else:
        close_df = price_data["Close"] if "Close" in price_data.columns else price_data

    # Pre-build price lookup dict: ticker -> sorted list of (date_str, price)
    _price_series: dict[str, list[tuple[str, float]]] = {}
    for ticker in all_tickers:
        try:
            if len(all_tickers) == 1:
                col = close_df[("Close", ticker)]
            else:
                col = close_df[ticker]
            series = col.dropna()
            div = price_divisor.get(ticker, 1.0)
            _price_series[ticker] = [
                (d.strftime("%Y-%m-%d"), float(v) / div)
                for d, v in zip(series.index, series.values)
            ]
        except (KeyError, IndexError) as e:
            logger.debug(f"Could not build price series for {ticker}: {e}")
            _price_series[ticker] = []
    return _price_series


async def _compute_portfolio_history(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    benchmark: str,
    user_id: uuid.UUID | None,
    downsample: bool,
    liquid: bool,
    bucket_id: uuid.UUID | None,
    cache_key: str,
) -> dict:
    """Rekonstruktion bei einem Cache-Miss. Fenster ist bereits geklemmt."""
    # 1. Load positions (user-scoped)
    pos_query = select(Position)
    if user_id is not None:
        pos_query = pos_query.where(Position.user_id == user_id)
    if bucket_id is not None:
        pos_query = pos_query.where(Position.bucket_id == bucket_id)
    result = await db.execute(pos_query)
    positions = {str(p.id): p for p in result.scalars().all()}

    # 2. Load transactions (user-scoped via Transaction.user_id)
    if not positions:
        return _leeres_ergebnis()
    txn_query = select(Transaction).order_by(Transaction.date.asc())
    if user_id is not None:
        txn_query = txn_query.where(Transaction.user_id == user_id)
    result = await db.execute(txn_query)
    all_txns = result.scalars().all()

    # 2b. Edelmetalle (gold_org) haben KEINE Transaktionen — ihre Holdings werden aus
    #     precious_metal_items rekonstruiert: pro (noch nicht verkauftem) Item ein
    #     synthetischer holdings_change am echten purchase_date. Dadurch waechst die
    #     gehaltene Menge exakt wie real akkumuliert, ist VOR dem ersten Kauf 0 (kein
    #     Phantom-Vorlauf in Vola/Drawdown/Faktoren) und wird ab Kauf taeglich ueber die
    #     Futures-Mapping markiert — cashflow-neutral ueber denselben value_before_cf-
    #     Mechanismus wie echte Txns. Fallback (kein/undatiertes Item): ab Fensterstart.
    from models.precious_metal_item import GRAMS_PER_TROY_OZ, PreciousMetalItem
    from services.precious_metals_service import METAL_TICKERS

    _ticker_to_metal = {v: k for k, v in METAL_TICKERS.items()}
    metal_pids: set[str] = set()
    metal_changes: list[tuple[str, date, float]] = []  # (pid, purchase_date, oz)
    seeded_holdings: dict[str, float] = {}  # Fallback ohne Item-Historie -> ab Start
    earliest_metal_date: date | None = None
    for pid, pos in positions.items():
        if not (pos.gold_org and pos.is_active and float(pos.shares or 0) > 0):
            continue
        if pos.type in (AssetType.private_equity, AssetType.real_estate):
            continue
        metal_pids.add(pid)
        metal_type = _ticker_to_metal.get(pos.ticker)
        rows = []
        if metal_type:
            rows = (
                await db.execute(
                    select(
                        PreciousMetalItem.purchase_date,
                        PreciousMetalItem.weight_grams,
                    ).where(
                        PreciousMetalItem.user_id == pos.user_id,
                        PreciousMetalItem.metal_type == metal_type,
                        PreciousMetalItem.is_sold == False,  # noqa: E712
                    )
                )
            ).all()
        injected = False
        for pdate, grams in rows:
            oz = float(grams or 0) / GRAMS_PER_TROY_OZ
            if pdate is None or oz <= 0 or pdate > end_date:
                continue
            metal_changes.append((pid, pdate, oz))
            injected = True
            if earliest_metal_date is None or pdate < earliest_metal_date:
                earliest_metal_date = pdate
        if not injected:
            # Keine datierten Items -> Position nicht verschwinden lassen: ab Start halten.
            seeded_holdings[pid] = float(pos.shares)

    # Serie an der echten Inception verankern statt am angefragten Start
    # (period=all → 2000). Statische Cash/Vorsorge-Positionen wuerden sonst mit
    # konstantem cost_basis rueckwaerts bis zum Start-Datum emittiert (Index auf
    # 100 festgenagelt) — ein synthetisches Pre-Inception-Plateau. Inception =
    # frueheste echte Txn ODER fruehestes Edelmetall-Kaufdatum (Metalle haben
    # keine Txns). Wir kuerzen nur nach vorne.
    #
    # Diese Klemmung hing frueher an ``not downsample``, war also nur auf dem
    # raw-Pfad aktiv — dem Pfad fuer empirische Auswertungen. Der DEFAULT-Pfad,
    # den das UI und jeder normale Konsument benutzt, lieferte weiter das
    # Plateau: ``period=all`` behauptete auf Prod 1713 Punkte lang einen
    # Portfoliowert von CHF 139'719.13 ab dem Jahr 2000, und die Zusammenfassung
    # rechnete daraus eine Rendite von 3.97 %. Mit Downsampling hat die Frage,
    # WO die Reihe beginnt, nichts zu tun.
    inception_dates = [t.date for t in all_txns[:1]]  # frueheste Txn (date.asc())
    if earliest_metal_date is not None:
        inception_dates.append(earliest_metal_date)
    if not inception_dates:
        # Weder Transaktion noch datiertes Edelmetall — genau die Konstellation,
        # die das Plateau ueberhaupt erzeugt (nur statische Cash-/Vorsorge-Salden
        # oder undatiertes Metall via seeded_holdings). Ohne Fallback bliebe
        # ausgerechnet dieser Fall ungeklemmt und produzierte weiter eine
        # erfundene Reihe ab dem angefragten Start — bei Fremdwaehrungs-Cash
        # sogar mit erfundener FX-"Performance" ueber Jahrzehnte.
        # Anker dann: wann die Daten im System entstanden sind. Das ist die
        # ehrlichste verfuegbare Aussage, wenn es keine datierte Historie gibt.
        anlagedaten = [
            p.created_at.date() for p in positions.values()
            if getattr(p, "created_at", None) is not None
        ]
        if anlagedaten:
            inception_dates.append(min(anlagedaten))
    if inception_dates:
        inception = min(inception_dates)
        if end_date < inception:
            # Fenster liegt KOMPLETT vor der Inception. Ohne diesen Ausstieg
            # wird das statische Plateau ueber das ganze Fenster emittiert —
            # eine Reihe fuer einen Zeitraum, in dem es das Portfolio nicht gab.
            # Leer ist die ehrliche Antwort.
            return _leeres_ergebnis()
        if start_date < inception:
            start_date = inception

    # 3. Build holdings timeline
    holdings_changes = defaultdict(list)  # date -> [(position_id, share_delta)]
    positions_with_txns = set()
    cashflows_by_date = defaultdict(float)  # date -> net cashflow in CHF

    for txn in all_txns:
        if txn.date > end_date:
            continue
        positions_with_txns.add(str(txn.position_id))
        delta = 0.0
        if txn.type in (TransactionType.buy, TransactionType.delivery_in):
            delta = float(txn.shares)
        elif txn.type in (TransactionType.sell, TransactionType.delivery_out):
            delta = -float(txn.shares)
        if delta != 0:
            holdings_changes[txn.date].append((str(txn.position_id), delta))

        if txn.type in INFLOW_TYPES:
            cashflows_by_date[txn.date] += float(txn.total_chf)
        elif txn.type in OUTFLOW_TYPES:
            cashflows_by_date[txn.date] -= float(txn.total_chf)

    # Synthetische Edelmetall-Holdings (aus 2b) in die Timeline einspeisen — danach
    # werden Metalle exakt wie transaktions-basierte Positionen behandelt.
    for pid, pdate, oz in metal_changes:
        holdings_changes[pdate].append((pid, oz))

    # Identify positions with no transactions (cash, pension, manually added).
    # Edelmetalle (gold_org, metal_pids) sind bereits ueber 2b als markt-bepreiste
    # Holdings erfasst und duerfen hier NICHT zusaetzlich als flache cost_basis-
    # Konstante landen (sonst doppelt gezaehlt + degenerierte Risiko-Kennzahlen).
    static_positions = {}
    # Cash/Vorsorge: cost_basis_chf ist der Saldo in POSITIONSWÄHRUNG
    # (Invariante) — Live- und Snapshot-Pfad rechnen saldo × fx, die History
    # zählte den Saldo bisher 1:1 als CHF (Review 2026-07-02, H1).
    static_fx_positions: dict[str, tuple[float, str]] = {}
    for pid, pos in positions.items():
        if pid in positions_with_txns or pid in metal_pids or not pos.is_active:
            continue
        if pos.type in (AssetType.private_equity, AssetType.real_estate):
            continue  # PE + Immobilien komplett aus der History excluded (Invariante #2)
        if float(pos.cost_basis_chf) <= 0:
            continue
        if liquid and pos.type in (AssetType.cash, AssetType.pension):
            continue  # liquid-only: Cash/Vorsorge raus
        if pos.type in (AssetType.cash, AssetType.pension) and pos.currency and pos.currency != "CHF":
            static_fx_positions[pid] = (float(pos.cost_basis_chf), pos.currency)
        else:
            static_positions[pid] = float(pos.cost_basis_chf)

    if not holdings_changes and not static_positions and not static_fx_positions and not seeded_holdings:
        return _leeres_ergebnis()

    # Ab hier keine DB-Abfrage mehr, aber Threads und Yahoo: die Connection
    # geht vorher zurueck in den Pool (K016).
    await release_db_connection(db)

    # 4. Determine tickers we need prices for — nur Positionen mit Bestand im
    # Fenster (K008). Vorher lud jeder Aufruf auch die Kurse laengst verkaufter
    # Titel, die der Replay nie abfragt.
    held_pids = _pids_held_in_window(holdings_changes, seeded_holdings, start_date, end_date)
    any_priced_position = False
    tradable_positions = {}
    for pid, pos in positions.items():
        if pos.type in (AssetType.cash, AssetType.pension, AssetType.private_equity, AssetType.real_estate):
            continue
        any_priced_position = True
        if pid not in held_pids:
            continue

        # Edelmetall: yfinance-Futures + USD (CHF-Spot-Ticker wie XAUCHF=X
        # sind in yfinance nicht verfuegbar). Mapping pro Spot-Ticker.
        if pos.gold_org:
            from services.precious_metals_service import get_metal_futures
            fut = get_metal_futures(pos.ticker)
            if fut:
                yf_ticker, currency = fut
            else:
                yf_ticker = "GC=F"
                currency = "USD"
        # Crypto: use {COIN}-USD + FX conversion (BTC-CHF not available in yfinance)
        elif pos.type == AssetType.crypto and pos.coingecko_id:
            yf_ticker = pos.yfinance_ticker or pos.ticker
            currency = "USD"
        else:
            yf_ticker = pos.yfinance_ticker or pos.ticker
            currency = pos.currency

        tradable_positions[pid] = {
            "ticker": yf_ticker,
            "currency": currency,
            "type": pos.type,
            # Nur fuer den Rueckgriff auf den letzten CoinGecko-Kurs (Schritt 5).
            "coingecko_id": (
                pos.coingecko_id if pos.type == AssetType.crypto and pos.coingecko_id else None
            ),
        }

    # 4b. LSE-Pence-Korrektur: yfinance quotiert viele .L-Titel in Pence (GBp),
    # nicht Pfund. Ohne ÷100 ist die historische Bewertung 100x zu hoch — derselbe
    # GBX-Bug, der im Live-/Snapshot-Pfad laengst gefixt ist (cache_service.
    # _pence_divisor), hier aber fehlte und /performance/history fuer Pence-.L-
    # Haltefenster auf das ~100-fache aufblies. Divisor + echte Quote-Waehrung
    # kommen aus denselben cache_service-Helpern wie der Live-Pfad; die oft falsche
    # pos.currency (.L kann USD/GBP/GBp sein) wird fuer .L-Ticker ueberschrieben.
    from services.cache_service import _quote_currency

    lse_tickers = {
        info["ticker"] for info in tradable_positions.values()
        if info["ticker"].endswith(".L")
    }
    price_divisor: dict[str, float] = {}
    # .L-Ticker, deren Notierungswaehrung Yahoo nicht liefert (Fehler, Lock-Frist).
    lse_unknown: set[str] = set()
    if lse_tickers:
        def _lse_quote_currencies() -> dict[str, str | None]:
            found: dict[str, str | None] = {}
            for t in lse_tickers:
                try:
                    found[t] = _quote_currency(t)
                except Exception as e:
                    logger.warning(f"Quote currency lookup failed for {t}: {e}")
                    found[t] = None
            return found

        lse_currency = await asyncio.to_thread(_lse_quote_currencies)
        lse_unknown = {t for t, cur in lse_currency.items() if not cur}
        price_divisor = {
            t: (100.0 if cur == "GBp" else 1.0)
            for t, cur in lse_currency.items() if cur
        }
        for pid in [p for p, info in tradable_positions.items() if info["ticker"] in lse_unknown]:
            # Pence oder Pfund ist offen. Divisor 1.0 bewertete einen Pence-Titel
            # 100-fach zu hoch (und der Zuschlag GBP waere geraten). Die Position
            # bleibt in diesem Lauf ohne Kurs; das Ergebnis wird nur kurz gecacht.
            logger.warning(
                "History: quote currency unknown for %s, position left unpriced",
                tradable_positions[pid]["ticker"],
            )
            del tradable_positions[pid]
        for info in tradable_positions.values():
            cur = lse_currency.get(info["ticker"])
            if cur:
                # Preis liegt nach ÷divisor in Pfund → FX ueber die echte
                # Quote-Waehrung (GBP bei Pence), nicht ueber pos.currency.
                info["currency"] = "GBP" if cur == "GBp" else cur

    # Collect all tickers + FX pairs needed
    tickers_needed = set()
    fx_pairs_needed = set()
    for info in tradable_positions.values():
        tickers_needed.add(info["ticker"])
        if info["currency"] != "CHF":
            fx_pairs_needed.add(f"{info['currency']}CHF=X")

    # FX-Paare für Fremdwährungs-Cash/Vorsorge (H1: saldo × Tages-FX)
    if not liquid:
        for pos in positions.values():
            if (
                pos.is_active
                and pos.type in (AssetType.cash, AssetType.pension)
                and pos.currency and pos.currency != "CHF"
            ):
                fx_pairs_needed.add(f"{pos.currency}CHF=X")

    # Benchmark in CHF: die Portfolio-Reihe ist CHF, ein Overlay/Delta gegen
    # eine Fremdwaehrungs-Reihe mischt zwei Waehrungen (Chart "vs. S&P 500",
    # summary.benchmark_return_pct und darauf aufbauend Information Ratio +
    # Tracking Error in risk_metrics_service). Spiegelt benchmark_service —
    # dort steckt der belegte Prod-Fall (Vorzeichen-Kipp) im Docstring.
    benchmark_currency: str | None = None
    if benchmark:
        tickers_needed.add(benchmark)
        from services.benchmark_service import benchmark_quote_currency
        # yf_to_thread: der Abruf wartet bei kaltem Cache am Ticker-Lock.
        benchmark_currency = await yf_to_thread(benchmark_quote_currency, benchmark)
        if benchmark_currency is None:
            logger.warning(
                "Benchmark %s: Notierungswaehrung unbekannt — Overlay entfaellt "
                "(statt einer waehrungsgemischten Reihe)", benchmark,
            )
        elif benchmark_currency != "CHF":
            fx_ccy = "GBP" if benchmark_currency == "GBp" else benchmark_currency
            fx_pairs_needed.add(f"{fx_ccy}CHF=X")

    # 5. Batch download historical prices
    all_tickers = list(tickers_needed | fx_pairs_needed)
    if not all_tickers and not any_priced_position:
        return _leeres_ergebnis()

    # Preis-Fenster am angefragten Zeitraum ausrichten: ~14 Tage Warm-up vor
    # start_date reichen für den last-known-Forward-Fill (Wochenenden/Feiertage).
    # Die Holdings-Rekonstruktion nutzt weiterhin ALLE Transaktionen seit
    # Inception — nur der Preis-Download hing unnötig an der ersten Txn
    # (Review 2026-07-02, M23: 1M-Chart lud sonst die komplette Historie).
    dl_start = start_date - timedelta(days=14)

    # Ohne Ticker (keine kursbewertete Position mit Bestand im Fenster, kein
    # Benchmark) entfaellt der Download; die Reihe besteht dann aus den Salden.
    price_data = None
    if all_tickers:
        if not await _acquire_download_slot():
            logger.warning(
                "History: no download slot within %.0fs for user %s, returning empty result",
                _DOWNLOAD_SLOT_WAIT_SECONDS, user_id,
            )
            return _leeres_ergebnis()
        try:
            price_data = await asyncio.to_thread(
                yf_download,
                all_tickers,
                start=dl_start.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                auto_adjust=True,
            )
        except Exception as e:
            logger.error(f"yfinance download failed: {e}")
            return _leeres_ergebnis()
        finally:
            _YF_DOWNLOAD_SLOTS.release()

    # Reihenaufbau und Tages-Replay rechnen Tage x Positionen und laufen deshalb
    # in einem Thread (K007); beide sind reine Funktionen ohne DB-Zugriff.
    _price_series = await asyncio.to_thread(
        _build_price_series, price_data, all_tickers, price_divisor
    )
    if _price_series is None:
        return _leeres_ergebnis()

    # Ticker ganz ohne Bars im Download-Fenster (delisted, Trading-Halt länger
    # als der 14d-Warm-up): letzten bekannten Kurs aus dem DB-Preiscache
    # seeden — sonst fällt eine gehaltene Position still auf 0 und verschiebt
    # die ganze Kurve (Review 2026-07-02, Follow-up zu M23; der frühere
    # Inception-weite Download lieferte den letzten Handelskurs implizit).
    fx_rates = await asyncio.to_thread(get_fx_rates_batch)

    seed_prices: dict[str, float] = {}
    missing_tickers = [t for t in tickers_needed if not _price_series.get(t)]
    if missing_tickers:
        from services.cache_service import get_cached_prices_batch_sync
        crypto_keys = _crypto_seed_keys(tradable_positions, missing_tickers)
        db_prices = await asyncio.to_thread(
            get_cached_prices_batch_sync,
            missing_tickers + sorted(set(crypto_keys.values())),
            3650,
        ) or {}
        usd_chf = fx_rates.get("USD")
        for t in missing_tickers:
            # Krypto: der letzte CoinGecko-Kurs liegt unter «CG:<coingecko_id>»
            # in CHF. Die Historie fuehrt Krypto in USD, deshalb durch USDCHF.
            cg_row = db_prices.get(crypto_keys[t]) if t in crypto_keys else None
            if cg_row and cg_row.get("price") and usd_chf:
                seed_prices[t] = float(cg_row["price"]) / usd_chf
                logger.info(
                    f"History: seeded {t} from CoinGecko price cache (no bars in download window)"
                )
                continue
            row = db_prices.get(t)
            if row and row.get("price"):
                seed_prices[t] = float(row["price"])
                logger.info(
                    f"History: seeded {t} from DB price cache (no bars in download window)"
                )

    result_data = await asyncio.to_thread(
        _replay_history,
        start_date=start_date,
        end_date=end_date,
        price_series=_price_series,
        seed_prices=seed_prices,
        seeded_holdings=seeded_holdings,
        holdings_changes=holdings_changes,
        static_positions=static_positions,
        static_fx_positions=static_fx_positions,
        positions={
            pid: SimpleNamespace(
                type=pos.type, currency=pos.currency, cost_basis_chf=pos.cost_basis_chf,
            )
            for pid, pos in positions.items()
        },
        tradable_positions=tradable_positions,
        fx_rates=fx_rates,
        benchmark=benchmark,
        benchmark_currency=benchmark_currency,
        liquid=liquid,
        downsample=downsample,
    )

    degraded = bool(lse_unknown) or (
        bool(tickers_needed) and not any(_price_series.get(t) for t in tickers_needed)
    )
    cache.set(cache_key, result_data, DEGRADED_CACHE_TTL if degraded else CACHE_TTL)
    return result_data


def _crypto_seed_keys(tradable_positions: dict[str, dict], tickers: list[str]) -> dict[str, str]:
    """``{Yahoo-Ticker: price_cache-Schluessel}`` fuer Ticker reiner Krypto-Positionen.

    Der Worker legt CoinGecko-Kurse unter «CG:<coingecko_id>» ab, nie unter dem
    Ticker der Position (K019). Ein Ticker, den auch eine Nicht-Krypto-Position
    oder ein zweiter Coin nutzt, bleibt beim Yahoo-Schluessel: der Seed gilt je
    Ticker und waere fuer die andere Position falsch.
    """
    ids_by_ticker: dict[str, set] = defaultdict(set)
    for info in tradable_positions.values():
        ids_by_ticker[info["ticker"]].add(info.get("coingecko_id"))
    from services.cache_service import crypto_price_key
    keys: dict[str, str] = {}
    for ticker in tickers:
        ids = ids_by_ticker.get(ticker, set())
        if len(ids) == 1 and None not in ids:
            keys[ticker] = crypto_price_key(next(iter(ids)))
    return keys


def _replay_history(
    *,
    start_date: date,
    end_date: date,
    price_series: dict[str, list[tuple[str, float]]],
    seed_prices: dict[str, float],
    seeded_holdings: dict[str, float],
    holdings_changes: dict,
    static_positions: dict[str, float],
    static_fx_positions: dict[str, tuple[float, str]],
    positions: dict,
    tradable_positions: dict[str, dict],
    fx_rates: dict[str, float],
    benchmark: str,
    benchmark_currency: str | None,
    liquid: bool,
    downsample: bool,
) -> dict:
    """Tages-Replay der Historie: Wert, cash-flow-bereinigter Index, Benchmark.

    Reine Funktion ohne DB- und Netzzugriff; laeuft ueber ``asyncio.to_thread``,
    weil sie Tage x Positionen rechnet und sonst den Event-Loop blockiert
    (K007). ``positions`` traegt nur ``type``, ``currency`` und
    ``cost_basis_chf`` (Kopien, keine ORM-Objekte).
    """
    _price_series = price_series
    # Direct O(1) lookups instead of scanning the sorted list above
    _price_by_date: dict[str, dict[str, float]] = {}
    for ticker, entries in _price_series.items():
        _price_by_date[ticker] = {d: p for d, p in entries}

    # Track last known price per ticker for forward-fill
    _last_known: dict[str, float] = {}

    def get_close(ticker: str, dt_str: str):
        """O(1) lookup with forward-fill from last known price."""
        price = _price_by_date.get(ticker, {}).get(dt_str)
        if price is not None:
            _last_known[ticker] = price
            return price
        return _last_known.get(ticker)

    # Warm up last-known prices from data before start_date
    for ticker, entries in _price_series.items():
        for d, p in entries:
            if d >= start_date.isoformat():
                break
            _last_known[ticker] = p

    # Ticker ohne Bars im Download-Fenster: letzter bekannter Kurs aus dem
    # DB-Preiscache (vom Aufrufer geladen).
    for t, price in seed_prices.items():
        if t not in _last_known:
            _last_known[t] = price

    # 6. Build daily portfolio values
    current_holdings = defaultdict(float)
    # Fallback-Seed: Edelmetall-Positionen ohne (datierte) Item-Historie ab Reihenbeginn
    # halten (siehe 2b) — markt-bepreist via tradable_positions, aber ohne purchase_date-
    # Anker. Der Normalfall laeuft ueber synthetische holdings_changes (purchase_date).
    for pid, shares in seeded_holdings.items():
        current_holdings[pid] = shares

    # Apply all transactions before start_date
    sorted_change_dates = sorted(holdings_changes.keys())
    for d in sorted_change_dates:
        if d >= start_date:
            break
        for pid, delta in holdings_changes[d]:
            current_holdings[pid] += delta

    def _cash_fx(ccy: str, dt_str: str) -> float:
        fx_price = get_close(f"{ccy}CHF=X", dt_str)
        return fx_price if fx_price else fx_rates.get(ccy, 1.0)

    def calc_portfolio_value(dt_str):
        value = 0.0
        has_price = False
        # Static positions
        for pid, val in static_positions.items():
            value += val
            has_price = True
        # Fremdwährungs-Cash/Vorsorge: saldo × Tages-FX (Review 2026-07-02, H1)
        for pid, (saldo, ccy) in static_fx_positions.items():
            value += saldo * _cash_fx(ccy, dt_str)
            has_price = True
        # Dynamic positions
        for pid, shares in current_holdings.items():
            if shares <= 0:
                continue
            pos = positions.get(pid)
            if not pos:
                continue
            if pos.type in (AssetType.private_equity, AssetType.real_estate):
                continue  # PE + Immobilien komplett aus der History excluded (Invariante #2)
            if pos.type in (AssetType.cash, AssetType.pension):
                if liquid:
                    continue  # liquid-only: Cash/Vorsorge raus
                fx = 1.0
                if pos.currency and pos.currency != "CHF":
                    fx = _cash_fx(pos.currency, dt_str)
                value += float(pos.cost_basis_chf) * fx
                has_price = True
                continue
            info = tradable_positions.get(pid)
            if not info:
                continue
            price = get_close(info["ticker"], dt_str)
            if price is not None:
                fx = 1.0
                if info["currency"] != "CHF":
                    fx_price = get_close(f"{info['currency']}CHF=X", dt_str)
                    fx = fx_price if fx_price else fx_rates.get(info["currency"], 1.0)
                value += shares * price * fx
                has_price = True
        return value, has_price

    # Generate daily data, tracking performance index (cashflow-adjusted)
    data_points = []
    current_date = start_date
    perf_index = 100.0
    prev_value = None

    while current_date <= end_date:
        dt_str = current_date.isoformat()

        # Value BEFORE applying today's cashflows
        value_before_cf, _ = calc_portfolio_value(dt_str)

        # Apply any holdings changes on this date
        if current_date in holdings_changes:
            for pid, delta in holdings_changes[current_date]:
                current_holdings[pid] += delta

        # Value AFTER applying today's cashflows
        portfolio_value, has_price = calc_portfolio_value(dt_str)

        if has_price:
            # Update performance index using sub-period return
            # value_before_cf > 0 schuetzt vor dem Index-Kollaps nach einer Luecke:
            # war der Bucket/das Portfolio zwischenzeitlich leer (alle Positionen
            # verkauft/umgehaengt -> Wert 0, keine Punkte aufgezeichnet) und kommt
            # spaeter zurueck, ist value_before_cf am Wiedereinstieg 0. Ohne den
            # Guard rechnete period_return = (0 - prev)/prev = -1 und der cash-flow-
            # bereinigte Index *= 0 kollabierte DAUERHAFT auf 0 (falsches -100% in
            # Drawdown/Rolling/Equity, auch nachdem wieder Positionen da sind). Der
            # Verkauf war ein Cashflow, kein Markt-Verlust -> bei leerem Vorlauf den
            # Index unveraendert weitertragen (keine Markt-Exposure = keine Rendite).
            if prev_value is not None and prev_value > 0 and value_before_cf > 0:
                # This excludes the effect of cashflows
                period_return = (value_before_cf - prev_value) / prev_value
                perf_index *= (1 + period_return)

            prev_value = portfolio_value

            point = {
                "date": dt_str,
                "value": round(portfolio_value, 2),
                "portfolio_indexed": round(perf_index, 2),
            }

            # Benchmark — in CHF (siehe oben). Ohne bekannte Waehrung oder
            # FX-Kurs bleibt der Punkt ohne Benchmark: dann fehlt das Overlay
            # sichtbar, statt still in Fremdwaehrung danebenzustehen.
            if benchmark and benchmark_currency is not None:
                bv = get_close(benchmark, dt_str)
                if bv is not None:
                    if benchmark_currency == "GBp":
                        bv /= 100
                    if benchmark_currency == "CHF":
                        point["benchmark"] = round(bv, 2)
                    else:
                        fx_ccy = "GBP" if benchmark_currency == "GBp" else benchmark_currency
                        fx = get_close(f"{fx_ccy}CHF=X", dt_str)
                        if fx:
                            point["benchmark"] = round(bv * fx, 2)

            data_points.append(point)

        current_date += timedelta(days=1)

    # 7. Normalize benchmark to indexed (start = 100)
    if data_points:
        start_bench = data_points[0].get("benchmark")
        for p in data_points:
            if start_bench and "benchmark" in p:
                p["benchmark_indexed"] = round(p["benchmark"] / start_bench * 100, 2)

    # 8. Downsample if range > 1 year (übersprungen bei raw=true)
    days_range = (end_date - start_date).days
    downsampled = False
    if downsample and days_range > 365 and len(data_points) > 260:
        sampled = [data_points[0]]
        for i in range(1, len(data_points)):
            prev_d = date.fromisoformat(sampled[-1]["date"])
            curr_d = date.fromisoformat(data_points[i]["date"])
            if (curr_d - prev_d).days >= 5:
                sampled.append(data_points[i])
        if sampled[-1]["date"] != data_points[-1]["date"]:
            sampled.append(data_points[-1])

        # Extrema erhalten. Ein 5-Tage-Raster trifft Hoch- und Tiefpunkt nur
        # zufaellig, und der Fehler verteilt sich unguenstig: die HOEHE ueberlebt
        # (die Nachbarpunkte liegen nah), das DATUM nicht. Prod-Beleg: das
        # Allzeithoch vom 2025-08-13 (CHF 244'308.78) faellt zwischen die
        # Stuetzpunkte 08-12 und 08-17; gemeldet wurde der Peak als 2025-10-06 —
        # 54 Tage daneben bei 0.01 % Wertdifferenz. Wer einen Drawdown-Peak
        # datiert, liest damit ein falsches Datum, ohne dass die Zahl daneben
        # auffaellig waere.
        traeger = [k for k in ("value", "portfolio_indexed") if k in data_points[0]]
        behalten = {p["date"] for p in sampled}
        zusatz = []
        for key in traeger:
            kandidaten = [p for p in data_points if p.get(key) is not None]
            if not kandidaten:
                continue
            for p in (min(kandidaten, key=lambda x: x[key]),
                      max(kandidaten, key=lambda x: x[key])):
                if p["date"] not in behalten:
                    behalten.add(p["date"])
                    zusatz.append(p)
        if zusatz:
            sampled = sorted(sampled + zusatz, key=lambda p: p["date"])

        data_points = sampled
        downsampled = True

    # 9. Summary
    summary = {}
    if len(data_points) >= 2:
        summary["start_value"] = data_points[0]["value"]
        summary["end_value"] = data_points[-1]["value"]
        summary["return_pct"] = round(data_points[-1]["portfolio_indexed"] - 100, 2)
        if "benchmark_indexed" in data_points[-1]:
            summary["benchmark_return_pct"] = round(data_points[-1]["benchmark_indexed"] - 100, 2)

    # ``downsampled`` sagt dem Konsumenten, dass die Reihe ausgeduennt ist —
    # sonst ist das aus den Daten nur zu erraten. Wer damit eine Quartals- oder
    # Monatsgrenze ausrechnet, trifft den Stichtag um bis zu vier Tage: fuer die
    # Q1-Grenze ergab das auf Prod -6.03 % statt -4.24 %. Randgenaue Rechnungen
    # gehoeren auf ``raw=true`` oder einen kuerzeren Zeitraum.
    result_data = {
        "data": data_points,
        "summary": summary,
        "downsampled": downsampled,
        "sample_interval_days": 5 if downsampled else 1,
    }
    return result_data
