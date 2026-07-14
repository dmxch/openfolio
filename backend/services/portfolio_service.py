import asyncio
import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import Position, AssetType
from models.transaction import Transaction
from models.etf_sector_weight import EtfSectorWeight
from services.price_service import (
    get_stock_price,
    get_stock_prices_bulk,
    get_crypto_price_chf,
    get_gold_price_chf,
    get_metal_price_chf,
)
from services.utils import get_fx_rates_batch, compute_moving_averages, compute_mansfield_rs, prefetch_close_series
from services.sector_mapping import MULTI_SECTOR_INDUSTRIES

logger = logging.getLogger(__name__)

SKIP_TICKERS = {"VIAC_3A", "GC=F"}


def _get_ma_status(ticker: str) -> dict:
    """Return MA data + status badge for a ticker."""
    if ticker.startswith("CASH_") or ticker in SKIP_TICKERS:
        return {"ma_status": None, "ma_detail": None}

    try:
        mas = compute_moving_averages(ticker, [50, 150, 200])
        current = mas.get("current")
        ma50 = mas.get("ma50")
        ma150 = mas.get("ma150")
        ma200 = mas.get("ma200")

        if current is None or ma200 is None:
            return {"ma_status": None, "ma_detail": None}

        above_50 = current > ma50 if ma50 else None
        above_150 = current > ma150 if ma150 else None
        above_200 = current > ma200 if ma200 else None

        checks_passed = sum(1 for x in [above_50, above_150, above_200] if x is True)
        checks_total = sum(1 for x in [above_50, above_150, above_200] if x is not None)

        if checks_total == 0:
            status = None
        elif checks_passed == checks_total:
            status = "GESUND"
        elif checks_passed >= checks_total / 2:
            status = "WARNUNG"
        else:
            status = "KRITISCH"

        return {
            "ma_status": status,
            "ma_detail": {
                "above_ma50": above_50,
                "above_ma150": above_150,
                "above_ma200": above_200,
            },
        }
    except Exception:
        logger.debug(f"MA status calculation failed for {ticker}", exc_info=True)
        return {"ma_status": None, "ma_detail": None}


def _get_mrs(ticker: str) -> float | None:
    if ticker.startswith("CASH_") or ticker in SKIP_TICKERS:
        return None

    try:
        return compute_mansfield_rs(ticker)
    except Exception:
        logger.debug(f"MRS lookup failed for {ticker}", exc_info=True)
        return None


