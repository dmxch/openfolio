"""Tests fuer die Bucket-Cashflow-Attribution der Snapshot-Regeneration.

Regression (Prod-Bug Satellite -49 %): rueckdatierte/nachgetragene Verkaeufe
liessen BucketSnapshot.net_cash_flow_chf stale (0), weil regenerate_snapshots
nur PortfolioSnapshots neu baute. Jetzt regeneriert es die Bucket-Reihe mit;
ein Verkauf erscheint als Outflow (negativ), nicht als Drawdown.

Hinweis: regenerate_snapshots selbst nutzt ``pg_insert`` und laeuft daher nur
auf PostgreSQL (nicht auf der SQLite-Test-DB) — die End-to-End-Verifikation
passiert gegen Prod. Hier wird die reine Attribution-Logik
(_bucket_cashflow_by_date) unit-getestet, die den Kern des Fixes bildet. Die
Drawdown-Konsumseite (net_cf → kein Phantom) deckt test_drawdown_service ab.
"""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

from models.transaction import TransactionType
from services.snapshot_service import _bucket_cashflow_by_date


def _txn(ptype, pos_id, d, total, bucket_at_sale=None):
    return SimpleNamespace(
        type=ptype, position_id=pos_id, date=d,
        total_chf=total, bucket_id_at_sale=bucket_at_sale,
    )


def test_sell_attributed_via_bucket_id_at_sale_as_outflow():
    bkt = uuid.uuid4()
    other = uuid.uuid4()
    pos_id = uuid.uuid4()
    # Position ist HEUTE in `other`, wurde aber aus `bkt` heraus verkauft.
    positions = {str(pos_id): SimpleNamespace(bucket_id=other)}
    d = date(2026, 6, 18)
    txns = [_txn(TransactionType.sell, pos_id, d, 8422.0, bucket_at_sale=bkt)]

    cf = _bucket_cashflow_by_date(txns, positions, {bkt, other})
    # Verkauf zaehlt zum Verkaufs-Bucket (bkt), NICHT zum aktuellen (other).
    assert cf[bkt][d] == -8422.0
    assert cf[other].get(d, 0.0) == 0.0


def test_buy_uses_current_bucket_and_inflow_positive():
    bkt = uuid.uuid4()
    pos_id = uuid.uuid4()
    positions = {str(pos_id): SimpleNamespace(bucket_id=bkt)}
    d = date(2026, 6, 10)
    txns = [_txn(TransactionType.buy, pos_id, d, 5000.0)]

    cf = _bucket_cashflow_by_date(txns, positions, {bkt})
    assert cf[bkt][d] == 5000.0


def test_multiple_sells_same_day_sum_and_fallback_to_position_bucket():
    bkt = uuid.uuid4()
    pos_a, pos_b = uuid.uuid4(), uuid.uuid4()
    positions = {
        str(pos_a): SimpleNamespace(bucket_id=bkt),
        str(pos_b): SimpleNamespace(bucket_id=bkt),
    }
    d = date(2026, 6, 15)
    txns = [
        _txn(TransactionType.sell, pos_a, d, 3849.0, bucket_at_sale=bkt),
        # bucket_id_at_sale fehlt → Fallback auf aktuelle Position.bucket_id.
        _txn(TransactionType.sell, pos_b, d, 2317.0, bucket_at_sale=None),
    ]
    cf = _bucket_cashflow_by_date(txns, positions, {bkt})
    assert cf[bkt][d] == -(3849.0 + 2317.0)


def test_ineligible_bucket_ignored():
    bkt = uuid.uuid4()  # eligible
    pe = uuid.uuid4()   # excluded (PE/Immobilien)
    pos_id = uuid.uuid4()
    positions = {str(pos_id): SimpleNamespace(bucket_id=pe)}
    d = date(2026, 6, 1)
    txns = [_txn(TransactionType.buy, pos_id, d, 9999.0)]
    cf = _bucket_cashflow_by_date(txns, positions, {bkt})  # pe nicht eligible
    assert bkt in cf
    assert pe not in cf
    assert cf[bkt].get(d, 0.0) == 0.0
