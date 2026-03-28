import asyncio
import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import Position, AssetType
from models.transaction import Transaction
from models.etf_sector_weight import EtfSectorWeight
from services.price_service import get_stock_price, get_crypto_price_chf, get_gold_price_chf
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

    fx_rates = await asyncio.to_thread(get_fx_rates_batch)
    total_invested = 0.0
    total_market_value = 0.0
    allocations_type = {}
    allocations_rk = {}
    allocations_style = {}
    allocations_sector = {}
    allocations_currency = {}
    allocations_cs = {}  # core/satellite
    position_list = []

    # Pre-compute MA status and MRS in parallel for all tradable positions
    tradable_tickers = []
    for pos in positions:
        if float(pos.shares) <= 0 and pos.type.value not in ("cash", "pension"):
            continue
        yf_ticker = pos.yfinance_ticker or pos.ticker
        if not yf_ticker.startswith("CASH_") and yf_ticker not in SKIP_TICKERS:
            tradable_tickers.append(yf_ticker)

    ma_results = {}
    mrs_results = {}
    if tradable_tickers:
        # Batch-download all close series before threading to avoid
        # yfinance thread-safety issues with concurrent yf.download calls
        await asyncio.to_thread(prefetch_close_series, tradable_tickers + ["^GSPC"])

        # Run MA and MRS computations in a thread (blocking yfinance/pandas ops)
        def _compute_all_ma_mrs():
            ma = {t: _get_ma_status(t) for t in tradable_tickers}
            mrs = {t: _get_mrs(t) for t in tradable_tickers}
            return ma, mrs

        ma_results, mrs_results = await asyncio.to_thread(_compute_all_ma_mrs)

    for pos in positions:
        # Skip fully sold positions (shares = 0) from active portfolio view
        if float(pos.shares) <= 0 and pos.type.value not in ("cash", "pension"):
            continue

        invested = float(pos.cost_basis_chf)
        total_invested += invested

        market_value_chf, current_price, price_currency, stale_info = _compute_market_value(pos, fx_rates)
        total_market_value += market_value_chf

        pnl = market_value_chf - invested
        pnl_pct = ((market_value_chf / invested) - 1) * 100 if invested > 0 else 0

        type_key = pos.type.value
        allocations_type[type_key] = allocations_type.get(type_key, 0) + market_value_chf
        rk_key = f"RK{pos.risk_class}"
        allocations_rk[rk_key] = allocations_rk.get(rk_key, 0) + market_value_chf
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
        # Core/Satellite: only tradable types (stock, etf)
        if pos.type.value in ("stock", "etf"):
            cs_key = pos.position_type or "unassigned"
            allocations_cs[cs_key] = allocations_cs.get(cs_key, 0) + market_value_chf

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
            "cost_basis_chf": invested,
            "market_value_chf": round(market_value_chf, 2),
            "current_price": round(current_price, 2) if current_price is not None else None,
            "price_currency": price_currency,
            "pnl_chf": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "risk_class": pos.risk_class,
            "position_type": pos.position_type,
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
            "is_etf": getattr(pos, 'is_etf', False) or pos.type == AssetType.etf,
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
            "by_risk_class": _to_allocation_list(allocations_rk, total_market_value),
            "by_style": _to_allocation_list(allocations_style, total_market_value),
            "by_sector": _to_allocation_list(allocations_sector, total_market_value),
            "by_currency": _to_allocation_list(allocations_currency, total_market_value),
            "by_core_satellite": _to_allocation_list(allocations_cs, sum(allocations_cs.values())),
        },
        "fx_rates": fx_rates,
    }


def _compute_market_value(pos: Position, fx_rates: dict) -> tuple[float, float | None, str | None, dict]:
    """Returns (market_value_chf, current_price, price_currency, stale_info)."""
    if pos.type == AssetType.cash or pos.type == AssetType.pension:
        return float(pos.cost_basis_chf), None, None, {}

    if pos.type == AssetType.crypto and pos.coingecko_id:
        crypto = get_crypto_price_chf(pos.coingecko_id)
        if crypto:
            return float(pos.shares) * crypto["price"], crypto["price"], "CHF", {}

    if pos.gold_org:
        gold = get_gold_price_chf()
        if gold:
            return float(pos.shares) * gold["price"], gold["price"], "CHF", {}

    if pos.pricing_mode.value == "manual":
        price = float(pos.current_price) if pos.current_price else 0
        return float(pos.shares) * price, price, pos.currency, {}

    yf_ticker = pos.yfinance_ticker or pos.ticker
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