async def get_portfolio_summary(db: AsyncSession, user_id: uuid.UUID | None = None) -> dict:

    query = select(Position).where(Position.is_active == True)
    if user_id is not None:
        query = query.where(Position.user_id == user_id)
    result = await db.execute(query)
    positions = result.scalars().all()

    # Get first buy date per position (SQL MIN — single query)
    from sqlalchemy import func as sqlfunc
    pos_ids = [p.id for p in positions]
    buy_date_query = (
        select(Transaction.position_id, sqlfunc.min(Transaction.date))
        .where(Transaction.type == "buy")
    )
    if pos_ids:
        buy_date_query = buy_date_query.where(Transaction.position_id.in_(pos_ids))
    buy_date_query = buy_date_query.group_by(Transaction.position_id)
    txn_result = await db.execute(buy_date_query)
    first_buy_dates: dict[str, date] = {str(pid): d for pid, d in txn_result}

    # Sum fees per position (for transparency note)
    from sqlalchemy import func
    pos_ids = [p.id for p in positions]
    fees_result = await db.execute(
        select(Transaction.position_id, func.sum(Transaction.fees_chf))
        .where(Transaction.position_id.in_(pos_ids))
        .group_by(Transaction.position_id)
    ) if pos_ids else None
    fees_by_pos: dict[str, float] = {}
    if fees_result:
        for pos_id, total_fees in fees_result:
            fees_by_pos[str(pos_id)] = float(total_fees or 0)

    # Load ETF sector weights (user-scoped, filtered to active position tickers)
    active_tickers = [p.ticker for p in positions]
    etf_query = select(EtfSectorWeight)
    if user_id is not None:
        etf_query = etf_query.where(EtfSectorWeight.user_id == user_id)
    if active_tickers:
        etf_query = etf_query.where(EtfSectorWeight.ticker.in_(active_tickers))
    etf_weights_result = await db.execute(etf_query)
    all_etf_weights = etf_weights_result.scalars().all()
    etf_sector_map: dict[str, list[dict]] = {}
    for w in all_etf_weights:
        etf_sector_map.setdefault(w.ticker, []).append({"sector": w.sector, "weight_pct": float(w.weight_pct)})

    total_invested = 0.0
    total_market_value = 0.0
    allocations_type = {}
    allocations_style = {}
    allocations_sector = {}
    allocations_currency = {}
    position_list = []

    # Pre-compute tradable tickers before parallel fetch
    tradable_tickers = []
    # MRS/MA sind Aktien-Kennzahlen: sie messen relative Staerke gegen ^GSPC bzw.
    # einen Aufwaertstrend. Auf einen Anleihen-ETF angewandt liefern sie strukturell
    # "KRITISCH" und stark negative RS — kein Signal, sondern ein Kategorienfehler.
    # Anleihen brauchen den Kurs (tradable_tickers), aber keine Aktien-Signale.
    signal_tickers = []
    for pos in positions:
        if pos.type.value in ("real_estate", "private_equity"):
            continue  # PE + Immobilien nicht im liquiden Summary (Invariante #2)
        if float(pos.shares) <= 0 and pos.type.value not in ("cash", "pension"):
            continue
        yf_ticker = pos.yfinance_ticker or pos.ticker
        if not yf_ticker.startswith("CASH_") and yf_ticker not in SKIP_TICKERS:
            tradable_tickers.append(yf_ticker)
            if pos.type != AssetType.bond:
                signal_tickers.append(yf_ticker)

    # Fetch FX rates and prefetch close series in parallel (independent blocking calls)
    ma_results = {}
    mrs_results = {}
    if tradable_tickers:
        fx_rates, _ = await asyncio.gather(
            asyncio.to_thread(get_fx_rates_batch),
            asyncio.to_thread(prefetch_close_series, tradable_tickers + ["^GSPC"]),
        )
    else:
        fx_rates = await asyncio.to_thread(get_fx_rates_batch)

    # Run MA and MRS computations in a thread (blocking yfinance/pandas ops).
    # Anleihen bleiben aussen vor — der Lookup unten faellt fuer sie auf None
    # zurueck (kein ma_status/mansfield_rs im Payload).
    if signal_tickers:
        def _compute_all_ma_mrs():
            ma = {t: _get_ma_status(t) for t in signal_tickers}
            mrs = {t: _get_mrs(t) for t in signal_tickers}
            return ma, mrs

        ma_results, mrs_results = await asyncio.to_thread(_compute_all_ma_mrs)

    # Batch-Preis-Resolution: alle Ticker in EINER Sync-DB-Session aufloesen
    # statt 1-2 Sync-Sessions pro Position auf dem Event-Loop (Review
    # 2026-07-02, M27). _compute_market_value nutzt get_stock_price nur noch
    # als Einzel-Fallback fuer Batch-Misses; Werte sind identisch (gleiche
    # Redis-first/DB-5d-Semantik wie der Event-Loop-Pfad von get_stock_price).
    price_map: dict[str, dict] = {}
    if tradable_tickers:
        price_map = await asyncio.to_thread(get_stock_prices_bulk, tradable_tickers)

    for pos in positions:
        # PE + Immobilien gehoeren nicht ins liquide Portfolio-Summary (Invariante #2) —
        # eigene Widgets (ImmobilienWidget/PrivateEquityWidget). In der Praxis shares=0;
        # der explizite Guard macht den Ausschluss robust (Multi-User).
        if pos.type.value in ("real_estate", "private_equity"):
            continue
        # Skip fully sold positions (shares = 0) from active portfolio view
        if float(pos.shares) <= 0 and pos.type.value not in ("cash", "pension"):
            continue

        market_value_chf, current_price, price_currency, stale_info = _compute_market_value(pos, fx_rates, price_map)
        total_market_value += market_value_chf

        # Cash/Pension have no PnL; their raw cost_basis_chf field stores the
        # balance in position currency, not CHF. Use the FX-converted market
        # value as invested so totals stay in CHF and PnL is zero.
        if pos.type in (AssetType.cash, AssetType.pension):
            invested = market_value_chf
        else:
            invested = float(pos.cost_basis_chf)
        total_invested += invested

        pnl = market_value_chf - invested
        pnl_pct = ((market_value_chf / invested) - 1) * 100 if invested > 0 else 0

        # FX-vs-Lokal-Renditezerlegung (additiv, display-only; aendert cost_basis
        # /pnl NICHT). Trennt Kursbewegung (lokal) von Waehrungsbewegung (FX) auf
        # der EX-Gebuehren-Kostenbasis. Identitaet: (1+lokal)*(1+fx) ==
        # market_value_chf / cost_basis_chf_at_fx. Nur wo native/at-fx-Kostenbasis
        # aus dem Txn-Stream vorliegt UND die Position in ihrer Nativwaehrung live
        # bepreist ist (Stocks/ETFs, price_currency == pos.currency); Crypto/Gold
        # (CHF-Preis) und txn-lose Positionen bleiben None. CHF-Positionen: reine
        # Kursrendite, FX-Effekt = 0.
        local_return_pct = fx_return_pct = fx_cross_pct = None
        cbn = pos.cost_basis_native
        cbfx = pos.cost_basis_chf_at_fx
        if (
            pos.type not in (AssetType.cash, AssetType.pension)
            and cbn is not None and cbfx is not None
            and float(cbn) > 0 and float(cbfx) > 0 and current_price is not None
        ):
            cbn = float(cbn)
            cbfx = float(cbfx)
            if pos.currency == "CHF":
                local_return_pct = round((market_value_chf / cbfx - 1) * 100, 2)
                fx_return_pct = 0.0
                fx_cross_pct = 0.0
            elif price_currency == pos.currency:
                native_value_now = float(pos.shares) * current_price
                fx_purchase = cbfx / cbn
                if native_value_now > 0 and fx_purchase > 0:
                    fx_now_eff = market_value_chf / native_value_now
                    loc = native_value_now / cbn - 1
                    fxr = fx_now_eff / fx_purchase - 1
                    local_return_pct = round(loc * 100, 2)
                    fx_return_pct = round(fxr * 100, 2)
                    fx_cross_pct = round(loc * fxr * 100, 2)

        # Geldmarkt-/T-Bill-ETFs (count_as_cash) zaehlen in der Anlageklassen-
        # Allokation als Cash, bleiben aber regulaer bepreist (Performance/PnL
        # unveraendert). Das Flag ist ETF-exklusiv: Anleihen sind kein Cash und
        # behalten ihren eigenen Topf, auch wenn count_as_cash an einer
        # bond-Position gesetzt wurde — sonst bliebe der Anleihen-Block leer.
        type_key = (
            "cash"
            if getattr(pos, "count_as_cash", False) and pos.type != AssetType.bond
            else pos.type.value
        )
        allocations_type[type_key] = allocations_type.get(type_key, 0) + market_value_chf
        style_key = pos.style.value if pos.style else "Nicht zugewiesen"
        allocations_style[style_key] = allocations_style.get(style_key, 0) + market_value_chf
        # Sector allocation: Multi-Sector positions distribute by ETF sector weights
        is_multi_sector = pos.industry in MULTI_SECTOR_INDUSTRIES
        etf_weights = etf_sector_map.get(pos.ticker) if is_multi_sector else None
        if is_multi_sector and etf_weights:
            for sw in etf_weights:
                s_key = sw["sector"]
                allocations_sector[s_key] = allocations_sector.get(s_key, 0) + market_value_chf * sw["weight_pct"] / 100.0
        elif is_multi_sector and not etf_weights:
            allocations_sector["Multi-Sector (unverteilt)"] = allocations_sector.get("Multi-Sector (unverteilt)", 0) + market_value_chf
        else:
            sector_key = pos.sector or "Nicht zugewiesen"
            allocations_sector[sector_key] = allocations_sector.get(sector_key, 0) + market_value_chf
        ccy_key = pos.currency
        allocations_currency[ccy_key] = allocations_currency.get(ccy_key, 0) + market_value_chf

        yf_ticker = pos.yfinance_ticker or pos.ticker
        ma_data = ma_results.get(yf_ticker, {"ma_status": None, "ma_detail": None})
        mrs = mrs_results.get(yf_ticker)

        buy_date = first_buy_dates.get(str(pos.id))

        pos_data = {
            "id": str(pos.id),
            "ticker": pos.ticker,
            "name": pos.name,
            "type": pos.type.value,
            "sector": pos.sector,
            "industry": pos.industry,
            "currency": pos.currency,
            "shares": float(pos.shares),
            "cost_basis_chf": float(pos.cost_basis_chf),
            "market_value_chf": round(market_value_chf, 2),
            "current_price": round(current_price, 2) if current_price is not None else None,
            "price_currency": price_currency,
            "pnl_chf": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "local_return_pct": local_return_pct,
            "fx_return_pct": fx_return_pct,
            "fx_cross_pct": fx_cross_pct,
            "bucket_id": str(pos.bucket_id) if pos.bucket_id else None,
            "risk_rules": pos.risk_rules,
            "style": pos.style.value if pos.style else None,
            "weight_pct": 0,
            "mansfield_rs": mrs,
            "ma_status": ma_data["ma_status"],
            "ma_detail": ma_data["ma_detail"],
            "buy_date": buy_date.isoformat() if buy_date else None,
            "stop_loss_price": float(pos.stop_loss_price) if pos.stop_loss_price is not None else None,
            "stop_loss_confirmed_at_broker": pos.stop_loss_confirmed_at_broker,
            "stop_loss_updated_at": pos.stop_loss_updated_at.isoformat() if pos.stop_loss_updated_at else None,
            "stop_loss_method": pos.stop_loss_method,
            "next_earnings_date": pos.next_earnings_date.isoformat() if pos.next_earnings_date else None,
            # Bond-ETFs sind ETF-Wrapper (Scope: boersengehandelte Fonds), tragen
            # aber type=bond. Ohne den bond-Zweig meldet ein importierter Bond-ETF
            # lautlos is_etf=false — import_service setzt das Feld nie, der
            # Typ-Zweig ist die einzige verlaessliche Quelle.
            "is_etf": getattr(pos, 'is_etf', False) or pos.type in (AssetType.etf, AssetType.bond),
            "count_as_cash": getattr(pos, "count_as_cash", False),
            "is_multi_sector": is_multi_sector,
            "has_sector_weights": bool(etf_weights) if is_multi_sector else None,
            "is_stale": False,
        }
        if stale_info:
            pos_data.update(stale_info)
        position_list.append(pos_data)

    for p in position_list:
        p["weight_pct"] = round(p["market_value_chf"] / total_market_value * 100, 2) if total_market_value > 0 else 0

    total_pnl = total_market_value - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    total_fees_chf = sum(fees_by_pos.values())

    return {
        "total_invested_chf": round(total_invested, 2),
        "total_market_value_chf": round(total_market_value, 2),
        "total_pnl_chf": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "total_fees_chf": round(total_fees_chf, 2),
        "positions": sorted(position_list, key=lambda x: x["market_value_chf"], reverse=True),
        "allocations": {
            "by_type": _to_allocation_list(allocations_type, total_market_value),
            "by_style": _to_allocation_list(allocations_style, total_market_value),
            "by_sector": _to_allocation_list(allocations_sector, total_market_value),
            "by_currency": _to_allocation_list(allocations_currency, total_market_value),
        },
        "fx_rates": fx_rates,
    }


