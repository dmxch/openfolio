"""Lasttest-Daten fuer den Snapshot-Job.

Generiert N User × M Buckets × D Tage Bucket-Snapshots + zugehoerige Positionen.

Usage (im Stage-Container):
    python -m scripts.seed_loadtest --users 1000 --buckets 10 --days 365 \\
        --positions-per-user 50 --yes-delete-all

Daten werden mit COPY FROM STDIN gestreamt → minimale Roundtrips.

ACHTUNG: Loescht vor dem Seed die Positionen, Buckets, Transaktionen und
Bucket-Snapshots ALLER Nutzer der Datenbank, nicht nur der Lasttest-Konten.
Deshalb zwei Sperren: der Datenbankname muss ``_stage`` oder ``_test``
enthalten, und der Aufruf braucht ``--yes-delete-all``.
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
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("seed_loadtest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# Bcrypt-Hash fuer "stage123" (12 Rounds), derselbe wie in scripts/anonymize_dump.sql.
STAGE_PASSWORD_HASH = "$2b$12$8qvrXiV0LAtIL9TyTDwaWO/ZcWGreswgIQrpKxD22OurP4H6GTK2m"


def _stage_safety_check(database_url: str) -> None:
    """Sicherheits-Check: der DATENBANKNAME muss _stage oder _test enthalten.

    Geprueft wird nur der Name. Ein ``_test`` im Passwort oder im Hostnamen
    einer Production-URL gab das Loeschen frueher frei. Die Meldung nennt die
    URL ohne Passwort.
    """
    try:
        url = make_url(database_url)
    except ArgumentError:
        raise SystemExit("REFUSING: DATABASE_URL is not a valid database URL.") from None
    db_name = url.database or ""
    if "_stage" not in db_name and "_test" not in db_name:
        raise SystemExit(
            "REFUSING: database name must contain '_stage' or '_test'. "
            f"Got: {url.render_as_string(hide_password=True)!r}"
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
        logger.info("Deleting bucket_snapshots, transactions, positions and buckets of ALL users...")
        await conn.execute(text("TRUNCATE TABLE bucket_snapshots, bucket_alert_log, position_bucket_history RESTART IDENTITY CASCADE;"))
        await conn.execute(text("TRUNCATE TABLE transactions RESTART IDENTITY CASCADE;"))
        await conn.execute(text("DELETE FROM positions;"))
        await conn.execute(text("DELETE FROM buckets;"))
        # Die Konten anderer Nutzer bleiben bestehen, ihre Depotdaten sind oben geloescht.
        await conn.execute(text("DELETE FROM users WHERE email LIKE 'loadtest-%@example.test';"))

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
                    "INSERT INTO users (id, email, password_hash, mfa_enabled, is_active, "
                    " is_admin, force_password_change, created_at, updated_at) "
                    "VALUES (:id, :email, :pw, false, true, false, false, now(), now())"
                ),
                {
                    "id": uid,
                    "email": f"loadtest-{i}@example.test",
                    "pw": STAGE_PASSWORD_HASH,
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
                        " price_source, gold_org, shares, cost_basis_chf, current_price, "
                        " stop_loss_confirmed_at_broker, is_etf, is_active, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), :uid, :bid, :tk, :nm, 'stock', 'CHF', 'auto', "
                        " 'yahoo', false, :sh, :cb, :px, false, false, true, now(), now())"
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=1000)
    parser.add_argument("--buckets", type=int, default=10)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--positions-per-user", type=int, default=50)
    parser.add_argument(
        "--yes-delete-all",
        action="store_true",
        help="Bestaetigt: Positionen, Buckets, Transaktionen und Snapshots ALLER Nutzer werden geloescht.",
    )
    args = parser.parse_args(argv)

    import os
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    _stage_safety_check(database_url)
    if not args.yes_delete_all:
        print(
            "REFUSING: this deletes positions, buckets, transactions and snapshots of ALL users "
            "in the database. Re-run with --yes-delete-all to confirm.",
            file=sys.stderr,
        )
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
