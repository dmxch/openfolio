"""Persistenz + Read für die akkumulierte Per-Signal-Forward-Return-Historie.

Schreibpfad (Worker): ``persist_run`` legt für einen Lauf je Signal×Fenster eine
Zeile an — idempotent pro ``run_date`` (erneuter Lauf am selben Tag ersetzt).
Lesepfad (API): ``get_signal_backtest_history`` liefert die Zeitreihe je Signal,
über die sich die Regime-Stabilität (oder eben Instabilität) ablesen lässt.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.signal_backtest import SignalBacktestResult


async def persist_run(
    db: AsyncSession,
    *,
    run_date: date,
    rows: list[dict[str, Any]],
    n_samples: int,
    earliest_scan: date | None,
    latest_scan: date | None,
) -> int:
    """Schreibt einen Lauf (idempotent pro run_date). Gibt die Anzahl Zeilen zurück."""
    await db.execute(
        delete(SignalBacktestResult).where(SignalBacktestResult.run_date == run_date)
    )
    for r in rows:
        db.add(SignalBacktestResult(
            run_date=run_date,
            signal_key=r["signal_key"],
            window_days=r["window_days"],
            weight=r.get("weight", 0),
            n_present=r.get("n_present", 0),
            n_absent=r.get("n_absent", 0),
            mean_present=r.get("mean_present"),
            mean_absent=r.get("mean_absent"),
            delta=r.get("delta"),
            hit_present=r.get("hit_present"),
            n_samples=n_samples,
            earliest_scan=earliest_scan,
            latest_scan=latest_scan,
        ))
    await db.commit()
    return len(rows)


def _row_to_dict(r: SignalBacktestResult) -> dict[str, Any]:
    return {
        "run_date": r.run_date.isoformat() if r.run_date else None,
        "signal_key": r.signal_key,
        "window_days": r.window_days,
        "weight": r.weight,
        "n_present": r.n_present,
        "n_absent": r.n_absent,
        "mean_present": r.mean_present,
        "mean_absent": r.mean_absent,
        "delta": r.delta,
        "hit_present": r.hit_present,
        "n_samples": r.n_samples,
        "earliest_scan": r.earliest_scan.isoformat() if r.earliest_scan else None,
        "latest_scan": r.latest_scan.isoformat() if r.latest_scan else None,
    }


async def get_signal_backtest_history(
    db: AsyncSession,
    *,
    window_days: int = 30,
) -> dict[str, Any]:
    """Liefert die Per-Signal-Historie für ein Fenster, gruppiert nach Signal.

    Global (Universe-Screening, nicht user-scoped). ``has_data:false`` solange der
    erste Worker-Lauf noch aussteht — die UI zeigt dann einen Hinweis."""
    res = await db.execute(
        select(SignalBacktestResult)
        .where(SignalBacktestResult.window_days == window_days)
        .order_by(SignalBacktestResult.run_date, SignalBacktestResult.signal_key)
    )
    rows = res.scalars().all()
    if not rows:
        return {"has_data": False, "window_days": window_days, "by_signal": {}, "runs": []}

    by_signal: dict[str, list[dict[str, Any]]] = {}
    run_dates: list[str] = []
    for r in rows:
        d = _row_to_dict(r)
        by_signal.setdefault(r.signal_key, []).append(d)
        rd = d["run_date"]
        if rd and rd not in run_dates:
            run_dates.append(rd)
    return {
        "has_data": True,
        "window_days": window_days,
        "runs": run_dates,
        "by_signal": by_signal,
    }