def _compute_market_value(
    pos: Position, fx_rates: dict, price_map: dict[str, dict] | None = None
) -> tuple[float, float | None, str | None, dict]:
    """Returns (market_value_chf, current_price, price_currency, stale_info).

    price_map (optional): vorab per get_stock_prices_bulk aufgeloeste Preise
    (Review 2026-07-02, M27) — get_stock_price dient nur noch als
    Einzel-Fallback fuer Batch-Misses.
    """
    if pos.type == AssetType.cash or pos.type == AssetType.pension:
        # For cash/pension the balance is stored in `cost_basis_chf` but in the
        # position's own currency (legacy field naming). Convert to CHF via FX
        # so foreign-currency accounts show the correct CHF value.
        saldo = float(pos.cost_basis_chf)
        if pos.currency == "CHF":
            return saldo, None, None, {}
        fx = fx_rates.get(pos.currency)
        if fx is None:
            from services.cache_service import get_cached_price_sync
            cached = get_cached_price_sync(f"{pos.currency}CHF=X", fallback_days=30)
            if cached:
                fx = cached["price"]
                logger.warning(f"FX {pos.currency}: using stale rate {fx} for cash/pension {pos.ticker}")
            else:
                logger.error(f"FX {pos.currency}: NO RATE AVAILABLE for cash/pension {pos.ticker}")
                return saldo, None, None, {
                    "is_stale": True,
                    "stale_reason": f"Kein FX-Kurs für {pos.currency}",
                }
        return saldo * fx, None, None, {}

    if pos.type == AssetType.crypto and pos.coingecko_id:
        crypto = get_crypto_price_chf(pos.coingecko_id)
        if crypto:
            return float(pos.shares) * crypto["price"], crypto["price"], "CHF", {}

    if pos.gold_org:
        metal = get_metal_price_chf(pos.ticker, fx_rates)
        if metal:
            return float(pos.shares) * metal["price"], metal["price"], "CHF", {}
        # Cache-Miss: Worker-gepflegten DB-Preis verwenden. yfinance-Spot-Ticker
        # wie XAUCHF=X sind nicht verfuegbar — Fall-Through wuerde faelschlich als
        # stale markieren, obwohl der Worker positions.current_price frisch haelt.
        if pos.current_price:
            price = float(pos.current_price)
            return float(pos.shares) * price, price, "CHF", {}
        return float(pos.cost_basis_chf), None, None, {
            "is_stale": True,
            "stale_reason": "Edelmetall-Kurs nicht verfuegbar",
            "price_source": "cost_basis_fallback",
        }

    if pos.pricing_mode.value == "manual":
        price = float(pos.current_price) if pos.current_price else 0
        # Invariante #1: value_chf = shares × current_price × fx_rate — auch
        # fuer manuell bepreiste Positionen (Review 2026-07-02, M1). Vorher
        # wurde der Fremdwaehrungs-Preis als CHF gezaehlt (permanente
        # Live/Snapshot-Diskrepanz vs. _calc_position_value_chf).
        if pos.currency == "CHF":
            return float(pos.shares) * price, price, pos.currency, {}
        fx = fx_rates.get(pos.currency)
        if fx is None:
            from services.cache_service import get_cached_price_sync
            cached = get_cached_price_sync(f"{pos.currency}CHF=X", fallback_days=30)
            if cached:
                fx = cached["price"]
                logger.warning(f"FX {pos.currency}: using stale rate {fx} for manual position {pos.ticker}")
            else:
                logger.error(f"FX {pos.currency}: NO RATE AVAILABLE - manual position {pos.ticker} cannot be valued")
                return 0, price, pos.currency, {
                    "is_stale": True,
                    "stale_reason": f"Kein FX-Kurs für {pos.currency}",
                }
        return float(pos.shares) * price * fx, price, pos.currency, {}

    yf_ticker = pos.yfinance_ticker or pos.ticker
    price_data = (price_map or {}).get(yf_ticker)
    if price_data is None:
        price_data = get_stock_price(yf_ticker)
    if price_data:
        price = price_data["price"]
        # Always use the position's currency for FX conversion, not yfinance's
        fx = fx_rates.get(pos.currency)
        if fx is None:
            # Try stale DB rate (up to 30 days)
            from services.cache_service import get_cached_price_sync
            fx_ticker = f"{pos.currency}CHF=X"
            cached = get_cached_price_sync(fx_ticker, fallback_days=30)
            if cached:
                fx = cached["price"]
                logger.warning(f"FX {pos.currency}: using stale rate {fx} from cache")
            else:
                # Position cannot be valued
                logger.error(f"FX {pos.currency}: NO RATE AVAILABLE - position {pos.ticker} cannot be valued")
                return 0, price, pos.currency, {
                    "is_stale": True,
                    "stale_reason": f"Kein FX-Kurs für {pos.currency}",
                }
        return float(pos.shares) * price * fx, price, pos.currency, {}

    # No price available — fall back to cost_basis
    logger.warning(f"No price for {pos.ticker} — using cost_basis_chf as fallback")
    return float(pos.cost_basis_chf), None, None, {
        "is_stale": True,
        "stale_reason": "Kein aktueller Kurs verfügbar — Einstandswert wird angezeigt",
        "price_source": "cost_basis_fallback",
    }


def _to_allocation_list(alloc: dict, total: float) -> list[dict]:
    return [
        {"name": k, "value_chf": round(v, 2), "pct": round(v / total * 100, 2) if total > 0 else 0}
        for k, v in sorted(alloc.items(), key=lambda x: x[1], reverse=True)
    ]
