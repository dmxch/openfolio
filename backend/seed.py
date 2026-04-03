"""Seed the database with initial portfolio data."""
import asyncio
import logging
import subprocess
from datetime import date

logger = logging.getLogger(__name__)

from sqlalchemy import select

from db import engine, async_session
from models import Base, Position, WatchlistItem, Property, Mortgage
from models.position import AssetType, PricingMode, PriceSource, Style
from models.transaction import Transaction, TransactionType
from models.user import User


POSITIONS = [
    {"ticker": "WM", "name": "Waste Management", "type": AssetType.stock, "sector": "Industrials", "currency": "USD", "style": Style.compounder, "shares": 55, "cost_basis_chf": 9918, "buy_date": date(2026, 2, 26), "buy_price": 232.91},
    {"ticker": "RSG", "name": "Republic Services", "type": AssetType.stock, "sector": "Industrials", "currency": "USD", "style": Style.compounder, "shares": 56, "cost_basis_chf": 9832, "buy_date": date(2026, 2, 27), "buy_price": 228.42},
    {"ticker": "JNJ", "name": "Johnson & Johnson", "type": AssetType.stock, "sector": "Healthcare", "currency": "USD", "style": Style.defensive, "shares": 53, "cost_basis_chf": 10033, "buy_date": date(2026, 2, 25), "buy_price": 244.94},
    {"ticker": "PEP", "name": "PepsiCo", "type": AssetType.stock, "sector": "Consumer Staples", "currency": "USD", "style": Style.defensive, "shares": 77, "cost_basis_chf": 10043, "buy_date": date(2026, 2, 25), "buy_price": 168.77},
    {"ticker": "PM", "name": "Philip Morris", "type": AssetType.stock, "sector": "Consumer Staples", "currency": "USD", "style": Style.defensive, "shares": 68, "cost_basis_chf": 10005, "buy_date": date(2026, 2, 25), "buy_price": 190.40},
    {"ticker": "ASML", "name": "ASML Holding", "type": AssetType.stock, "sector": "Technology", "currency": "USD", "style": Style.compounder, "shares": 6, "cost_basis_chf": 6289, "buys": [{"date": date(2026, 3, 4), "shares": 3, "price": 1390.52, "total_chf": 3256}, {"date": date(2026, 3, 6), "shares": 3, "price": 1293.86, "total_chf": 3033}]},
    {"ticker": "LHX", "name": "L3Harris Technologies", "type": AssetType.stock, "sector": "Industrials", "currency": "USD", "style": Style.compounder, "shares": 16, "cost_basis_chf": 4549, "buys": [{"date": date(2026, 3, 4), "shares": 8, "price": 368.86, "total_chf": 2302}, {"date": date(2026, 3, 6), "shares": 8, "price": 360.83, "total_chf": 2247}]},
    {"ticker": "NOVN.SW", "name": "Novartis", "type": AssetType.stock, "sector": "Healthcare", "currency": "CHF", "style": Style.defensive, "shares": 77, "cost_basis_chf": 9937, "buy_date": date(2026, 2, 26), "buy_price": 129.06},
    {"ticker": "ROG.SW", "name": "Roche GS", "type": AssetType.stock, "sector": "Healthcare", "currency": "CHF", "style": Style.defensive, "shares": 27, "cost_basis_chf": 9893, "buy_date": date(2026, 2, 26), "buy_price": 366.40},
    {"ticker": "PAAS", "name": "Pan American Silver", "type": AssetType.stock, "sector": "Materials", "currency": "CAD", "yfinance_ticker": "PAAS.TO", "style": Style.opportunistic, "shares": 188, "cost_basis_chf": 9979, "buy_date": date(2026, 1, 26), "buy_price": 93.66},
    {"ticker": "EIMI.L", "name": "iShares MSCI EM IMI", "type": AssetType.etf, "sector": "Emerging Markets", "currency": "USD", "style": Style.core, "shares": 164, "cost_basis_chf": 5931, "buy_date": date(2025, 11, 10), "buy_price": 44.86},
    {"ticker": "BTC-USD", "name": "Bitcoin", "type": AssetType.crypto, "sector": "Crypto", "currency": "USD", "style": Style.opportunistic, "shares": 0.5, "cost_basis_chf": 25000, "coingecko_id": "bitcoin", "price_source": PriceSource.coingecko, "buy_date": date(2024, 6, 10), "buy_price": 55000},
    {"ticker": "Gold", "name": "Gold physisch", "type": AssetType.commodity, "sector": "Commodities", "currency": "CHF", "gold_org": True, "price_source": PriceSource.gold_org, "style": Style.defensive, "shares": 8.04, "cost_basis_chf": 25000, "buy_date": date(2025, 3, 1), "buy_price": 3100},
    {"ticker": "CASH_BANK_LOHN", "name": "Lohnkonto CHF", "type": AssetType.cash, "sector": "Cash", "currency": "CHF", "style": Style.cash, "shares": 1, "cost_basis_chf": 25000, "pricing_mode": PricingMode.manual, "price_source": PriceSource.manual, "current_price": 25000},
    {"ticker": "CASH_BANK_SPAR", "name": "Sparkonto CHF", "type": AssetType.cash, "sector": "Cash", "currency": "CHF", "style": Style.cash, "shares": 1, "cost_basis_chf": 10000, "pricing_mode": PricingMode.manual, "price_source": PriceSource.manual, "current_price": 10000},
    {"ticker": "CASH_BROKER_CHF", "name": "Broker CHF", "type": AssetType.cash, "sector": "Cash", "currency": "CHF", "style": Style.cash, "shares": 1, "cost_basis_chf": 15000, "pricing_mode": PricingMode.manual, "price_source": PriceSource.manual, "current_price": 15000},
    {"ticker": "CASH_BROKER_USD", "name": "Broker USD", "type": AssetType.cash, "sector": "Cash", "currency": "CHF", "style": Style.cash, "shares": 1, "cost_basis_chf": 5000, "pricing_mode": PricingMode.manual, "price_source": PriceSource.manual, "current_price": 5000},
    {"ticker": "PENSION_3A", "name": "Säule 3a", "type": AssetType.pension, "sector": "Pension", "currency": "CHF", "style": Style.defensive, "shares": 1, "cost_basis_chf": 7000, "pricing_mode": PricingMode.manual, "price_source": PriceSource.manual, "current_price": 7000},
]

