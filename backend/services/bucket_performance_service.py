"""Performance-Berechnung pro Bucket.

Architektur-Prinzip (siehe Plan §4.2):
  Die bestehenden Performance-Services (portfolio_service,
  performance_history_service, total_return_service) duerfen NICHT geaendert
  werden. Dieser Service wrapped sie mit zusaetzlichem bucket_id-Filter.

Cashflow-Zuordnung:
  Eine Transaktion gehoert zu Bucket der Position zum Zeitpunkt der Transaktion.
  Da Bucket-Wechsel prospektiv sind (Re-Labeling, kein Cost-Basis-Split), reicht
  fuer das Cashflow-Aggregat: Transaction.position_id → aktuelle Position.bucket_id.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from constants.cashflow import INFLOW_TYPES, OUTFLOW_TYPES
from models.bucket import Bucket, BucketSnapshot
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import Position
from models.transaction import Transaction

logger = logging.getLogger(__name__)


async def get_bucket_summary(
    db: AsyncSession, user_id: uuid.UUID, bucket_id: uuid.UUID
) -> dict:
    """Aktueller Markt-Wert + Cost-Basis fuer einen Bucket.

    Returns:
        {
          "bucket_id", "name", "total_value_chf", "cost_basis_chf",
          "unrealized_pnl_chf", "unrealized_pnl_pct",
          "position_count", "running_peak_chf"
        }
    """
    bucket_q = await db.execute(
        select(Bucket).where(Bucket.id == bucket_id, Bucket.user_id == user_id)
    )
    bucket = bucket_q.scalar_one_or_none()
    if bucket is None:
        return {}

    # Aktuelle Positionen im Bucket
    pos_q = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.bucket_id == bucket_id,
            Position.is_active.is_(True),
        )
    )
    positions = list(pos_q.scalars().all())

    # Snapshots ab Bucket-Erstellung. Backfill-Rows davor sind synthetisch
    # (anteilige Portfolio-Rendite, siehe compare_to_benchmark). Wir rechnen
    # Wealth-Index + Peak on-the-fly aus den rohen Snapshots, statt den
    # gespeicherten wealth_index zu lesen — der kann nach Regenerate/Backfill
    # mid-series auf 1.0 zuruecksetzen. So kommen YTD-Kachel, Drawdown und
    # Monats-Heatmap alle aus derselben Quelle (Tages-gechainter TWR).
    inception = bucket.created_at.date()
    chain_q = await db.execute(
        select(BucketSnapshot)
        .where(
            BucketSnapshot.user_id == user_id,
            BucketSnapshot.bucket_id == bucket_id,
            BucketSnapshot.date >= inception,
        )
        .order_by(BucketSnapshot.date.asc())
    )
    chain_rows = list(chain_q.scalars().all())
    latest = chain_rows[-1] if chain_rows else None

    total_value = Decimal("0")
    cost_basis = Decimal("0")
    for p in positions:
        cost_basis += Decimal(p.cost_basis_chf or 0)
        if p.shares and p.current_price:
            # Vereinfachung: CHF-Wert. FX-Konvertierung passiert in
            # snapshot_service._calc_portfolio_value_fast. Hier nur Naeherung
            # fuer Live-Ansicht; final value via bucket_snapshots.
            total_value += Decimal(str(float(p.shares) * float(p.current_price)))

    # Bevorzugt Snapshot-Wert (FX-akkurat)
    if latest is not None:
        total_value = latest.total_value_chf

    unrealized = total_value - cost_basis
    unrealized_pct = (
        float((unrealized / cost_basis) * 100) if cost_basis > 0 else 0.0
    )

    # Drawdown vs Peak: Wealth-Index-Chain on-the-fly, cashflow-bereinigt
    # ((v - cf)/v_prev), damit ein Sell (Outflow) keinen kuenstlichen Drawdown
    # ausloest. running_peak_chf = Nominalwert am Tag des Wealth-Index-Hochs.
    drawdown_vs_peak_pct: float | None = None
    running_peak_chf = float(total_value)
    if chain_rows:
        wealth = 1.0
        peak_wealth = 1.0
        prev_value = float(chain_rows[0].total_value_chf or 0)
        running_peak_chf = prev_value
        for s in chain_rows[1:]:
            v = float(s.total_value_chf or 0)
            cf = float(s.net_cash_flow_chf or 0)
            if prev_value > 0:
                ret_factor = (v - cf) / prev_value
                if ret_factor > 0:
                    wealth *= ret_factor
            if wealth > peak_wealth:
                peak_wealth = wealth
                running_peak_chf = v
            prev_value = v
        if peak_wealth > 0:
            drawdown_vs_peak_pct = round((wealth / peak_wealth - 1) * 100, 2)

    return {
        "bucket_id": str(bucket_id),
        "name": bucket.name,
        "color": bucket.color,
        "benchmark": bucket.benchmark,
        "total_value_chf": float(total_value),
        "cost_basis_chf": float(cost_basis),
        "unrealized_pnl_chf": float(unrealized),
        "unrealized_pnl_pct": round(unrealized_pct, 2),
        "position_count": len(positions),
        "running_peak_chf": round(running_peak_chf, 2),
        "drawdown_vs_peak_pct": drawdown_vs_peak_pct,
        "snapshot_date": latest.date.isoformat() if latest else None,
    }


async def get_bucket_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
    *,
    period: str = "ytd",
) -> list[dict]:
    """Zeitreihe (date, total_value_chf, net_cash_flow_chf) aus bucket_snapshots.

    period: 'ytd' | '1m' | '3m' | '6m' | '1y' | 'all'.

    Hinweis: Anders als get_bucket_summary / compare_to_benchmark wird hier NICHT
    auf created_at geklemmt — die Wertkurve zeigt bewusst auch die (approximierte)
    Backfill-Historie vor Bucket-Erstellung (siehe bucket_snapshot_backfill_service,
    UI weist darauf hin). running_peak_chf ist hier die gespeicherte Spalte und kann
    nach Regenerate/Backfill leicht nachhinken; das Frontend rendert daraus aktuell
    keine Peak-Linie (der "vs Peak"-Wert der Karte kommt on-the-fly aus
    get_bucket_summary).
    """
    today = date.today()
    if period == "ytd":
        start = date(today.year, 1, 1)
    elif period == "1m":
        start = today - timedelta(days=30)
    elif period == "3m":
        start = today - timedelta(days=90)
    elif period == "6m":
        start = today - timedelta(days=180)
    elif period == "1y":
        start = today - timedelta(days=365)
    elif period == "all":
        start = None
    else:
        raise ValueError(f"Unbekannter Zeitraum: {period}")

    stmt = (
        select(BucketSnapshot)
        .where(
            BucketSnapshot.user_id == user_id,
            BucketSnapshot.bucket_id == bucket_id,
        )
        .order_by(BucketSnapshot.date.asc())
    )
    if start is not None:
        stmt = stmt.where(BucketSnapshot.date >= start)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "date": s.date.isoformat(),
            "total_value_chf": float(s.total_value_chf),
            "net_cash_flow_chf": float(s.net_cash_flow_chf),
            "running_peak_chf": float(s.running_peak_chf),
        }
        for s in rows
    ]


async def get_allocations_by_bucket(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Live-Allokation pro Bucket (cached prices, kein yfinance).

    Returns: Liste sortiert nach value_chf desc, mit name/color/value/pct.
    Nur aktive Buckets, PE/RE-System-Buckets ausgeschlossen (analog
    snapshot_service-Logik). Cash/Pension/Stocks/ETFs/Crypto/Commodities
    werden gezaehlt.
    """
    from services.utils import get_fx_rates_batch
    import asyncio as _asyncio

    from models.bucket import BucketSystemRole
    excluded_roles = {BucketSystemRole.real_estate, BucketSystemRole.private_equity}

    buckets_q = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user_id,
            Bucket.deleted_at.is_(None),
        )
    )
    buckets = list(buckets_q.scalars().all())
    eligible = [b for b in buckets if b.system_role not in excluded_roles]
    by_id = {b.id: b for b in eligible}

    pos_q = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.is_active.is_(True),
        )
    )
    positions = list(pos_q.scalars().all())

    from services.snapshot_service import _calc_position_value_chf
    fx_rates = await _asyncio.to_thread(get_fx_rates_batch)

    totals: dict = {b.id: 0.0 for b in eligible}
    for pos in positions:
        if pos.bucket_id is None or pos.bucket_id not in by_id:
            continue
        val = await _calc_position_value_chf(pos, fx_rates)
        totals[pos.bucket_id] += val

    total_sum = sum(totals.values())
    result = []
    for b in eligible:
        v = totals.get(b.id, 0.0)
        result.append({
            "bucket_id": str(b.id),
            "name": b.name,
            "color": b.color,
            "kind": b.kind.value if hasattr(b.kind, "value") else b.kind,
            "system_role": b.system_role.value if b.system_role else None,
            "value_chf": round(v, 2),
            "pct": round((v / total_sum) * 100, 2) if total_sum > 0 else 0.0,
        })
    result.sort(key=lambda r: r["value_chf"], reverse=True)
    return result


