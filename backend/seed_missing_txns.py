"""One-time script to add all missing historical positions and transactions from PP."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date
from sqlalchemy import select
from db import async_session
from models.position import Position, AssetType, PriceSource, PricingMode
from models.transaction import Transaction, TransactionType


# ── Positions to CREATE (all fully sold, is_active=False) ──────────────────
NEW_POSITIONS = [
    {
        "ticker": "IWDA.L",
        "name": "iShares Core MSCI World",
        "type": AssetType.etf,
        "currency": "USD",
        "yfinance_ticker": "IWDA.L",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "CSPX.L",
        "name": "Invesco S&P 500 ETF",
        "type": AssetType.etf,
        "currency": "USD",
        "yfinance_ticker": "CSPX.L",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "INTC",
        "name": "Intel",
        "type": AssetType.stock,
        "currency": "USD",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "SBUX",
        "name": "Starbucks",
        "type": AssetType.stock,
        "currency": "USD",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "TSLA",
        "name": "Tesla",
        "type": AssetType.stock,
        "currency": "USD",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "ICGA.L",
        "name": "iShares MSCI China",
        "type": AssetType.etf,
        "currency": "USD",
        "yfinance_ticker": "ICGA.L",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "SGLD.L",
        "name": "iShares Physical Gold",
        "type": AssetType.etf,
        "currency": "USD",
        "yfinance_ticker": "SGLD.L",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "1329.T",
        "name": "X Nikkei 225",
        "type": AssetType.etf,
        "currency": "JPY",
        "yfinance_ticker": "1329.T",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "UBSJF",
        "name": "UBS MSCI Japan ETF",
        "type": AssetType.etf,
        "currency": "JPY",
        "yfinance_ticker": "UBSJF",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "CHSPI.SW",
        "name": "iShares Swiss Dividend ETF",
        "type": AssetType.etf,
        "currency": "CHF",
        "yfinance_ticker": "CHSPI.SW",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "ZPRS.L",
        "name": "SPDR MSCI World Small Cap",
        "type": AssetType.etf,
        "currency": "CHF",
        "yfinance_ticker": "ZPRS.L",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "CRB.PA",
        "name": "Amundi BB EW Commodities CRB",
        "type": AssetType.etf,
        "currency": "CHF",
        "yfinance_ticker": "CRB.PA",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "GDIG.L",
        "name": "VanEck S&P Global Mining",
        "type": AssetType.etf,
        "currency": "CHF",
        "yfinance_ticker": "GDIG.L",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
    {
        "ticker": "SXP.V",
        "name": "Southern Exploration",
        "type": AssetType.stock,
        "currency": "CAD",
        "yfinance_ticker": "SXP.V",
        "is_active": False,
        "shares": 0,
        "cost_basis_chf": 0,
    },
]

# ── Transactions keyed by ticker ──────────────────────────────────────────
# Format: (type, date, shares, price, currency, total_chf, notes)
# total_chf is the CHF equivalent at time of transaction

TRANSACTIONS = {
    # ─── IWDA (iShares Core MSCI World) ───
    "IWDA.L": [
        ("buy",  date(2024, 5, 10), 480, 98.63,  "USD", 47431.17, None),
        ("buy",  date(2024, 6, 6),   39, 100.78, "USD",  3947.59, None),
        ("sell", date(2024, 10, 18), 519, 108.46, "USD", 56186.27, None),
        ("buy",  date(2025, 11, 10),  57, 128.61, "USD",  7351.45, None),
        ("buy",  date(2026, 1, 15),   37, 133.26, "USD",  4950.48, None),
        ("sell", date(2026, 3, 4),    94, 131.11, "USD", 12295.73, None),
    ],
    # ─── Invesco S&P 500 ───
    "CSPX.L": [
        ("buy",  date(2023, 6, 14),  38, 843.96, "USD", 32135.04, None),
        ("sell", date(2024, 5, 10),  38, 1021.00, "USD", 38723.33, None),
    ],
    # ─── EIMI (additional historical txns — buy for existing position) ───
    "EIMI.L": [
        ("buy",  date(2023, 6, 14), 374, 30.66, "USD", 11497.64, None),
        ("buy",  date(2024, 5, 10), 890, 33.69, "USD", 30039.78, None),
        ("buy",  date(2024, 6, 6),  296, 33.73, "USD", 10009.75, None),
        ("sell", date(2024, 10, 18), 1560, 36.65, "USD", 57085.40, None),
    ],
    # ─── Intel ───
    "INTC": [
        ("buy",  date(2024, 8, 29), 515, 20.34, "USD", 10546.66, None),
        ("sell", date(2024, 10, 18), 515, 22.59, "USD", 11560.28, None),
    ],
    # ─── Starbucks ───
    "SBUX": [
        ("buy",  date(2024, 7, 12),  68, 73.49, "USD",  5034.82, None),
        ("sell", date(2024, 8, 13),  68, 91.16, "USD",  6158.56, None),
    ],
    # ─── Tesla ───
    "TSLA": [
        ("buy",  date(2025, 3, 24),  25, 272.69, "USD",  6857.48, None),
        ("buy",  date(2025, 3, 25),  49, 281.35, "USD", 13861.83, None),
        ("sell", date(2025, 7, 9),   74, 297.63, "USD", 21910.73, None),
    ],
    # ─── iShares MSCI China ───
    "ICGA.L": [
        ("buy",  date(2025, 11, 10), 397, 6.51, "USD", 2600.68, None),
        ("sell", date(2026, 1, 15),  397, 6.47, "USD", 2551.60, None),
    ],
    # ─── iShares Physical Gold (SGLD) ───
    "SGLD.L": [
        ("buy",  date(2025, 10, 14), 600, 49.00, "USD", 29579.95, None),
        ("sell", date(2026, 1, 8),   600, 72.43, "USD", 43257.16, None),
    ],
    # ─── X Nikkei 225 ───
    "1329.T": [
        ("buy",      date(2023, 6, 14), 463, 3489.00,  "JPY", 11350.00, None),
        ("dividend", date(2023, 9, 7),  463,   27.76,  "JPY",    85.00, None),
        ("dividend", date(2024, 3, 7),  463,   26.64,  "JPY",    82.00, None),
        ("sell",     date(2024, 5, 10), 463, 3952.67,  "JPY", 12150.00, None),
    ],
    # ─── UBS MSCI Japan ETF ───
    "UBSJF": [
        ("buy",  date(2025, 11, 10), 156, 4513.00, "JPY", 4700.00, None),
        ("sell", date(2026, 1, 15),  156, 4977.00, "JPY", 5140.00, None),
    ],
    # ─── iShares Swiss Dividend ETF ───
    # 53 shares were pre-existing (Anfangsbestand), modeled as delivery_in
    "CHSPI.SW": [
        ("delivery_in", date(2023, 6, 13),  53, 148.97, "CHF", 7895.41, "Anfangsbestand"),
        ("buy",         date(2023, 6, 14), 351, 148.97, "CHF", 52348.40, None),
        ("dividend",    date(2023, 7, 20), 351,   0.44, "CHF",   154.44, None),
        ("dividend",    date(2023, 7, 20), 351,   0.22, "CHF",    50.19, None),
        ("dividend",    date(2024, 3, 11), 351,   0.74, "CHF",   168.83, None),
        ("dividend",    date(2024, 3, 18), 351,   0.86, "CHF",   196.21, None),
        ("dividend",    date(2024, 4, 16), 351,   1.70, "CHF",   387.85, None),
        ("dividend",    date(2024, 4, 18), 351,   0.88, "CHF",   200.77, None),
        ("dividend",    date(2024, 4, 24), 351,   0.90, "CHF",   205.33, None),
        ("sell",        date(2024, 5, 10), 351, 153.70, "CHF", 53889.65, None),
        ("sell",        date(2026, 1, 15),  53, 182.51, "CHF",  9656.15, None),
    ],
    # ─── SPDR MSCI World Small Cap ───
    "ZPRS.L": [
        ("buy",  date(2024, 5, 10), 508, 93.19, "CHF", 47429.10, None),
        ("buy",  date(2024, 6, 6),   65, 91.28, "CHF",  5953.50, None),
        ("sell", date(2024, 10, 18), 573, 95.35, "CHF", 54534.05, None),
    ],
    # ─── Amundi BB EW Commodities CRB ───
    "CRB.PA": [
        ("buy",  date(2024, 6, 6),  924, 22.71, "CHF", 21028.40, None),
        ("sell", date(2025, 1, 14), 924, 23.39, "CHF", 21561.60, None),
    ],
    # ─── VanEck S&P Global Mining (Anfangsbestand) ───
    "GDIG.L": [
        ("delivery_in", date(2023, 6, 13), 119, 51.10, "CHF", 6080.90, "Anfangsbestand"),
        ("sell",        date(2026, 1, 15), 119, 51.10, "CHF", 6061.58, None),
    ],
    # ─── Southern Exploration ───
    "SXP.V": [
        ("buy",  date(2026, 1, 20), 21086, 0.48, "CHF", 10144.70, None),
        ("sell", date(2026, 1, 26), 10543, 1.08, "CAD", 7900.00, None),
        ("sell", date(2026, 1, 26), 10543, 1.08, "CAD", 7900.00, None),
    ],
    # ─── ASML — additional buy on 06.03.2026 (position already exists) ───
    "ASML": [
        ("buy", date(2026, 3, 6), 3, 1293.86, "USD", 3033, None),
    ],
    # ─── LHX — additional buy on 06.03.2026 (position already exists) ───
    "LHX": [
        ("buy", date(2026, 3, 6), 8, 360.83, "USD", 2247, None),
    ],
}


async def main():
    async with async_session() as db:
        # Load existing positions by ticker
        result = await db.execute(select(Position))
        all_positions = result.scalars().all()
        existing = {p.ticker: p for p in all_positions}
        # Also map by yfinance_ticker
        for p in all_positions:
            if p.yfinance_ticker:
                existing[p.yfinance_ticker] = p

        # Check existing transaction count
        result = await db.execute(select(Transaction))
        existing_txns = result.scalars().all()
        print(f"Existing: {len(existing)} positions, {len(existing_txns)} transactions")

        # Create new positions
        created_positions = {}
        for pos_data in NEW_POSITIONS:
            ticker = pos_data["ticker"]
            if ticker in existing:
                print(f"  SKIP position {ticker} (already exists)")
                created_positions[ticker] = existing[ticker]
                continue
            pos = Position(**pos_data)
            db.add(pos)
            created_positions[ticker] = pos
            print(f"  CREATE position {ticker} ({pos_data['name']})")

        await db.flush()  # Get IDs for new positions

        # Add transactions
        txn_count = 0
        for ticker, txns in TRANSACTIONS.items():
            # Find position
            pos = created_positions.get(ticker) or existing.get(ticker)
            if not pos:
                print(f"  ERROR: position {ticker} not found!")
                continue

            for txn_data in txns:
                txn_type_str, txn_date, shares, price, currency, total_chf, notes = txn_data
                txn_type = TransactionType(txn_type_str)

                # Check for duplicate
                dup = await db.execute(
                    select(Transaction).where(
                        Transaction.position_id == pos.id,
                        Transaction.type == txn_type,
                        Transaction.date == txn_date,
                        Transaction.shares == shares,
                    )
                )
                if dup.scalars().first():
                    print(f"  SKIP duplicate: {ticker} {txn_type_str} {shares}x @ {price} on {txn_date}")
                    continue

                txn = Transaction(
                    position_id=pos.id,
                    user_id=pos.user_id,
                    type=txn_type,
                    date=txn_date,
                    shares=shares,
                    price_per_share=price,
                    currency=currency,
                    total_chf=total_chf,
                    notes=notes,
                )
                db.add(txn)
                txn_count += 1
                print(f"  ADD {ticker}: {txn_type_str} {shares}x @ {price} {currency} on {txn_date}")

        await db.commit()
        print(f"\nDone! Added {txn_count} transactions.")

        # Verify final state
        result = await db.execute(select(Transaction))
        all_txns = result.scalars().all()
        result = await db.execute(select(Position))
        all_pos = result.scalars().all()
        print(f"Final: {len(all_pos)} positions, {len(all_txns)} transactions")


if __name__ == "__main__":
    asyncio.run(main())
