"""Tests fuer die Inception-Klemmung der Portfolio-Historie.

Regression (Prod-Befund 01.08.2026): Die Klemmung auf die echte Inception hing
an ``not downsample`` — sie war also nur auf dem raw-Pfad aktiv, den empirische
Auswertungen benutzen. Der DEFAULT-Pfad, den das UI und jeder normale Konsument
nimmt, lieferte weiter ein synthetisches Plateau: ``period=all`` behauptete
1713 Punkte lang einen Portfoliowert von CHF 139'719.13 ab dem Jahr 2000, weil
statische Cash-/Vorsorge-Positionen mit konstantem cost_basis rueckwaerts bis
zum angefragten Start emittiert wurden. ``summary.return_pct`` rechnete daraus
3.97 %.

Mit dem Downsampling hat die Frage, WO die Reihe beginnt, nichts zu tun.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_bucket, create_system_buckets
from services.history_service import get_portfolio_history

pytestmark = pytest.mark.asyncio


async def _user_mit_cash_und_aktie(db, d0: date):
    """Cash-Position OHNE Transaktion (der Ausloeser) + eine echte Position."""
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()

    # Statische Cash-Position: keine Transaktion, konstanter cost_basis.
    db.add(Position(
        user_id=user.id, bucket_id=bucket.id, ticker="CHF-KONTO",
        name="Kontokorrent", type=AssetType.cash, currency="CHF",
        shares=Decimal("1"), cost_basis_chf=Decimal("50000"), is_active=True,
    ))
    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="NESN.SW",
        name="Nestle", type=AssetType.stock, currency="CHF",
        shares=Decimal("100"), cost_basis_chf=Decimal("10000"), is_active=True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    db.add(Transaction(
        user_id=user.id, position_id=pos.id, type=TransactionType.buy,
        date=d0, shares=Decimal("100"), price_per_share=Decimal("100"),
        currency="CHF", total_chf=Decimal("10000"),
    ))
    await db.commit()
    return user


def _fake_yf(cal):
    def fake(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            cols[("Close", t)] = np.full(len(cal), 100.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df
    return fake


async def test_default_path_clamps_to_inception(db, monkeypatch):
    """period=all mit Default (downsample=True) darf NICHT vor der ersten
    Transaktion beginnen — sonst steht dort ein erfundenes Plateau."""
    today = date.today()
    inception = today - timedelta(days=400)
    user = await _user_mit_cash_und_aktie(db, inception)

    weit_davor = inception - timedelta(days=2000)
    cal = pd.date_range(weit_davor, today, freq="D")
    monkeypatch.setattr("services.history_service.yf_download", _fake_yf(cal))
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {})
    # Bindungsstelle: history_service ruft benchmark_quote_currency AUS
    # benchmark_service auf. Ein Patch auf cache_service._quote_currency
    # griffe ins Leere (nur LSE-Pence-Pfad) und liesse einen echten
    # yfinance-fast_info-Call fuer ^GSPC raus.
    monkeypatch.setattr(
        "services.benchmark_service.benchmark_quote_currency", lambda t: "CHF"
    )

    hist = await get_portfolio_history(db, weit_davor, today, user_id=user.id)
    punkte = hist["data"]
    assert punkte, "keine Datenpunkte"

    erster = date.fromisoformat(punkte[0]["date"])
    assert erster >= inception, (
        f"Reihe beginnt {erster}, also {(inception - erster).days} Tage vor der "
        f"Inception {inception} — synthetisches Pre-Inception-Plateau"
    )


async def test_raw_path_still_clamps(db, monkeypatch):
    """Gegenprobe: der raw-Pfad klemmt weiterhin (war nie kaputt)."""
    today = date.today()
    inception = today - timedelta(days=400)
    user = await _user_mit_cash_und_aktie(db, inception)

    weit_davor = inception - timedelta(days=2000)
    cal = pd.date_range(weit_davor, today, freq="D")
    monkeypatch.setattr("services.history_service.yf_download", _fake_yf(cal))
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {})
    # Bindungsstelle: history_service ruft benchmark_quote_currency AUS
    # benchmark_service auf. Ein Patch auf cache_service._quote_currency
    # griffe ins Leere (nur LSE-Pence-Pfad) und liesse einen echten
    # yfinance-fast_info-Call fuer ^GSPC raus.
    monkeypatch.setattr(
        "services.benchmark_service.benchmark_quote_currency", lambda t: "CHF"
    )

    hist = await get_portfolio_history(
        db, weit_davor, today, user_id=user.id, downsample=False
    )
    erster = date.fromisoformat(hist["data"][0]["date"])
    assert erster >= inception


async def test_downsampled_flag_is_reported(db, monkeypatch):
    """Der Konsument muss erkennen koennen, dass die Reihe ausgeduennt ist —
    sonst rechnet er Quartalsgrenzen auf einem 5-Tage-Raster aus."""
    today = date.today()
    inception = today - timedelta(days=800)  # > 1 Jahr → Downsampling greift
    user = await _user_mit_cash_und_aktie(db, inception)

    cal = pd.date_range(inception - timedelta(days=5), today, freq="D")
    monkeypatch.setattr("services.history_service.yf_download", _fake_yf(cal))
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {})
    # Bindungsstelle: history_service ruft benchmark_quote_currency AUS
    # benchmark_service auf. Ein Patch auf cache_service._quote_currency
    # griffe ins Leere (nur LSE-Pence-Pfad) und liesse einen echten
    # yfinance-fast_info-Call fuer ^GSPC raus.
    monkeypatch.setattr(
        "services.benchmark_service.benchmark_quote_currency", lambda t: "CHF"
    )

    lang = await get_portfolio_history(db, inception, today, user_id=user.id)
    assert lang["downsampled"] is True
    assert lang["sample_interval_days"] == 5

    kurz = await get_portfolio_history(
        db, today - timedelta(days=90), today, user_id=user.id
    )
    assert kurz["downsampled"] is False
    assert kurz["sample_interval_days"] == 1


async def test_user_without_any_transaction_is_still_clamped(db, monkeypatch):
    """Das Loch, das die erste Fassung offen liess.

    Ein Nutzer mit ausschliesslich statischen Salden — keine Transaktion, kein
    datiertes Edelmetall — hatte keine Inception und blieb deshalb ungeklemmt.
    Ausgerechnet diese Konstellation erzeugt das Plateau: der heutige Saldo wird
    rueckwaerts bis zum angefragten Start fortgeschrieben. Anker ist dann das
    Anlagedatum der Position.
    """
    today = date.today()
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    db.add(Position(
        user_id=user.id, bucket_id=bucket.id, ticker="CHF-KONTO",
        name="Kontokorrent", type=AssetType.cash, currency="CHF",
        shares=Decimal("1"), cost_basis_chf=Decimal("50000"), is_active=True,
    ))
    await db.commit()

    weit_davor = date(2000, 1, 1)
    cal = pd.date_range(weit_davor, today, freq="D")
    monkeypatch.setattr("services.history_service.yf_download", _fake_yf(cal))
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(
        "services.benchmark_service.benchmark_quote_currency", lambda t: "CHF"
    )

    hist = await get_portfolio_history(db, weit_davor, today, user_id=user.id)
    punkte = hist["data"]
    if punkte:
        erster = date.fromisoformat(punkte[0]["date"])
        assert erster.year >= today.year - 1, (
            f"Reihe beginnt {erster} — der Saldo wurde bis zum angefragten Start "
            f"zurueckgeschrieben, obwohl es dort noch nichts gab"
        )
    # Leer ist ebenfalls akzeptabel (Fenster vor Anlagedatum) — verboten ist nur
    # eine erfundene Reihe ab 2000.


async def test_window_entirely_before_inception_is_empty(db, monkeypatch):
    """Fenster komplett vor der Inception → leer, nicht Plateau."""
    today = date.today()
    inception = today - timedelta(days=400)
    user = await _user_mit_cash_und_aktie(db, inception)

    ende = inception - timedelta(days=10)
    start = ende - timedelta(days=200)
    cal = pd.date_range(start, today, freq="D")
    monkeypatch.setattr("services.history_service.yf_download", _fake_yf(cal))
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(
        "services.benchmark_service.benchmark_quote_currency", lambda t: "CHF"
    )

    hist = await get_portfolio_history(db, start, ende, user_id=user.id)
    assert hist["data"] == []
    assert hist["downsampled"] is False
    assert hist["sample_interval_days"] == 1


async def test_downsampling_preserves_extrema(db, monkeypatch):
    """Die Ausduennung darf Hoch- und Tiefpunkt nicht verschlucken.

    Prod-Beleg: das Allzeithoch vom 2025-08-13 fiel zwischen die 5-Tage-
    Stuetzpunkte; gemeldet wurde der Peak 54 Tage spaeter, bei nur 0.01 %
    Wertdifferenz. Die Hoehe ueberlebt die Ausduennung, das Datum nicht — und
    genau das Datum dokumentiert eine Drawdown-Bremse.
    """
    today = date.today()
    inception = today - timedelta(days=800)
    user = await _user_mit_cash_und_aktie(db, inception)

    cal = pd.date_range(inception - timedelta(days=5), today, freq="D")
    # Genau EIN Tag mit Ausreisser-Kurs, bewusst neben dem 5-Tage-Raster:
    # spike_idx 206 im Kalender, der 5 Tage VOR Fensterstart beginnt → Offset
    # 201 ab Fensterstart, und 201 mod 5 == 1. Der Punkt kann also nur ueber
    # den Extrema-Nachtrag in die Reihe kommen, nicht ueber das Raster.
    spike_idx = 206
    kurse = np.full(len(cal), 100.0)
    kurse[spike_idx] = 500.0
    spike_datum = cal[spike_idx].date().isoformat()

    def fake(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            cols[("Close", t)] = kurse if t == "NESN.SW" else np.full(len(cal), 100.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("services.history_service.yf_download", fake)
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(
        "services.benchmark_service.benchmark_quote_currency", lambda t: "CHF"
    )

    hist = await get_portfolio_history(db, inception, today, user_id=user.id)
    assert hist["downsampled"] is True, "Testaufbau trifft die Ausduennung nicht"

    daten = [p["date"] for p in hist["data"]]
    hoechster = max(hist["data"], key=lambda p: p["value"])
    assert hoechster["date"] == spike_datum, (
        f"Peak als {hoechster['date']} gemeldet statt {spike_datum} — die "
        f"Ausduennung hat den Extrempunkt verschluckt"
    )
    # Die zwei Kernrisiken der Insertion: Reihenfolge und Duplikate.
    assert daten == sorted(daten), "Reihe nach dem Nachtrag nicht chronologisch"
    assert len(daten) == len(set(daten)), "Doppelter Datenpunkt nach dem Nachtrag"