async def get_bucket_monthly_returns(
    db: AsyncSession, user_id: uuid.UUID, bucket_id: uuid.UUID
) -> dict:
    """Monatliche Returns + Jahres-Totale fuer einen Bucket (Tages-gechainter
    TWR, cashflow-bereinigt, ab Bucket-Erstellung).

    Pro Monat das Produkt der Tages-Sub-Returns ``(V_t - cf_t)/V_{t-1}`` der
    Snapshots dieses Monats. Da das Produkt assoziativ ist, reconciliert der
    Monats-Compound exakt mit dem YTD-TWR aus compare_to_benchmark (loest die
    fruehere Diskrepanz "Monats-Compound != YTD"). Snapshots vor
    ``bucket.created_at`` (proportionaler Backfill = Portfolio-Rendite je
    Bucket, kein bucket-spezifischer Wert) werden ausgeschlossen — sonst
    entsteht ein Phantom-Return im Erstellungsmonat.

    Schema identisch zu performance_history_service.get_monthly_returns:
      {"months": [{"year","month","return_pct"}], "annual_totals": {year: pct}}
    """
    bucket_q = await db.execute(
        select(Bucket).where(Bucket.id == bucket_id, Bucket.user_id == user_id)
    )
    bucket = bucket_q.scalar_one_or_none()
    if bucket is None:
        return {"months": [], "annual_totals": {}}

    inception = bucket.created_at.date()
    snap_q = await db.execute(
        select(BucketSnapshot)
        .where(
            BucketSnapshot.user_id == user_id,
            BucketSnapshot.bucket_id == bucket_id,
            BucketSnapshot.date >= inception,
        )
        .order_by(BucketSnapshot.date.asc())
    )
    snapshots = list(snap_q.scalars().all())
    if len(snapshots) < 2:
        return {"months": [], "annual_totals": {}}

    # Tages-Sub-Returns chainen, je Monat des spaeteren Snapshots akkumulieren.
    from collections import defaultdict
    monthly_wealth: dict[tuple[int, int], float] = defaultdict(lambda: 1.0)
    prev_value = float(snapshots[0].total_value_chf or 0)
    for s in snapshots[1:]:
        v = float(s.total_value_chf or 0)
        cf = float(s.net_cash_flow_chf or 0)
        if prev_value > 0:
            ret_factor = (v - cf) / prev_value
            if ret_factor > 0:
                monthly_wealth[(s.date.year, s.date.month)] *= ret_factor
        prev_value = v

    monthly_returns = [
        {"year": y, "month": m, "return_pct": round((monthly_wealth[(y, m)] - 1) * 100, 2)}
        for (y, m) in sorted(monthly_wealth.keys())
    ]

    # Jahres-Totale: compound aller Monate eines Jahres
    annual_totals: dict[int, float] = {}
    for year in set(m["year"] for m in monthly_returns):
        compound = 1.0
        for m in monthly_returns:
            if m["year"] == year:
                compound *= (1 + m["return_pct"] / 100)
        annual_totals[year] = round((compound - 1) * 100, 2)

    return {"months": monthly_returns, "annual_totals": annual_totals}


