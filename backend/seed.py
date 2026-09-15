"""Seed the database with initial portfolio data."""
import asyncio
import logging
import subprocess
from datetime import date

logger = logging.getLogger(__name__)

from sqlalchemy import select

from db import engine, async_session
from models import Position, WatchlistItem, Property, Mortgage
from models.bucket import BucketSystemRole
from models.position import AssetType, PricingMode, PriceSource, Style
from models.transaction import Transaction, TransactionType
from models.user import User
from services.bucket_service import get_system_bucket


# Fiktives Beispiel-Depot — erfundene Stückzahlen, Kaufkurse und Kaufdaten
# (wie "Beispiel-Immobilie"/"Beispielbank" weiter unten). Die Ticker sind echt,
# damit yfinance/CoinGecko/gold.org im Demo-Lauf auflösen; gerechnet ist mit
# runden Kursen und USD→CHF 0.80 bzw. CAD→CHF 0.60.
POSITIONS = [
    {"ticker": "AAPL", "name": "Apple", "type": AssetType.stock, "sector": "Technology", "currency": "USD", "style": Style.compounder, "shares": 50, "cost_basis_chf": 10000, "buy_date": date(2025, 1, 15), "buy_price": 250.00},
    {"ticker": "GOOGL", "name": "Alphabet", "type": AssetType.stock, "sector": "Communication Services", "currency": "USD", "style": Style.compounder, "shares": 40, "cost_basis_chf": 8000, "buy_date": date(2025, 1, 15), "buy_price": 250.00},
    {"ticker": "KO", "name": "Coca-Cola", "type": AssetType.stock, "sector": "Consumer Staples", "currency": "USD", "style": Style.defensive, "shares": 100, "cost_basis_chf": 6000, "buy_date": date(2025, 3, 3), "buy_price": 75.00},
    {"ticker": "MRK", "name": "Merck & Co", "type": AssetType.stock, "sector": "Healthcare", "currency": "USD", "style": Style.defensive, "shares": 100, "cost_basis_chf": 8000, "buy_date": date(2025, 3, 3), "buy_price": 100.00},
    {"ticker": "NEM", "name": "Newmont", "type": AssetType.stock, "sector": "Materials", "currency": "USD", "style": Style.opportunistic, "shares": 100, "cost_basis_chf": 6000, "buy_date": date(2025, 6, 2), "buy_price": 75.00},
    {"ticker": "CAT", "name": "Caterpillar", "type": AssetType.stock, "sector": "Industrials", "currency": "USD", "style": Style.compounder, "shares": 20, "cost_basis_chf": 6800, "buys": [{"date": date(2026, 1, 12), "shares": 10, "price": 400.00, "total_chf": 3200}, {"date": date(2026, 2, 10), "shares": 10, "price": 450.00, "total_chf": 3600}]},
    {"ticker": "TSM", "name": "Taiwan Semiconductor", "type": AssetType.stock, "sector": "Technology", "currency": "USD", "style": Style.compounder, "shares": 40, "cost_basis_chf": 7200, "buys": [{"date": date(2026, 1, 12), "shares": 20, "price": 200.00, "total_chf": 3200}, {"date": date(2026, 3, 10), "shares": 20, "price": 250.00, "total_chf": 4000}]},
    {"ticker": "NESN.SW", "name": "Nestlé", "type": AssetType.stock, "sector": "Consumer Staples", "currency": "CHF", "style": Style.defensive, "shares": 100, "cost_basis_chf": 8000, "buy_date": date(2025, 2, 3), "buy_price": 80.00},
    {"ticker": "ABBN.SW", "name": "ABB", "type": AssetType.stock, "sector": "Industrials", "currency": "CHF", "style": Style.compounder, "shares": 100, "cost_basis_chf": 5000, "buy_date": date(2025, 2, 3), "buy_price": 50.00},
    {"ticker": "ENB", "name": "Enbridge", "type": AssetType.stock, "sector": "Energy", "currency": "CAD", "yfinance_ticker": "ENB.TO", "style": Style.defensive, "shares": 200, "cost_basis_chf": 7200, "buy_date": date(2025, 4, 1), "buy_price": 60.00},
    {"ticker": "IWDA.L", "name": "iShares Core MSCI World", "type": AssetType.etf, "sector": "Developed Markets", "currency": "USD", "style": Style.core, "shares": 200, "cost_basis_chf": 16000, "buy_date": date(2024, 11, 1), "buy_price": 100.00},
    {"ticker": "ETH-USD", "name": "Ethereum", "type": AssetType.crypto, "sector": "Crypto", "currency": "USD", "style": Style.opportunistic, "shares": 5, "cost_basis_chf": 10000, "coingecko_id": "ethereum", "price_source": PriceSource.coingecko, "buy_date": date(2024, 9, 2), "buy_price": 2500.00},
    {"ticker": "Gold", "name": "Gold physisch", "type": AssetType.commodity, "sector": "Commodities", "currency": "CHF", "gold_org": True, "price_source": PriceSource.gold_org, "style": Style.defensive, "shares": 5, "cost_basis_chf": 15000, "buy_date": date(2025, 5, 2), "buy_price": 3000.00},
    {"ticker": "CASH_BANK_LOHN", "name": "Lohnkonto CHF", "type": AssetType.cash, "sector": "Cash", "currency": "CHF", "style": Style.cash, "shares": 1, "cost_basis_chf": 10000, "pricing_mode": PricingMode.manual, "price_source": PriceSource.manual, "current_price": 10000},
    {"ticker": "CASH_BANK_SPAR", "name": "Sparkonto CHF", "type": AssetType.cash, "sector": "Cash", "currency": "CHF", "style": Style.cash, "shares": 1, "cost_basis_chf": 20000, "pricing_mode": PricingMode.manual, "price_source": PriceSource.manual, "current_price": 20000},
    {"ticker": "CASH_BROKER_CHF", "name": "Broker CHF", "type": AssetType.cash, "sector": "Cash", "currency": "CHF", "style": Style.cash, "shares": 1, "cost_basis_chf": 5000, "pricing_mode": PricingMode.manual, "price_source": PriceSource.manual, "current_price": 5000},
    {"ticker": "CASH_BROKER_USD", "name": "Broker USD", "type": AssetType.cash, "sector": "Cash", "currency": "CHF", "style": Style.cash, "shares": 1, "cost_basis_chf": 2000, "pricing_mode": PricingMode.manual, "price_source": PriceSource.manual, "current_price": 2000},
    {"ticker": "PENSION_3A", "name": "Säule 3a", "type": AssetType.pension, "sector": "Pension", "currency": "CHF", "style": Style.defensive, "shares": 1, "cost_basis_chf": 12000, "pricing_mode": PricingMode.manual, "price_source": PriceSource.manual, "current_price": 12000},
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
    # Schema via Migrationen aufbauen — NICHT create_all + stamp head:
    # create_all kennt Migration-only-DDL nicht (CHECK-Constraints wie
    # ck_api_write_log_action, Composite-Indizes, Typ-Abweichungen) und der
    # Stamp markierte die lückenhafte DB trotzdem als "head", womit die
    # Lücke nie mehr geschlossen wurde (Review 2026-06-10, M5).
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    print("Alembic upgrade head done (schema via migrations).")

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

        # positions.bucket_id ist NOT NULL (Migration 064): jede Position braucht
        # einen Bucket. Derselbe Pfad wie beim App-Anlegen (api/positions.py):
        # pension/real_estate/private_equity → jeweiliger System-Bucket,
        # alle liquiden Typen → liquid_default. get_system_bucket legt die
        # System-Buckets bei Bedarf idempotent an (on_conflict_do_nothing).
        type_to_role = {
            AssetType.pension: BucketSystemRole.pension,
            AssetType.real_estate: BucketSystemRole.real_estate,
            AssetType.private_equity: BucketSystemRole.private_equity,
        }
        bucket_id_by_role = {}
        for role in {type_to_role.get(p["type"], BucketSystemRole.liquid_default) for p in POSITIONS}:
            bucket = await get_system_bucket(db, admin_id, role)
            bucket_id_by_role[role] = bucket.id

        for p_src in POSITIONS:
            p = dict(p_src)  # POSITIONS nicht mutieren (pop) — Wiederverwendbarkeit
            buy_date = p.pop("buy_date", None)
            buy_price = p.pop("buy_price", None)
            buys = p.pop("buys", None)
            p["user_id"] = admin_id
            role = type_to_role.get(p["type"], BucketSystemRole.liquid_default)
            p["bucket_id"] = bucket_id_by_role[role]
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
