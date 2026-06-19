"""Tests fuer services/drawdown_service.py.

Kern-Invariante (Bug-Fix): Drawdown + Drawdown-Bremse rechnen auf der
cash-flow-bereinigten, indexierten Serie (portfolio_indexed), NICHT auf rohen
Snapshot-Marktwerten inkl. Netto-Einzahlungen. Reine Einzahlungen / DCA duerfen
daher KEINEN Drawdown vortaeuschen.

Coverage:
  - _running_peak_drawdown: Index-Invarianten (trough nie ueber peak, flat → 0,
    echter Einbruch wird erkannt, Bremse feuert bei Schwellen-Ueberschreitung,
    CHF-Anker konsistent mit den Prozenten).
  - get_max_drawdown(bucket_id=...): Bucket-Drawdown via geguardeten
    BucketSnapshot-TWR — reine Einzahlungen → ~0% Drawdown, echter Einbruch
    erkannt, Zero-Collapse-Tag wird neutralisiert (kein -100% Phantom-Brake).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from models.bucket import BucketSnapshot
from models.user import User, UserSettings
from services.bucket_service import create_bucket, create_system_buckets
from services.drawdown_service import _running_peak_drawdown, get_max_drawdown

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Unit-Tests auf der reinen Index-Mechanik (kein DB/Netz)
# ---------------------------------------------------------------------------

def test_flat_index_with_rising_rawvalue_has_zero_drawdown():
    """Index flach (nur Einzahlungen), Rohwert steigt → Drawdown 0, keine Bremse.

    Genau der Produktions-Fehlerfall: trough_value (roh) liegt UEBER peak_value
    (roh), weil zwischendrin eingezahlt wurde. max_drawdown_pct/Bremse rechnen
    aber auf dem flachen Index und melden korrekt 0.
    """
    d0 = date(2026, 1, 1)
    # (date, wealth_index, raw_value): Index konstant 1.0, Rohwert verdreifacht.
    series = [
        (d0, 1.0, 30000.0),
        (d0 + timedelta(days=30), 1.0, 60000.0),
        (d0 + timedelta(days=60), 1.0, 90000.0),
    ]
    out = _running_peak_drawdown(series, threshold=6.0)
    assert out["max_drawdown_pct"] == 0.0
    assert out["current_vs_peak_pct"] == 0.0
    assert out["drawdown_brake_active"] is False


def test_trough_index_never_above_peak_index():
    """Egal wie die Rohwerte laufen — der Drawdown wird am Index gemessen, also
    kann der Index-Trough nie ueber dem Index-Peak liegen (dd_pct <= 0).

    Zusaetzlich (Follow-up-Fix): die CHF-Anker sind aus DERSELBEN indexierten
    Serie abgeleitet, also gilt trough_value_chf <= peak_value_chf — obwohl die
    nominalen Rohwerte (v) per Einzahlung in die Gegenrichtung laufen.
    """
    d0 = date(2026, 1, 1)
    series = [
        (d0, 1.00, 10000.0),
        (d0 + timedelta(days=1), 1.20, 90000.0),   # Index-Peak, Rohwert via Einzahlung hoch
        (d0 + timedelta(days=2), 1.05, 95000.0),   # Index runter, Rohwert weiter hoch
        (d0 + timedelta(days=3), 1.10, 120000.0),
    ]
    out = _running_peak_drawdown(series, threshold=6.0)
    # Drawdown ist negativ und entsteht am Index-Peak (1.20) → Trough (1.05):
    assert out["max_drawdown_pct"] == pytest.approx((1.05 / 1.20 - 1) * 100, abs=0.01)
    # current vs peak ebenfalls am Index: 1.10 vs 1.20
    assert out["current_vs_peak_pct"] == pytest.approx((1.10 / 1.20 - 1) * 100, abs=0.01)
    # Index-Drawdown ist immer <= 0
    assert out["max_drawdown_pct"] <= 0.0
    # CHF-Anker konsistent trotz gegenlaeufiger Rohwerte (peak-Roh 90k < trough-Roh 95k):
    assert out["trough_value_chf"] <= out["peak_value_chf"]


def test_chf_anchors_consistent_with_percentages():
    """Die CHF-Anker erfuellen die geforderten Invarianten exakt (innerhalb Rundung):
    max_drawdown_pct aus peak/trough, current_vs_peak_pct aus current/running_peak,
    trough <= peak — auch wenn die nominalen Rohwerte cash-flow-kontaminiert sind."""
    d0 = date(2026, 1, 1)
    # Index: 1.00 → 1.30 (Peak) → 1.04 (Trough, -20%) → 1.17 (Erholung, aktuell).
    # Rohwerte absichtlich gegenlaeufig aufgeblaeht (Einzahlungen).
    series = [
        (d0, 1.00, 50000.0),
        (d0 + timedelta(days=1), 1.30, 60000.0),
        (d0 + timedelta(days=2), 1.04, 95000.0),   # nominaler "trough" > nominaler "peak"
        (d0 + timedelta(days=3), 1.17, 174128.77),  # current real
    ]
    out = _running_peak_drawdown(series, threshold=6.0)

    peak = out["peak_value_chf"]
    trough = out["trough_value_chf"]
    rpeak = out["running_peak_value_chf"]
    current = out["current_value_chf"]

    # current_value_chf bleibt der reale nominale Buchwert
    assert current == pytest.approx(174128.77, abs=0.01)
    # Invariante 1: trough <= peak
    assert trough <= peak
    # Invariante 2: max_drawdown_pct == (trough - peak)/peak
    assert out["max_drawdown_pct"] == pytest.approx((trough - peak) / peak * 100, abs=0.05)
    # Invariante 3: current_vs_peak_pct == (current - running_peak)/running_peak
    assert out["current_vs_peak_pct"] == pytest.approx(
        (current - rpeak) / rpeak * 100, abs=0.05
    )
    # max_drawdown entspricht dem Index-Verhaeltnis 1.04/1.30 - 1 = -20%
    assert out["max_drawdown_pct"] == pytest.approx(-20.0, abs=0.05)


def test_real_drawdown_triggers_brake():
    """Echter Kursverfall (Index faellt 20%) → Bremse feuert bei threshold 15."""
    d0 = date(2026, 1, 1)
    series = [
        (d0, 1.00, 1000.0),
        (d0 + timedelta(days=1), 1.00, 1000.0),
        (d0 + timedelta(days=2), 0.80, 800.0),
    ]
    out = _running_peak_drawdown(series, threshold=15.0)
    assert out["max_drawdown_pct"] == pytest.approx(-20.0, abs=0.01)
    assert out["current_vs_peak_pct"] == pytest.approx(-20.0, abs=0.01)
    assert out["drawdown_brake_active"] is True


def test_brake_not_active_below_threshold():
    """Index-Drawdown 4% < Schwelle 6% → keine Bremse."""
    d0 = date(2026, 1, 1)
    series = [
        (d0, 1.00, 1000.0),
        (d0 + timedelta(days=1), 0.96, 960.0),
    ]
    out = _running_peak_drawdown(series, threshold=6.0)
    assert out["current_vs_peak_pct"] == pytest.approx(-4.0, abs=0.01)
    assert out["drawdown_brake_active"] is False


# ---------------------------------------------------------------------------
# Integration: get_max_drawdown(bucket_id=...) via geguardeten BucketSnapshot-TWR
# ---------------------------------------------------------------------------

async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    return user


async def _bucket_with_snaps(db, user, snaps, *, threshold=6.0):
    """snaps = [(days_ago, total_value_chf, net_cash_flow_chf)] chronologisch.

    Erzeugt einen user-Bucket (created_at vor dem aeltesten Snapshot, sonst klemmt
    die Inception-Klemmung alles weg) + die BucketSnapshots.
    """
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(
        db, user.id, name="Core",
        risk_rules={"drawdown_brake_pct": threshold, "drawdown_brake_active": True},
    )
    await db.commit()
    today = date.today()
    oldest = max(d for d, _, _ in snaps)
    bucket.created_at = datetime.combine(
        today - timedelta(days=oldest + 1), datetime.min.time()
    )
    await db.commit()
    for days_ago, total, cf in snaps:
        db.add(BucketSnapshot(
            user_id=user.id,
            bucket_id=bucket.id,
            date=today - timedelta(days=days_ago),
            total_value_chf=Decimal(str(total)),
            cash_chf=Decimal("0"),
            net_cash_flow_chf=Decimal(str(cf)),
            running_peak_chf=Decimal(str(total)),
        ))
    await db.commit()
    return bucket


async def test_pure_deposits_flat_returns_zero_drawdown(db):
    """Bug-Invariante: reine Einzahlungen (DCA) + flache Returns → Drawdown ~0%,
    Bremse INAKTIV. Buchwert verdreifacht (1000→3000) rein via net_cash_flow.

    Vor dem Fix rechnete die Bremse auf rohen Snapshot-Marktwerten inkl.
    Einzahlungen und meldete einen riesigen Phantom-Drawdown.
    """
    user = await _make_user(db)
    bucket = await _bucket_with_snaps(db, user, [
        (60, 1000, 0),
        (30, 2000, 1000),   # +1000 Einzahlung → ret=(2000-1000)/1000=1.0
        (0, 3000, 1000),    # +1000 Einzahlung → ret=(3000-1000)/2000=1.0
    ])
    dd = await get_max_drawdown(
        db, user.id, period="all", bucket_id=bucket.id, brake_threshold_pct=6.0
    )
    assert dd["snapshots_count"] == 3
    assert dd["max_drawdown_pct"] == pytest.approx(0.0, abs=0.1)
    assert dd["current_vs_peak_pct"] == pytest.approx(0.0, abs=0.1)
    assert dd["drawdown_brake_active"] is False
    # current_value_chf = realer Buchwert des letzten Snapshots (nicht Phantom).
    assert dd["current_value_chf"] == pytest.approx(3000.0, abs=0.01)


async def test_real_drop_detected(db):
    """Sanity: ein echter Markteinbruch (cf=0) wird erkannt und feuert die
    Bremse (sonst koennte der Fix einfach 'immer 0' liefern)."""
    user = await _make_user(db)
    bucket = await _bucket_with_snaps(db, user, [
        (40, 1000, 0),
        (20, 850, 0),   # -15%
        (0, 700, 0),    # kumuliert ~ -30%
    ])
    dd = await get_max_drawdown(
        db, user.id, period="all", bucket_id=bucket.id, brake_threshold_pct=6.0
    )
    assert dd["max_drawdown_pct"] < -25.0
    assert dd["drawdown_brake_active"] is True
    assert dd["current_value_chf"] == pytest.approx(700.0, abs=0.01)


async def test_zero_collapse_day_is_guarded(db):
    """Regression (der in Prod gefundene Bug): ein einzelner Tag mit kollabiertem
    Bucket-Wert (z.B. alle Preise fehlen → total 0) darf den Index NICHT permanent
    nullen. Die history_service-Rekonstruktion tat genau das (-100% Phantom-Brake
    fuer Core auf period=all); der geguardete Snapshot-TWR neutralisiert den Tag."""
    user = await _make_user(db)
    bucket = await _bucket_with_snaps(db, user, [
        (30, 1000, 0),
        (20, 0, 0),     # Daten-Glitch: Wert kollabiert auf 0
        (10, 1000, 0),  # erholt sich
        (0, 1000, 0),
    ])
    dd = await get_max_drawdown(
        db, user.id, period="all", bucket_id=bucket.id, brake_threshold_pct=6.0
    )
    # Kein -100%: ret<=0 am Glitch-Tag → factor 1.0 (neutralisiert).
    assert dd["max_drawdown_pct"] == pytest.approx(0.0, abs=0.1)
    assert dd["drawdown_brake_active"] is False
    assert dd["current_value_chf"] == pytest.approx(1000.0, abs=0.01)