async def compare_to_benchmark(
    db: AsyncSession,
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
    *,
    period: str = "ytd",
) -> dict:
    """Bucket-Return vs konfigurierter Benchmark — like-for-like ueber das reale
    Bucket-Fenster.

    Cashflow-adjusted TWR via Tages-Sub-Return-Chaining (analog
    drawdown_service._build_wealth_index): Sub-Return Tag t =
    ``(V_t - cf_t) / V_{t-1}``, kumulierter Return = Π Sub-Returns - 1.

    Backfill-Klemmung (WICHTIG): bucket_snapshots vor ``bucket.created_at``
    stammen aus dem proportionalen Backfill (bucket_snapshot_backfill_service),
    der den Portfolio-Wert anteilig auf jeden Bucket verteilt. Dadurch traegt
    jeder Bucket fuer die Backfill-Periode die *Portfolio*-Rendite, nicht seine
    eigene — ein Vergleich ueber dieses Fenster ist kontaminiert und das Delta
    kann vorzeichen-falsch sein. Wir klemmen den Vergleich daher auf die reale
    Historie ab Erstellungsdatum und messen den Benchmark ueber exakt dasselbe
    Kalenderfenster (rows[0].date .. rows[-1].date). ``clamped`` signalisiert der
    UI, dass das Fenster kuerzer als der angefragte Zeitraum ist (z.B. "seit
    Bucket-Start" statt "YTD").

    Wenn Bucket keinen Benchmark gesetzt hat, ist der Vergleich `null`.
    """
    bucket_q = await db.execute(
        select(Bucket).where(Bucket.id == bucket_id, Bucket.user_id == user_id)
    )
    bucket = bucket_q.scalar_one_or_none()
    if bucket is None:
        return {}

    today = date.today()
    if period == "ytd":
        nominal_start: date | None = date(today.year, 1, 1)
    elif period == "1m":
        nominal_start = today - timedelta(days=30)
    elif period == "3m":
        nominal_start = today - timedelta(days=90)
    elif period == "6m":
        nominal_start = today - timedelta(days=180)
    elif period == "1y":
        nominal_start = today - timedelta(days=365)
    elif period == "all":
        nominal_start = None
    else:
        raise ValueError(f"Unbekannter Zeitraum: {period}")

    # Backfill-Klemmung: nie vor Bucket-Erstellung vergleichen (siehe Docstring).
    inception = bucket.created_at.date()
    effective_start = inception if nominal_start is None else max(nominal_start, inception)
    clamped = nominal_start is not None and effective_start > nominal_start

    snap_q = (
        select(BucketSnapshot)
        .where(
            BucketSnapshot.user_id == user_id,
            BucketSnapshot.bucket_id == bucket_id,
            BucketSnapshot.date >= effective_start,
        )
        .order_by(BucketSnapshot.date.asc())
    )
    rows = (await db.execute(snap_q)).scalars().all()

    bucket_return_pct: float | None = None
    if len(rows) >= 2:
        wealth = 1.0
        prev_value = float(rows[0].total_value_chf or 0)
        any_subreturn = False
        for snap in rows[1:]:
            value = float(snap.total_value_chf or 0)
            cf = float(snap.net_cash_flow_chf or 0)
            if prev_value > 0:
                ret_factor = (value - cf) / prev_value
                if ret_factor > 0:
                    wealth *= ret_factor
                    any_subreturn = True
            prev_value = value
        if any_subreturn:
            bucket_return_pct = round((wealth - 1) * 100, 2)

    benchmark_return_pct: float | None = None
    benchmark_name: str | None = None
    if bucket.benchmark and bucket_return_pct is not None:
        # Defense-in-depth: nur Allowlist-Ticker an yfinance reichen, auch wenn
        # die DB durch Altbestand einen unbekannten Wert enthielte (siehe
        # Audit H-1 + constants/benchmarks.py).
        from constants.benchmarks import ALLOWED_BENCHMARKS
        if bucket.benchmark not in ALLOWED_BENCHMARKS:
            logger.warning(
                "Bucket %s hat unzulaessigen Benchmark %r — uebersprungen",
                bucket_id, bucket.benchmark,
            )
        else:
            from services.benchmark_service import (
                get_benchmark_name,
                get_benchmark_window_return,
            )
            import asyncio as _asyncio
            benchmark_name = get_benchmark_name(bucket.benchmark)
            try:
                benchmark_return_pct = await _asyncio.to_thread(
                    get_benchmark_window_return,
                    bucket.benchmark,
                    rows[0].date,
                    rows[-1].date,
                )
            except Exception as e:
                logger.warning("Benchmark-Vergleich %s fehlgeschlagen: %s", bucket.benchmark, e)

    delta_pct = None
    if bucket_return_pct is not None and benchmark_return_pct is not None:
        delta_pct = round(bucket_return_pct - benchmark_return_pct, 2)

    # Das gemeldete Fenster-Start ist der erste reale Snapshot (rows[0].date),
    # nicht die Klemm-Grenze created_at — beide koennen 1-3 Tage auseinander-
    # liegen (Erstellung am Wochenende/Feiertag). So matcht das UI-Label
    # ("Perf. seit ...") exakt den gemessenen Zeitraum.
    reported_start = rows[0].date if rows else effective_start

    return {
        "bucket_id": str(bucket_id),
        "period": period,
        "effective_start": reported_start.isoformat(),
        "clamped": clamped,
        "bucket_return_pct": bucket_return_pct,
        "benchmark_ticker": bucket.benchmark,
        "benchmark_name": benchmark_name,
        "benchmark_return_pct": benchmark_return_pct,
        "delta_pct": delta_pct,
    }


async def get_bucket_cashflows(
    db: AsyncSession,
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """Netto-Cashflows in/aus dem Bucket fuer den Zeitraum.

    Verwendet die aktuelle position.bucket_id-Zuordnung (siehe Modul-Doc
    fuer Caveats bei Bucket-Wechseln).
    """
    stmt = (
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type.in_(INFLOW_TYPES), Transaction.total_chf),
                        (Transaction.type.in_(OUTFLOW_TYPES), -Transaction.total_chf),
                        else_=0,
                    )
                ),
                0,
            )
        )
        .join(Position, Transaction.position_id == Position.id)
        .where(
            Transaction.user_id == user_id,
            Position.bucket_id == bucket_id,
        )
    )
    if start is not None:
        stmt = stmt.where(Transaction.date >= start)
    if end is not None:
        stmt = stmt.where(Transaction.date <= end)

    result = await db.execute(stmt)
    net = result.scalar() or 0
    return {
        "net_cash_flow_chf": float(net),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    }
