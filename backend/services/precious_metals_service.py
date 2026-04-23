import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position, PricingMode, PriceSource
from models.precious_metal_item import PreciousMetalItem, GRAMS_PER_TROY_OZ

logger = logging.getLogger(__name__)

# Metal type → ticker mapping
METAL_TICKERS: dict[str, str] = {
    "gold": "XAUCHF=X",
    "silver": "XAGCHF=X",
    "platinum": "XPTCHF=X",
    "palladium": "XPDCHF=X",
}

METAL_NAMES: dict[str, str] = {
    "gold": "Gold (physisch)",
    "silver": "Silber (physisch)",
    "platinum": "Platin (physisch)",
    "palladium": "Palladium (physisch)",
}

# Spot-Ticker → (yfinance-Futures-Ticker, Currency) fuer gold_org-Positionen.
# Live-CHF-Spot fuer Gold kommt von Gold.org; fuer Silber/Platin/Palladium gibt
# es keine CHF-Spot-API — wir nehmen die USD-Futures × USDCHF=X.
METAL_FUTURES: dict[str, tuple[str, str]] = {
    "XAUCHF=X": ("GC=F", "USD"),
    "XAGCHF=X": ("SI=F", "USD"),
    "XPTCHF=X": ("PL=F", "USD"),
    "XPDCHF=X": ("PA=F", "USD"),
}


def get_metal_futures(spot_ticker: str) -> tuple[str, str] | None:
    """Return (yfinance_futures_ticker, currency) for a precious-metal spot ticker."""
    return METAL_FUTURES.get(spot_ticker)


async def sync_metal_position(db: AsyncSession, user_id: uuid.UUID, metal_type: str) -> None:
    """Sync the commodity position for a metal type from precious_metal_items.

    Creates, updates, or deactivates the Position row that mirrors
    the aggregate of all unsold PreciousMetalItem rows for the given
    user and metal type.
    """
    ticker = METAL_TICKERS.get(metal_type)
    if not ticker:
        return

    # Sum all unsold items for this metal
    result = await db.execute(
        select(
            func.coalesce(func.sum(PreciousMetalItem.weight_grams), 0),
            func.coalesce(func.sum(PreciousMetalItem.purchase_price_chf), 0),
            func.count(PreciousMetalItem.id),
        ).where(
            PreciousMetalItem.user_id == user_id,
            PreciousMetalItem.metal_type == metal_type,
            PreciousMetalItem.is_sold == False,
        )
    )
    total_grams, total_cost, item_count = result.one()
    total_oz = round(float(total_grams) / GRAMS_PER_TROY_OZ, 8)
    total_cost = round(float(total_cost), 2)

    # Find or create position
    pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.ticker == ticker,
        )
    )
    pos = pos_result.scalars().first()

    if item_count == 0 and pos:
        # No items left — deactivate position
        pos.shares = 0
        pos.cost_basis_chf = 0
        pos.is_active = False
    elif item_count > 0 and pos:
        # Update existing position
        old_shares = float(pos.shares)
        pos.shares = total_oz
        pos.cost_basis_chf = total_cost
        pos.is_active = True
        if old_shares != total_oz:
            logger.info(
                f"Metal sync {ticker}: shares {old_shares} -> {total_oz} "
                f"({item_count} items, {float(total_grams)}g)"
            )
    elif item_count > 0 and not pos:
        # Create new position. gold_org=True fuer alle physischen Edelmetalle:
        # das Flag signalisiert "nutzt dedizierten Metall-Preispfad" (Name ist
        # historisch — kommt von der urspruenglichen Gold-only-Integration).
        is_gold = metal_type == "gold"
        pos = Position(
            user_id=user_id,
            ticker=ticker,
            name=METAL_NAMES.get(metal_type, f"{metal_type.title()} (physisch)"),
            type=AssetType.commodity,
            sector="Commodities",
            currency="CHF",
            pricing_mode=PricingMode.auto,
            price_source=PriceSource.gold_org if is_gold else PriceSource.yahoo,
            gold_org=True,
            shares=total_oz,
            cost_basis_chf=total_cost,
        )
        db.add(pos)

    await db.flush()
