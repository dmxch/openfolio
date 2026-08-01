"""Tests fuer die Bucket-Cashflow-Attribution der Snapshot-Regeneration.

Regression (Prod-Bug Satellite -49 %): rueckdatierte/nachgetragene Verkaeufe
liessen BucketSnapshot.net_cash_flow_chf stale (0), weil regenerate_snapshots
nur PortfolioSnapshots neu baute. Jetzt regeneriert es die Bucket-Reihe mit;
ein Verkauf erscheint als Outflow (negativ), nicht als Drawdown.

Zweite Regression (Prod-Bug Satellite +55.6 % / Core -4.4 %, 2026-06-25): Der
Outflow muss demselben Bucket zugeordnet werden wie der Wert der Position, sonst
zerreisst es beide TWR-Ketten. Details im Docstring von _bucket_cashflow_by_date.

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

from models.position import AssetType
from models.transaction import TransactionType
from services.snapshot_service import _bucket_cashflow_by_date, _resolve_price_ticker


def _txn(ptype, pos_id, d, total, bucket_at_sale=None):
    return SimpleNamespace(
        type=ptype, position_id=pos_id, date=d,
        total_chf=total, bucket_id_at_sale=bucket_at_sale,
    )


def test_sell_follows_current_bucket_not_bucket_id_at_sale():
    """Regression Prod 2026-06-25 (RSG, CHF 9'786): Der Abfluss muss dort landen,
    wo der Wert-Replay den Wert der Position bucht — also bei
    ``Position.bucket_id``, nicht bei ``bucket_id_at_sale``.

    Frueher fiel der Cashflow nach ``sold_from``, der Wert aber nach ``current``.
    Beide TWR-Ketten brachen: ``sold_from`` bekam einen Abfluss ohne Wertrueckgang
    (Phantomgewinn +38.3 % an einem Tag), ``current`` den Wertrueckgang ohne
    Abfluss (Phantomverlust -8.9 %).
    """
    sold_from = uuid.uuid4()
    current = uuid.uuid4()
    pos_id = uuid.uuid4()
    # Position liegt HEUTE in `current` — dort bucht der Replay auch ihren Wert.
    positions = {str(pos_id): SimpleNamespace(bucket_id=current)}
    d = date(2026, 6, 25)
    txns = [_txn(TransactionType.sell, pos_id, d, 9786.0, bucket_at_sale=sold_from)]

    cf = _bucket_cashflow_by_date(txns, positions, {sold_from, current})
    assert cf[current][d] == -9786.0
    assert cf[sold_from].get(d, 0.0) == 0.0


def test_buy_uses_current_bucket_and_inflow_positive():
    bkt = uuid.uuid4()
    pos_id = uuid.uuid4()
    positions = {str(pos_id): SimpleNamespace(bucket_id=bkt)}
    d = date(2026, 6, 10)
    txns = [_txn(TransactionType.buy, pos_id, d, 5000.0)]

    cf = _bucket_cashflow_by_date(txns, positions, {bkt})
    assert cf[bkt][d] == 5000.0


def test_multiple_sells_same_day_sum_regardless_of_bucket_id_at_sale():
    bkt = uuid.uuid4()
    pos_a, pos_b = uuid.uuid4(), uuid.uuid4()
    positions = {
        str(pos_a): SimpleNamespace(bucket_id=bkt),
        str(pos_b): SimpleNamespace(bucket_id=bkt),
    }
    d = date(2026, 6, 15)
    txns = [
        # bucket_id_at_sale gesetzt bzw. fehlend — fuer die Snapshot-Reihe
        # irrelevant, beide folgen der aktuellen Position.bucket_id.
        _txn(TransactionType.sell, pos_a, d, 3849.0, bucket_at_sale=bkt),
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


# ---------- _resolve_price_ticker ------------------------------------------
#
# Regression (Prod: Hard Money): Eine transaktionslose Gold-Position wurde mit
# ihrem HEUTIGEN Wert als Konstante ueber die ganze Historie gelegt — 213 Tage
# derselbe Betrag, jeder TWR-Faktor exakt 1.0. Jetzt wird sie taeglich zum
# historischen Kurs bewertet; dafuer muessen Ticker-Sammlung und Bewertung
# denselben Ticker waehlen, sonst laedt der Batch einen Kurs, den niemand
# abfragt. Genau das sichert diese Funktion ab.

def _pos(ticker, *, ptype=AssetType.stock, gold_org=False, yf=None, currency="CHF"):
    return SimpleNamespace(
        ticker=ticker, yfinance_ticker=yf, type=ptype,
        gold_org=gold_org, currency=currency,
    )


def test_resolve_price_ticker_gold_uses_futures_contract():
    """XAUCHF=X gibt es auf yfinance nicht — Gold laeuft ueber den Future."""
    yf_ticker, currency = _resolve_price_ticker(
        _pos("XAUCHF=X", ptype=AssetType.commodity, gold_org=True)
    )
    assert yf_ticker != "XAUCHF=X"
    assert currency == "USD"


def test_resolve_price_ticker_crypto_is_usd_even_if_position_says_chf():
    """Crypto quotiert in USD, auch wenn pos.currency faelschlich CHF sagt —
    sonst wird der USD-Preis als CHF gelesen (~25 % zu hoch)."""
    _, currency = _resolve_price_ticker(
        _pos("BTC-USD", ptype=AssetType.crypto, currency="CHF")
    )
    assert currency == "USD"


def test_resolve_price_ticker_plain_position_unchanged():
    """Normalfall: yfinance_ticker schlaegt ticker, Waehrung bleibt."""
    yf_ticker, currency = _resolve_price_ticker(
        _pos("ROG", yf="ROG.SW", currency="CHF")
    )
    assert (yf_ticker, currency) == ("ROG.SW", "CHF")
