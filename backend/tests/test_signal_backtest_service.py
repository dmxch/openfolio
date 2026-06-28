"""Per-Signal-Backtest: pure Aggregation + DB-Persistenz/Read (Regime-Historie)."""
from datetime import date

import pytest

from services.screening.backtest_harness import aggregate_per_signal
from services.signal_backtest_service import get_signal_backtest_history, persist_run

pytestmark = pytest.mark.asyncio


# --- Pure Aggregation ---

def test_aggregate_per_signal_present_absent():
    samples = [
        ({"insider_cluster": [1, 2]}, {30: 0.10, 60: 0.05}),
        ({"insider_cluster": True}, {30: 0.20}),
        ({"buyback": True}, {30: -0.05}),
    ]
    rows = aggregate_per_signal(samples, ["insider_cluster", "buyback"], {"insider_cluster": 3, "buyback": 2})
    by = {(r["signal_key"], r["window_days"]): r for r in rows}

    ic30 = by[("insider_cluster", 30)]
    assert ic30["n_present"] == 2 and ic30["n_absent"] == 1
    assert ic30["mean_present"] == pytest.approx(0.15)
    assert ic30["mean_absent"] == pytest.approx(-0.05)
    assert ic30["delta"] == pytest.approx(0.20)
    assert ic30["weight"] == 3
    assert ic30["hit_present"] == pytest.approx(1.0)

    ic60 = by[("insider_cluster", 60)]
    assert ic60["mean_present"] == pytest.approx(0.05)
    assert ic60["mean_absent"] is None
    assert ic60["delta"] is None

    bb30 = by[("buyback", 30)]
    assert bb30["n_present"] == 1 and bb30["n_absent"] == 2
    assert bb30["delta"] == pytest.approx(-0.20)


def test_aggregate_emits_all_windows():
    rows = aggregate_per_signal([], ["insider_cluster"], {})
    # 1 Signal × 3 Fenster (30/60/90), alle leer.
    assert len(rows) == 3
    assert all(r["n_present"] == 0 and r["mean_present"] is None for r in rows)


# --- DB Persistenz + Read ---

_ROWS = [
    {"signal_key": "insider_cluster", "window_days": 30, "weight": 3,
     "n_present": 2, "n_absent": 1, "mean_present": 0.15, "mean_absent": -0.05,
     "delta": 0.20, "hit_present": 1.0},
    {"signal_key": "buyback", "window_days": 30, "weight": 2,
     "n_present": 1, "n_absent": 2, "mean_present": -0.05, "mean_absent": 0.15,
     "delta": -0.20, "hit_present": 0.0},
]


async def test_persist_and_read(db):
    n = await persist_run(
        db, run_date=date(2026, 6, 1), rows=_ROWS, n_samples=3,
        earliest_scan=date(2026, 4, 1), latest_scan=date(2026, 6, 1),
    )
    assert n == 2
    hist = await get_signal_backtest_history(db, window_days=30)
    assert hist["has_data"] is True
    assert set(hist["by_signal"].keys()) == {"insider_cluster", "buyback"}
    assert hist["runs"] == ["2026-06-01"]
    ic = hist["by_signal"]["insider_cluster"][0]
    assert ic["delta"] == pytest.approx(0.20)
    assert ic["n_samples"] == 3
    assert ic["earliest_scan"] == "2026-04-01"


async def test_persist_is_idempotent_per_run_date(db):
    await persist_run(db, run_date=date(2026, 6, 1), rows=_ROWS, n_samples=3,
                      earliest_scan=date(2026, 4, 1), latest_scan=date(2026, 6, 1))
    # Erneuter Lauf am selben Tag mit nur 1 Zeile -> ersetzt (kein Duplikat).
    await persist_run(db, run_date=date(2026, 6, 1), rows=_ROWS[:1], n_samples=3,
                      earliest_scan=date(2026, 4, 1), latest_scan=date(2026, 6, 1))
    hist = await get_signal_backtest_history(db, window_days=30)
    assert set(hist["by_signal"].keys()) == {"insider_cluster"}


async def test_empty_window_has_no_data(db):
    await persist_run(db, run_date=date(2026, 6, 1), rows=_ROWS, n_samples=3,
                      earliest_scan=date(2026, 4, 1), latest_scan=date(2026, 6, 1))
    hist90 = await get_signal_backtest_history(db, window_days=90)
    assert hist90["has_data"] is False
    assert hist90["by_signal"] == {}
