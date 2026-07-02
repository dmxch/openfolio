"""Daily portfolio change calculation from price_cache."""
import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import Position
from models.price_cache import PriceCache


async def calculate_daily_change(db: AsyncSession, user_id: UUID) -> dict:
    """Calculate today's portfolio change using price_cache (not positions.current_price)."""
    result = await db.execute(
        select(Position).where(
            Position.is_active == True,
            Position.type.notin_(["cash", "pension", "private_equity"]),
            Position.user_id == user_id,
        )
    )
    positions = result.scalars().all()

    empty = {"daily_change_chf": 0, "daily_change_pct": 0, "positions_valued": 0, "timestamp": datetime.datetime.now().isoformat()}
    if not positions:
        return empty

    # Get the two most recent dates in price_cache
    date_result = await db.execute(
        select(PriceCache.date).distinct().order_by(PriceCache.date.desc()).limit(2)
    )
    dates = [row[0] for row in date_result]

    if len(dates) < 2:
        return empty

    today_date, prev_date = dates[0], dates[1]

    # Collect tickers needed from positions
    needed_tickers = set()
    for pos in positions:
        if pos.pricing_mode and pos.pricing_mode.value == "manual":
            continue
        needed_tickers.add(pos.yfinance_ticker or pos.ticker)

    # Get today's and previous close prices from cache (filtered to needed tickers)
    today_result = await db.execute(
        select(PriceCache.ticker, PriceCache.close, PriceCache.currency).where(
            PriceCache.date == today_date, PriceCache.ticker.in_(needed_tickers)
        )
    )
    today_prices = {row.ticker: {"close": float(row.close), "currency": row.currency} for row in today_result}

    prev_result = await db.execute(
        select(PriceCache.ticker, PriceCache.close, PriceCache.currency).where(
            PriceCache.date == prev_date, PriceCache.ticker.in_(needed_tickers)
        )
    )
    prev_prices = {row.ticker: {"close": float(row.close), "currency": row.currency} for row in prev_result}

    # Batch-load FX rates for all needed currencies in one query.
    # Massgeblich ist die RESOLVED Quote-Währung der price_cache-Row (Pence-.L
    # wird dort schon GBP-normalisiert gespeichert); pos.currency ist nur
    # Fallback — ".L sagt NICHTS über die Währung" (Review 2026-07-02).
    currencies_needed = set()
    for pos in positions:
        if pos.pricing_mode and pos.pricing_mode.value == "manual":
            continue
        if pos.currency and pos.currency != "CHF":
            currencies_needed.add(pos.currency)
    for price_map in (today_prices, prev_prices):
        for row in price_map.values():
            if row.get("currency") and row["currency"] != "CHF":
                currencies_needed.add(row["currency"])

    fx_cache: dict[str, float] = {"CHF": 1.0}
    if currencies_needed:
        fx_pairs = [f"{c}CHF=X" for c in currencies_needed]
        fx_result = await db.execute(
            select(PriceCache.ticker, PriceCache.close)
            .where(PriceCache.ticker.in_(fx_pairs))
            .order_by(PriceCache.date.desc())
        )
        seen: set[str] = set()
        for row in fx_result:
            if row.ticker not in seen:
                currency = row.ticker.replace("CHF=X", "")
                fx_cache[currency] = float(row.close)
                seen.add(row.ticker)

    total_change_chf = 0.0
    total_prev_value_chf = 0.0
    positions_valued = 0

    for pos in positions:
        if pos.pricing_mode and pos.pricing_mode.value == "manual":
            continue
        yf_ticker = pos.yfinance_ticker or pos.ticker
        today_data = today_prices.get(yf_ticker)
        prev_data = prev_prices.get(yf_ticker)
        if not today_data or not prev_data:
            continue
        shares = float(pos.shares)
        if shares <= 0:
            continue
        fx = fx_cache.get(today_data.get("currency") or pos.currency)
        if fx is None:
            fx = fx_cache.get(pos.currency)
        if fx is None:
            continue
        prev_value = prev_data["close"] * shares * fx
        curr_value = today_data["close"] * shares * fx
        total_change_chf += curr_value - prev_value
        total_prev_value_chf += prev_value
        positions_valued += 1

    daily_pct = (total_change_chf / total_prev_value_chf * 100) if total_prev_value_chf > 0 else 0

    return {
        "daily_change_chf": round(total_change_chf, 2),
        "daily_change_pct": round(daily_pct, 2),
        "positions_valued": positions_valued,
        "timestamp": datetime.datetime.now().isoformat(),
    }
