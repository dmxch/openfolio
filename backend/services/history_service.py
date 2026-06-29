"""Portfolio history reconstruction — daily portfolio value + benchmark."""
import logging
import uuid
from collections import defaultdict
from datetime import date, timedelta

import yfinance as yf
from yf_patch import yf_download
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType
from services import cache
from services.utils import get_fx_rates_batch

logger = logging.getLogger(__name__)

CACHE_TTL = 900  # 15 min

from constants.cashflow import INFLOW_TYPES, OUTFLOW_TYPES


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
    cache_key = (
        f"portfolio_history:{user_id}:{start_date}:{end_date}:{benchmark}"
        f":ds{int(downsample)}:lq{int(liquid)}:bk{bucket_id or ''}"
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

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
        return {"data": [], "summary": {}}
    txn_query = select(Transaction).order_by(Transaction.date.asc())
    if user_id is not None:
        txn_query = txn_query.where(Transaction.user_id == user_id)
    result = await db.execute(txn_query)
    all_txns = result.scalars().all()

    # raw=true (downsample=False): Serie an echter Inception verankern statt am
    # angefragten Start (period=all → 2000). Statische Cash/Vorsorge-Positionen
    # würden sonst mit konstantem cost_basis rückwärts bis zum Start-Datum emittiert
    # (Index auf 100 festgenagelt) — ein synthetisches Pre-Inception-Plateau, das
    # empirische Auswertungen verzerrt. Wir kürzen nur nach vorne, erzeugen nichts.
    if not downsample and all_txns:
        first_txn_date = all_txns[0].date  # query ist nach date.asc() sortiert
        if start_date < first_txn_date <= end_date:
            start_date = first_txn_date

    # 3. Build holdings timeline
    holdings_changes = defaultdict(list)  # date -> [(position_id, share_delta)]
    positions_with_txns = set()
    # Track cashflows per date for performance-adjusted curve
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

        # Track external cashflows for performance adjustment
        if txn.type in INFLOW_TYPES:
            cashflows_by_date[txn.date] += float(txn.total_chf)
        elif txn.type in OUTFLOW_TYPES:
            cashflows_by_date[txn.date] -= float(txn.total_chf)

    # Identify positions with no transactions (cash, pension, manually added)
    static_positions = {}
    for pid, pos in positions.items():
        if pid not in positions_with_txns and pos.is_active and float(pos.cost_basis_chf) > 0:
            if pos.type in (AssetType.private_equity, AssetType.real_estate):
                continue  # PE + Immobilien komplett aus der History excluded (Invariante #2)
            if liquid and pos.type in (AssetType.cash, AssetType.pension):
                continue  # liquid-only: Cash/Vorsorge raus
            static_positions[pid] = float(pos.cost_basis_chf)

    if not holdings_changes and not static_positions:
        return {"data": [], "summary": {}}

    # 4. Determine tickers we need prices for
    tradable_positions = {}
    for pid, pos in positions.items():
        if pos.type in (AssetType.cash, AssetType.pension, AssetType.private_equity, AssetType.real_estate):
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
        }

    # 4b. LSE-Pence-Korrektur: yfinance quotiert viele .L-Titel in Pence (GBp),
    # nicht Pfund. Ohne ÷100 ist die historische Bewertung 100x zu hoch — derselbe
    # GBX-Bug, der im Live-/Snapshot-Pfad laengst gefixt ist (cache_service.
    # _pence_divisor), hier aber fehlte und /performance/history fuer Pence-.L-
    # Haltefenster auf das ~100-fache aufblies. Divisor + echte Quote-Waehrung
    # kommen aus denselben cache_service-Helpern wie der Live-Pfad; die oft falsche
    # pos.currency (.L kann USD/GBP/GBp sein) wird fuer .L-Ticker ueberschrieben.
    import asyncio
    from services.cache_service import _pence_divisor, _resolved_currency

    lse_tickers = {
        info["ticker"] for info in tradable_positions.values()
        if info["ticker"].endswith(".L")
    }
    price_divisor: dict[str, float] = {}
    if lse_tickers:
        lse_meta = await asyncio.to_thread(
            lambda: {t: (_pence_divisor(t), _resolved_currency(t)) for t in lse_tickers}
        )
        price_divisor = {t: meta[0] for t, meta in lse_meta.items()}
        for info in tradable_positions.values():
            if info["ticker"] in lse_meta:
                # Preis liegt nach ÷divisor in Pfund → FX ueber die echte
                # Quote-Waehrung (GBP bei Pence), nicht ueber pos.currency.
                info["currency"] = lse_meta[info["ticker"]][1]

    # Collect all tickers + FX pairs needed
    tickers_needed = set()
    fx_pairs_needed = set()
    for info in tradable_positions.values():
        tickers_needed.add(info["ticker"])
        if info["currency"] != "CHF":
            fx_pairs_needed.add(f"{info['currency']}CHF=X")

    if benchmark:
        tickers_needed.add(benchmark)

    # 5. Batch download historical prices
    all_tickers = list(tickers_needed | fx_pairs_needed)
    if not all_tickers:
        return {"data": [], "summary": {}}

    earliest_txn = min(holdings_changes.keys()) if holdings_changes else start_date
    dl_start = min(earliest_txn, start_date) - timedelta(days=5)

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
        return {"data": [], "summary": {}}

    # Handle single ticker case
    if len(all_tickers) == 1:
        single_ticker = all_tickers[0]
        if "Close" in price_data.columns:
            import pandas as pd
            close_df = price_data[["Close"]].copy()
            close_df.columns = pd.MultiIndex.from_tuples([("Close", single_ticker)])
        else:
            return {"data": [], "summary": {}}
    else:
        close_df = price_data["Close"] if "Close" in price_data.columns else price_data

    # Pre-build price lookup dict: ticker -> sorted list of (date_str, price)
    # and a last-known-price cache for O(1) lookup per day
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

    # Build dict[ticker][date_str] = price for direct O(1) lookups
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

    # 6. Build daily portfolio values
    current_holdings = defaultdict(float)
    fx_rates = await asyncio.to_thread(get_fx_rates_batch)

    # Apply all transactions before start_date
    sorted_change_dates = sorted(holdings_changes.keys())
    for d in sorted_change_dates:
        if d >= start_date:
            break
        for pid, delta in holdings_changes[d]:
            current_holdings[pid] += delta

    def calc_portfolio_value(dt_str):
        value = 0.0
        has_price = False
        # Static positions
        for pid, val in static_positions.items():
            value += val
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
                value += float(pos.cost_basis_chf)
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
    perf_index = 100.0  # Performance index starts at 100
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
            if prev_value is not None and prev_value > 0:
                # Return for this period = (value_before_cf - prev_value) / prev_value
                # This excludes the effect of cashflows
                period_return = (value_before_cf - prev_value) / prev_value
                perf_index *= (1 + period_return)

            prev_value = portfolio_value

            point = {
                "date": dt_str,
                "value": round(portfolio_value, 2),
                "portfolio_indexed": round(perf_index, 2),
            }

            # Benchmark
            if benchmark:
                bv = get_close(benchmark, dt_str)
                if bv is not None:
                    point["benchmark"] = round(bv, 2)

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
    if downsample and days_range > 365 and len(data_points) > 260:
        sampled = [data_points[0]]
        for i in range(1, len(data_points)):
            prev_d = date.fromisoformat(sampled[-1]["date"])
            curr_d = date.fromisoformat(data_points[i]["date"])
            if (curr_d - prev_d).days >= 5:
                sampled.append(data_points[i])
        if sampled[-1]["date"] != data_points[-1]["date"]:
            sampled.append(data_points[-1])
        data_points = sampled

    # 9. Summary
    summary = {}
    if len(data_points) >= 2:
        summary["start_value"] = data_points[0]["value"]
        summary["end_value"] = data_points[-1]["value"]
        summary["return_pct"] = round(data_points[-1]["portfolio_indexed"] - 100, 2)
        if "benchmark_indexed" in data_points[-1]:
            summary["benchmark_return_pct"] = round(data_points[-1]["benchmark_indexed"] - 100, 2)

    result_data = {"data": data_points, "summary": summary}
    cache.set(cache_key, result_data, CACHE_TTL)
    return result_data
