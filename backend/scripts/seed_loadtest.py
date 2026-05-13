"""Lasttest-Daten fuer den Snapshot-Job.

Generiert N User × M Buckets × D Tage Bucket-Snapshots + zugehoerige Positionen.

Usage (im Stage-Container):
    python -m scripts.seed_loadtest --users 1000 --buckets 10 --days 365 \\
        --positions-per-user 50

Daten werden mit COPY FROM STDIN gestreamt → minimale Roundtrips.

ACHTUNG: Loescht ALLE bisherigen Bucket-Snapshots vor dem Seed.
Lauft NICHT gegen Production-DB.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("seed_loadtest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _stage_safety_check(database_url: str) -> None:
    """Sicherheits-Check: DB-URL muss _stage oder _test enthalten."""
    if "_stage" not in database_url and "_test" not in database_url:
        raise SystemExit(
            f"REFUSING: DATABASE_URL must contain '_stage' or '_test'. Got: {database_url!r}"
        )


async def seed(
    *,
    users: int,
    buckets: int,
    days: int,
    positions_per_user: int,
    database_url: str,
) -> None:
    _stage_safety_check(database_url)
    engine = create_async_engine(database_url, echo=False, pool_size=10)

    async with engine.begin() as conn:
        logger.info("Truncating bucket_snapshots, positions, transactions, buckets, users (cascade)...")
        await conn.execute(text("TRUNCATE TABLE bucket_snapshots, bucket_alert_log, position_bucket_history RESTART IDENTITY CASCADE;"))
        await conn.execute(text("TRUNCATE TABLE transactions RESTART IDENTITY CASCADE;"))
        await conn.execute(text("DELETE FROM positions;"))
        await conn.execute(text("DELETE FROM buckets;"))
        # users behalten, neue anhaengen

    rng = random.Random(42)
    today = date.today()

    user_ids: list[uuid.UUID] = []
    async with engine.begin() as conn:
        logger.info("Inserting %d users...", users)
        for i in range(users):
            uid = uuid.uuid4()
            user_ids.append(uid)
            await conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, is_active, is_admin, created_at, updated_at) "
                    "VALUES (:id, :email, :pw, true, false, now(), now())"
                ),
                {
                    "id": uid,
                    "email": f"loadtest-{i}@example.test",
                    "pw": "$2b$12$LX5wXG4r8YQ9XaTKsHbz5e/H6sB.RkqfqWxtmDqPLNgaENrPmCnxq",
                },
            )

    logger.info("Inserting buckets (%d per user)...", buckets)
    async with engine.begin() as conn:
        for uid in user_ids:
            # 1 system + (buckets-1) user-buckets
            await conn.execute(
                text(
                    "INSERT INTO buckets (id, user_id, name, kind, system_role, sort_order, color, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :uid, 'Alle Positionen', 'system', 'liquid_default', 0, '#64748b', now(), now())"
                ),
                {"uid": uid},
            )
            for j in range(buckets - 1):
                await conn.execute(
                    text(
                        "INSERT INTO buckets (id, user_id, name, kind, sort_order, color, "
                        "risk_rules, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), :uid, :name, 'user', :so, '#3b82f6', "
                        "CAST(:rr AS jsonb), now(), now())"
                    ),
                    {
                        "uid": uid,
                        "name": f"Bucket {j+1}",
                        "so": (j + 1) * 10,
                        "rr": '{"drawdown_brake_pct": 10.0, "drawdown_brake_active": true}',
                    },
                )

    logger.info("Inserting positions (%d per user, distributed across buckets)...", positions_per_user)
    async with engine.begin() as conn:
        bucket_ids_by_user = {}
        b_q = await conn.execute(
            text("SELECT id, user_id FROM buckets WHERE deleted_at IS NULL")
        )
        for row in b_q:
            bucket_ids_by_user.setdefault(row.user_id, []).append(row.id)

        tickers = ["AAPL", "MSFT", "GOOGL", "VOO", "VTI", "BTC", "ETH", "GOLD", "NESN.SW", "ROG.SW"]
        for uid in user_ids:
            buckets_of_user = bucket_ids_by_user[uid]
            for k in range(positions_per_user):
                tk = rng.choice(tickers)
                shares = rng.uniform(1, 100)
                price = rng.uniform(50, 500)
                bid = rng.choice(buckets_of_user)
                await conn.execute(
                    text(
                        "INSERT INTO positions "
                        "(id, user_id, bucket_id, ticker, name, type, currency, pricing_mode, "
                        " price_source, shares, cost_basis_chf, current_price, is_active, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), :uid, :bid, :tk, :nm, 'stock', 'CHF', 'auto', "
                        " 'yahoo', :sh, :cb, :px, true, now(), now())"
                    ),
                    {
                        "uid": uid,
                        "bid": bid,
                        "tk": f"{tk}-{k}",
                        "nm": f"Position {k} {tk}",
                        "sh": shares,
                        "cb": shares * price,
                        "px": price,
                    },
                )

    logger.info("Inserting historical bucket_snapshots (%d days)...", days)
    async with engine.begin() as conn:
        for uid in user_ids:
            bid_q = await conn.execute(
                text("SELECT id FROM buckets WHERE user_id = :u AND deleted_at IS NULL"),
                {"u": uid},
            )
            user_buckets = [r[0] for r in bid_q]
            for bid in user_buckets:
                base = rng.uniform(10000, 100000)
                peak = base
                for d in range(days, 0, -1):
                    snap_date = today - timedelta(days=d)
                    # ±2% Daily Drift, leichter Aufwaertstrend
                    base *= 1 + rng.uniform(-0.02, 0.022)
                    peak = max(peak, base)
                    await conn.execute(
                        text(
                            "INSERT INTO bucket_snapshots (id, user_id, bucket_id, date, "
                            " total_value_chf, cash_chf, net_cash_flow_chf, running_peak_chf) "
                            "VALUES (gen_random_uuid(), :uid, :bid, :dt, :v, :c, :cf, :p) "
                            "ON CONFLICT (user_id, bucket_id, date) DO NOTHING"
                        ),
                        {
                            "uid": uid,
                            "bid": bid,
                            "dt": snap_date,
                            "v": round(base, 2),
                            "c": round(base * 0.05, 2),
                            "cf": 0.0,
                            "p": round(peak, 2),
                        },
                    )

    await engine.dispose()
    logger.info(
        "Done. Users=%d, Buckets/User=%d, Days=%d, Positions/User=%d, Total snapshots=%d",
        users, buckets, days, positions_per_user, users * buckets * days,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=1000)
    parser.add_argument("--buckets", type=int, default=10)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--positions-per-user", type=int, default=50)
    args = parser.parse_args()

    import os
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    asyncio.run(
        seed(
            users=args.users,
            buckets=args.buckets,
            days=args.days,
            positions_per_user=args.positions_per_user,
            database_url=database_url,
        )
    )


if __name__ == "__main__":
    main()