WATCHLIST = [
    ("ABBV", "AbbVie", "Healthcare"),
    ("BAM", "Brookfield Asset Management", "Financials"),
    ("CL", "Colgate-Palmolive", "Consumer Staples"),
    ("COST", "Costco", "Consumer Staples"),
    ("CVX", "Chevron", "Energy"),
    ("ITW", "Illinois Tool Works", "Industrials"),
    ("KTOS", "Kratos Defense", "Industrials"),
    ("LMT", "Lockheed Martin", "Industrials"),
    ("MA", "Mastercard", "Financials"),
    ("MSFT", "Microsoft", "Technology"),
    ("NOC", "Northrop Grumman", "Industrials"),
    ("PG", "Procter & Gamble", "Consumer Staples"),
    ("RTX", "RTX Corporation", "Industrials"),
    ("SPGI", "S&P Global", "Financials"),
    ("TDG", "TransDigm", "Industrials"),
    ("TXN", "Texas Instruments", "Technology"),
    ("V", "Visa", "Financials"),
    ("XOM", "ExxonMobil", "Energy"),
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Stamp alembic to head if no version exists yet (fresh DB created by create_all)
    try:
        from sqlalchemy import text as sa_text
        async with engine.connect() as conn:
            result = await conn.execute(sa_text("SELECT count(*) FROM alembic_version"))
            count = result.scalar()
            if count == 0:
                # Use alembic stamp head to always match the latest migration
                subprocess.run(["alembic", "stamp", "head"], check=True)
                print("Stamped alembic to head (fresh DB).")
    except Exception as e:
        logger.debug(f"Alembic version check skipped (expected on first run): {e}")

    async with async_session() as db:
        # Find the admin user (created by backend startup from ADMIN_EMAIL env var)
        admin_result = await db.execute(select(User).where(User.is_admin.is_(True)).limit(1))
        admin_user = admin_result.scalars().first()
        if not admin_user:
            # Fallback: get any user
            any_result = await db.execute(select(User).limit(1))
            admin_user = any_result.scalars().first()
        if not admin_user:
            print("No user found in database. Create an admin user first (via init.sh or backend startup).")
            return

        admin_id = admin_user.id

        # Seed properties independently
        existing_props = await db.execute(select(Property))
        if not existing_props.scalars().first():
            prop = Property(
                user_id=admin_id,
                name="Beispiel-Immobilie",
                property_type="efh",
                purchase_date=date(2024, 1, 15),
                purchase_price=850_000,
                estimated_value=850_000,
                estimated_value_date=date(2024, 1, 15),
                canton="ZH",
            )
            db.add(prop)
            await db.flush()

            m1 = Mortgage(
                property_id=prop.id,
                name="Fest-Hypothek",
                type="fixed",
                amount=500_000,
                interest_rate=1.500,
                start_date=date(2024, 1, 15),
                end_date=date(2029, 1, 15),
                amortization_annual=10_000,
                bank="Beispielbank",
            )
            m2 = Mortgage(
                property_id=prop.id,
                name="SARON-Hypothek",
                type="saron",
                amount=200_000,
                interest_rate=0.800,
                start_date=date(2024, 1, 15),
                end_date=date(2027, 1, 15),
                amortization_annual=5_000,
                bank="Beispielbank",
            )
            db.add(m1)
            db.add(m2)
            await db.commit()
            print("Seeded 1 property with 2 mortgages.")

        existing = await db.execute(select(Position))
        if existing.scalars().first():
            print("Positions already seeded, skipping.")
            return

        for p in POSITIONS:
            buy_date = p.pop("buy_date", None)
            buy_price = p.pop("buy_price", None)
            buys = p.pop("buys", None)
            p["user_id"] = admin_id
            pos = Position(**p)
            db.add(pos)
            await db.flush()

            if buys:
                for buy in buys:
                    txn = Transaction(
                        position_id=pos.id,
                        user_id=pos.user_id,
                        type=TransactionType.buy,
                        date=buy["date"],
                        shares=buy["shares"],
                        price_per_share=buy["price"],
                        currency=p.get("currency", "CHF"),
                        fx_rate_to_chf=1.0,
                        fees_chf=0,
                        taxes_chf=0,
                        total_chf=buy["total_chf"],
                    )
                    db.add(txn)
            elif buy_date and buy_price:
                txn = Transaction(
                    position_id=pos.id,
                    user_id=pos.user_id,
                    type=TransactionType.buy,
                    date=buy_date,
                    shares=p.get("shares", 0),
                    price_per_share=buy_price,
                    currency=p.get("currency", "CHF"),
                    fx_rate_to_chf=1.0,
                    fees_chf=0,
                    taxes_chf=0,
                    total_chf=p.get("cost_basis_chf", 0),
                )
                db.add(txn)

        for ticker, name, sector in WATCHLIST:
            db.add(WatchlistItem(user_id=admin_id, ticker=ticker, name=name, sector=sector))

        await db.commit()
        print(f"Seeded {len(POSITIONS)} positions and {len(WATCHLIST)} watchlist items.")


if __name__ == "__main__":
    asyncio.run(seed())
