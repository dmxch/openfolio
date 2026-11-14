"""Golden Master für Snapshot-Regeneration und Portfolio-Historie (Vollreview 11/2026).

Die Tagesschleifen beider Pfade laufen seit K007/K056 als reine Funktionen in
einem Thread. Diese Datei pinnt ihre Ausgabe für ein festes Depot: jede Zahl,
die ``regenerate_snapshots`` schreibt, und jede Antwort von
``get_portfolio_history`` geht in einen Hash ein. Die Soll-Hashes stammen aus
dem Stand VOR dem Umbau (HEAD 7daa0de) — ein abweichender Hash heisst, dass
sich für unveränderte Eingaben eine Zahl geändert hat.

Ausnahme, bewusst geändert in der Abnahme des Fix-Laufs: drei XIRR-Werte in
``test_total_and_monthly_returns_golden``. HEAD zählte die zwei
Wochenend-Buchungen des Depots doppelt, siehe dort.

Das Depot deckt die Sonderfälle ab, an denen die Pfade sich verzweigen:
Pence-Titel mit und ohne Kauf, Fremdwährung, Krypto mit Wochenend-Buchung,
Edelmetall ohne Transaktionen, Geldmarkt-ETF (count_as_cash), Cash mit Ein- und
Auszahlung, Vorsorge, Private Equity und Immobilien (ausgeschlossen), Verkauf
über den Bestand hinaus, Titel ohne Kursreihe, geschlossene Position.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from models.bucket import Bucket, BucketSnapshot, BucketSystemRole
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import AssetType, Position
from models.precious_metal_item import PreciousMetalItem
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_bucket, create_system_buckets, get_system_bucket

pytestmark = pytest.mark.asyncio

FIXED_TODAY = date(2025, 6, 30)


class _FixedDate(date):
    @classmethod
    def today(cls):
        return FIXED_TODAY


def _series(base: float, amp: float, period: float, cal: pd.DatetimeIndex) -> np.ndarray:
    return np.array([round(base + amp * math.sin(i / period), 4) for i in range(len(cal))])


def _fake_yf(all_tickers, **kwargs):
    """Deterministische Kurse. Aktien und FX nur an Werktagen, Krypto täglich."""
    days = pd.date_range("2023-12-15", FIXED_TODAY, freq="D")
    bdays = pd.bdate_range("2023-12-15", FIXED_TODAY)
    spec = {
        "AAA": (50.0, 6.0, 9.0, bdays),
        "USDX": (100.0, 12.0, 13.0, bdays),
        "SWDA.L": (9000.0, 400.0, 11.0, bdays),   # Pence
        "VUSA.L": (8000.0, 300.0, 17.0, bdays),   # Pence
        "GC=F": (2300.0, 150.0, 23.0, bdays),
        "BTC-USD": (60000.0, 9000.0, 19.0, days),
        "MMF": (100.0, 0.5, 31.0, bdays),
        "OLD": (20.0, 2.0, 5.0, bdays),
        "PEX": (10.0, 1.0, 5.0, bdays),
        "USDCHF=X": (0.90, 0.03, 29.0, bdays),
        "GBPCHF=X": (1.12, 0.04, 37.0, bdays),
        "^GSPC": (5000.0, 350.0, 41.0, bdays),
        "^SSMI": (11500.0, 500.0, 43.0, bdays),
    }
    cols = {}
    for t in all_tickers:
        if t in spec:
            base, amp, period, cal = spec[t]
            cols[("Close", t)] = pd.Series(_series(base, amp, period, cal), index=cal)
        else:
            cols[("Close", t)] = pd.Series(np.nan, index=bdays)  # z. B. NOPX: keine Reihe
    df = pd.DataFrame(cols).sort_index()
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    if len(all_tickers) == 1:
        # yf_download liefert bei genau einem Ticker flache Spalten.
        df = pd.DataFrame({"Close": df[("Close", all_tickers[0])]})
    return df


def _txn(uid, pos, ttype, d, shares, price, total, ccy="CHF", **extra):
    return Transaction(
        user_id=uid, position_id=pos.id, type=ttype, date=d,
        shares=Decimal(str(shares)), price_per_share=Decimal(str(price)),
        currency=ccy, total_chf=Decimal(str(total)),
        **{k: Decimal(str(v)) for k, v in extra.items()},
    )


async def build_depot(db) -> dict:
    user = User(email=f"gm{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    uid = user.id
    await create_system_buckets(db, uid)
    await db.commit()
    core = await create_bucket(db, uid, name="Core")
    sat = await create_bucket(db, uid, name="Satellite")
    await db.commit()
    liquid = await get_system_bucket(db, uid, BucketSystemRole.liquid_default)
    pe_b = await get_system_bucket(db, uid, BucketSystemRole.private_equity)
    re_b = await get_system_bucket(db, uid, BucketSystemRole.real_estate)
    pen_b = await get_system_bucket(db, uid, BucketSystemRole.pension)

    def pos(bucket, ticker, type_, ccy="CHF", shares="0", cost="0", **kw):
        return Position(
            user_id=uid, bucket_id=bucket.id, ticker=ticker, name=ticker, type=type_,
            currency=ccy, shares=Decimal(shares), cost_basis_chf=Decimal(cost),
            is_active=kw.pop("is_active", True), **kw,
        )

    p = {
        "AAA": pos(core, "AAA", AssetType.stock, shares="20", cost="1200"),
        "USDX": pos(sat, "USDX", AssetType.stock, "USD", "40", "3600"),
        "SWDA": pos(core, "SWDA.L", AssetType.etf, "GBP", "10", "990"),
        "VUSA": pos(core, "VUSA.L", AssetType.etf, "GBP", "5", "400"),
        "CASH": pos(core, "CASH_CHF", AssetType.cash, "CHF", "1", "20000"),
        "CASHUSD": pos(liquid, "CASH_USD", AssetType.cash, "USD", "1", "3000"),
        "PENS": pos(pen_b, "VIAC_3A", AssetType.pension, "CHF", "0", "40000"),
        "GOLD": pos(core, "XAUCHF=X", AssetType.commodity, "CHF", "3.2", "6500",
                    gold_org=True, current_price=Decimal("2100")),
        "BTC": pos(sat, "BTC", AssetType.crypto, "CHF", "0.03", "2340",
                   yfinance_ticker="BTC-USD", coingecko_id="bitcoin",
                   current_price=Decimal("58000")),
        "MMF": pos(liquid, "MMF", AssetType.etf, "CHF", "100", "10000", count_as_cash=True),
        "PE": pos(pe_b, "PEX", AssetType.private_equity, "CHF", "5", "25000"),
        "NOPX": pos(core, "NOPX", AssetType.stock, "CHF", "10", "300",
                    current_price=Decimal("33")),
        "OLD": pos(core, "OLD", AssetType.stock, "CHF", "0", "0", is_active=False),
        "RE": pos(re_b, "HAUS", AssetType.real_estate, "CHF", "1", "500000"),
    }
    db.add_all(p.values())
    await db.commit()
    for x in p.values():
        await db.refresh(x)

    T = TransactionType
    db.add_all([
        _txn(uid, p["AAA"], T.buy, date(2024, 1, 8), 100, 50, 5010),
        _txn(uid, p["OLD"], T.buy, date(2024, 1, 10), 10, 20, 200),
        _txn(uid, p["MMF"], T.buy, date(2024, 1, 22), 100, 100, 10000),
        _txn(uid, p["OLD"], T.sell, date(2024, 1, 31), 10, 25, 250,
             realized_pnl_chf=50, fees_chf=4),
        _txn(uid, p["USDX"], T.buy, date(2024, 2, 15), 40, 100, 3600, "USD"),
        _txn(uid, p["SWDA"], T.buy, date(2024, 3, 4), 10, 90, 990, "GBP"),
        _txn(uid, p["PE"], T.buy, date(2024, 4, 2), 5, 5000, 25000),
        _txn(uid, p["AAA"], T.buy, date(2024, 5, 10), 50, 55, 2755),
        _txn(uid, p["CASH"], T.deposit, date(2024, 6, 20), 0, 0, 5000),
        _txn(uid, p["BTC"], T.buy, date(2024, 7, 6), 0.05, 78000, 3900),       # Samstag
        _txn(uid, p["USDX"], T.dividend, date(2024, 8, 20), 0, 0, 18, "USD",
             gross_amount=24, tax_amount=4, fx_rate_to_chf=0.9, taxes_chf=3.6),
        _txn(uid, p["AAA"], T.sell, date(2024, 9, 13), 30, 60, 1800,
             realized_pnl_chf=246.5, fees_chf=9.5),
        _txn(uid, p["MMF"], T.capital_gain, date(2024, 9, 30), 0, 0, 41.2),
        _txn(uid, p["NOPX"], T.buy, date(2024, 10, 15), 10, 30, 300),
        _txn(uid, p["AAA"], T.delivery_in, date(2024, 11, 1), 10, 60, 600),
        _txn(uid, p["AAA"], T.fee, date(2024, 12, 31), 0, 0, 35),
        _txn(uid, p["BTC"], T.sell, date(2025, 1, 12), 0.02, 90000, 1800,      # Sonntag
             realized_pnl_chf=240, fees_chf=6),
        _txn(uid, p["CASH"], T.withdrawal, date(2025, 2, 5), 0, 0, 1500),
        _txn(uid, p["USDX"], T.dividend, date(2025, 2, 20), 0, 0, 21.5, "USD"),
        _txn(uid, p["AAA"], T.sell, date(2025, 3, 3), 200, 45, 9000,           # über Bestand
             realized_pnl_chf=-310.25, fees_chf=12),
        _txn(uid, p["CASH"], T.interest, date(2025, 3, 31), 0, 0, 12.4),
        _txn(uid, p["AAA"], T.buy, date(2025, 4, 10), 20, 60, 1200),
    ])
    db.add_all([
        PreciousMetalItem(
            user_id=uid, position_id=p["GOLD"].id, metal_type="gold", form="bar",
            weight_grams=Decimal("37.3242"), purchase_date=date(2024, 5, 14),
            purchase_price_chf=Decimal("2500"),
        ),
        PreciousMetalItem(
            user_id=uid, position_id=p["GOLD"].id, metal_type="gold", form="coin",
            weight_grams=Decimal("62.2070"), purchase_date=date(2024, 12, 3),
            purchase_price_chf=Decimal("4000"),
        ),
    ])
    await db.commit()
    return {"user": user, "core": core, "sat": sat, "positions": p}


def patch_market(monkeypatch) -> None:
    fx = {"USD": 0.9, "GBP": 1.1}
    monkeypatch.setattr("services.snapshot_service.yf_download", _fake_yf)
    monkeypatch.setattr("services.history_service.yf_download", _fake_yf)
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: dict(fx))
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: dict(fx))
    monkeypatch.setattr("services.cache.get", lambda k: None)
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "GBp")
    monkeypatch.setattr(
        "services.benchmark_service.benchmark_quote_currency",
        lambda t: "CHF" if t == "^SSMI" else "USD",
    )
    monkeypatch.setattr("services.snapshot_service.date", _FixedDate)
    monkeypatch.setattr("services.total_return_service.date", _FixedDate)
    monkeypatch.setattr("services.performance_history_service.date", _FixedDate)


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


async def regen_rows(db, uid) -> tuple[list, list]:
    snaps = (await db.execute(
        select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == uid)
        .order_by(PortfolioSnapshot.date)
    )).scalars().all()
    portfolio = [
        [s.date.isoformat(), f"{float(s.total_value_chf):.2f}",
         f"{float(s.cash_chf):.2f}", f"{float(s.net_cash_flow_chf):.2f}"]
        for s in snaps
    ]
    rows = (await db.execute(
        select(BucketSnapshot, Bucket)
        .join(Bucket, Bucket.id == BucketSnapshot.bucket_id)
        .where(BucketSnapshot.user_id == uid)
    )).all()
    buckets = sorted(
        [
            b.system_role.value if b.system_role else b.name, s.date.isoformat(),
            f"{float(s.total_value_chf):.2f}", f"{float(s.cash_chf):.2f}",
            f"{float(s.net_cash_flow_chf):.2f}", f"{float(s.running_peak_chf):.2f}",
            f"{float(s.wealth_index):.6f}", f"{float(s.running_peak_wealth_index):.6f}",
        ]
        for s, b in rows
    )
    return portfolio, buckets


# Soll-Werte aus dem Stand vor dem Umbau (HEAD 7daa0de), siehe Modul-Docstring.
REGEN_EXPECTED = {
    "result": [386, 2160, {"from": "2024-01-08", "to": "2025-06-30"}],
    "portfolio": "00c8f4957fa6808b",
    "buckets": "05896875c6fc069c",
}
HISTORY_EXPECTED = {
    "all_default": "c4f6e2b651274451",
    "all_raw": "c9b13409df731c6f",
    "liquid_smi": "ab89221362893eb6",
    "core_raw": "bd3d8d9cf0f9dad5",
    "sat_nobench": "7db15296264a5a51",
    "ytd_2025": "5b971b03b3dd5d73",
}
# Stand nach der XIRR-Korrektur (Nachtrag-Zeilen zählen einmal). Die Hashes von
# HEAD 7daa0de waren "3e320ba0a5b154bd" und "7170ec6fba7668ce"; sie unterscheiden
# sich nur in total_return_pct, ytd_pct und annual_totals[2025].
RETURNS_EXPECTED = {"total": "914999a78ba68490", "monthly": "d8f3e637ce251098"}


async def test_regenerate_snapshots_golden(db, monkeypatch):
    from services.snapshot_service import regenerate_snapshots

    depot = await build_depot(db)
    patch_market(monkeypatch)
    uid = depot["user"].id

    result = await regenerate_snapshots(db, uid)
    portfolio, buckets = await regen_rows(db, uid)
    got = {
        "result": [result.get("snapshots_created"), result.get("bucket_snapshots_created"),
                   result.get("date_range")],
        "portfolio": _digest(portfolio),
        "buckets": _digest(buckets),
    }
    # Stichproben neben den Hashes: ein abweichender Hash allein sagt nicht,
    # wie gross die Abweichung ist.
    assert portfolio[0] == ["2024-01-08", "72324.04", "59247.10", "5010.00"]
    assert portfolio[-1] == ["2025-06-30", "86811.02", "72803.84", "0.00"]
    assert buckets[0] == ["Core", "2024-01-08", "29576.94", "16500.00", "5010.00",
                          "29576.94", "1.000000", "1.000000"]
    assert got == REGEN_EXPECTED


def _history_cases(depot) -> dict[str, dict]:
    end = FIXED_TODAY
    return {
        "all_default": dict(start_date=date(2000, 1, 1), end_date=end),
        "all_raw": dict(start_date=date(2000, 1, 1), end_date=end, downsample=False),
        "liquid_smi": dict(start_date=date(2024, 9, 1), end_date=date(2025, 3, 31),
                           liquid=True, benchmark="^SSMI"),
        "core_raw": dict(start_date=date(2000, 1, 1), end_date=end, downsample=False,
                         bucket_id=depot["core"].id),
        "sat_nobench": dict(start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
                            benchmark="", bucket_id=depot["sat"].id),
        "ytd_2025": dict(start_date=date(2025, 1, 1), end_date=end),
    }


async def test_portfolio_history_golden(db, monkeypatch):
    from services.history_service import get_portfolio_history

    depot = await build_depot(db)
    patch_market(monkeypatch)
    uid = depot["user"].id

    got = {}
    for name, kwargs in _history_cases(depot).items():
        hist = await get_portfolio_history(db, user_id=uid, **kwargs)
        assert hist["data"], name
        got[name] = _digest(hist)
        if name == "all_raw":
            assert len(hist["data"]) == 540
            assert hist["data"][0] == {
                "date": "2024-01-08", "value": 48734.29, "portfolio_indexed": 100.0,
                "benchmark": 4700.42, "benchmark_indexed": 100.0,
            }
            assert hist["summary"] == {
                "start_value": 48734.29, "end_value": 65429.94,
                "return_pct": -0.86, "benchmark_return_pct": -3.63,
            }
    assert got == HISTORY_EXPECTED


SUMMARY = {
    "total_pnl_chf": 1830.4,
    "total_invested_chf": 81200.0,
    "positions": [
        {"type": "stock", "cost_basis_chf": 1200.0, "market_value_chf": 1530.4, "pnl_chf": 330.4},
        {"type": "pension", "cost_basis_chf": 40000.0, "market_value_chf": 40000.0, "pnl_chf": 0.0},
        {"type": "private_equity", "cost_basis_chf": 25000.0, "market_value_chf": 26500.0,
         "pnl_chf": 1500.0},
    ],
}


async def test_total_and_monthly_returns_golden(db, monkeypatch):
    """Total-Return (XIRR, YTD) und Monatsrenditen auf den regenerierten Snapshots.

    Drei Werte weichen bewusst von HEAD 7daa0de ab. Das Depot bucht am Samstag
    06.07.2024 einen Kauf über 3900 und am Sonntag 12.01.2025 einen Verkauf über
    1800. Der Regen trägt beide in der Montagszeile nach. HEAD zählte sie in der
    XIRR-Reihe am Buchungsdatum und noch einmal am Montag:

    - total_return_pct: -16.46 (HEAD) -> -15.41
    - ytd_pct und annual_totals[2025]: 5.28 (HEAD) -> 3.12

    Mit abgeschalteter Korrektur (``_rolled_up_snapshot_cfs`` liefert ``{}``)
    ergeben sich wieder genau die Hashes von HEAD: alle übrigen 37 Felder,
    darunter jede Monatsrendite, sind unverändert.
    ``test_period_xirr_equals_the_ledger_cash_flows`` rechnet die neuen Werte
    unabhängig nach.
    """
    from services.performance_history_service import get_monthly_returns
    from services.snapshot_service import regenerate_snapshots
    from services.total_return_service import get_total_return

    depot = await build_depot(db)
    patch_market(monkeypatch)
    uid = depot["user"].id
    await regenerate_snapshots(db, uid)

    total = await get_total_return(db, user_id=uid, summary=SUMMARY)
    monthly = await get_monthly_returns(db, user_id=uid)
    got = {"total": _digest(total), "monthly": _digest(monthly)}
    assert total["total_return_pct"] == -15.41
    assert (total["ytd_chf"], total["ytd_pct"]) == (2706.25, 3.12)
    assert (total["realized_pnl_chf"], total["dividends_gross_chf"]) == (226.25, 43.1)
    assert (total["ytd_realized_chf"], total["ytd_dividends_chf"]) == (-70.25, 21.5)
    assert monthly["annual_totals"] == {2025: 3.12}
    assert got == RETURNS_EXPECTED


async def test_returns_without_the_rollup_correction_match_head(db, monkeypatch):
    """Gegenprobe: Ohne die Nachtrag-Korrektur liefert der Arbeitsstand die
    Hashes von HEAD 7daa0de. Die Korrektur ist damit die einzige Ursache der
    drei geänderten Werte."""
    from services import performance_history_service as phs
    from services.performance_history_service import get_monthly_returns
    from services.snapshot_service import regenerate_snapshots
    from services.total_return_service import get_total_return

    depot = await build_depot(db)
    patch_market(monkeypatch)
    uid = depot["user"].id
    await regenerate_snapshots(db, uid)
    monkeypatch.setattr(phs, "_rolled_up_snapshot_cfs", lambda *args, **kwargs: {})

    total = await get_total_return(db, user_id=uid, summary=SUMMARY)
    monthly = await get_monthly_returns(db, user_id=uid)

    assert (total["total_return_pct"], total["ytd_pct"]) == (-16.46, 5.28)
    assert {"total": _digest(total), "monthly": _digest(monthly)} == {
        "total": "3e320ba0a5b154bd", "monthly": "7170ec6fba7668ce",
    }


@pytest.mark.parametrize("start, end", [
    (date(2024, 12, 31), FIXED_TODAY),       # YTD 2025, enthält den Sonntags-Verkauf
    (date(2023, 12, 31), date(2024, 12, 31)),  # 2024, enthält den Samstags-Kauf
    (date(2000, 1, 1), FIXED_TODAY),         # gesamt ab Startwert 0
    (date(2024, 1, 8), FIXED_TODAY),         # ab der ersten Zeile, wie get_total_return
], ids=["ytd_2025", "jahr_2024", "gesamt", "ab_erster_zeile"])
async def test_period_xirr_equals_the_ledger_cash_flows(db, monkeypatch, start, end):
    """Unabhängige Nachrechnung: Das Depot hat keinen Snapshot-Cashflow ohne
    Buchung. Die XIRR-Reihe muss deshalb genau aus Startwert, Buchungen an ihrem
    Datum und Endwert bestehen. Jede doppelt gezählte Buchung verschiebt die Rate."""
    from collections import defaultdict

    from constants.cashflow import INFLOW_TYPES, OUTFLOW_TYPES
    from services.performance_history_service import (
        _calculate_xirr_from_data, load_return_inputs, xirr,
    )
    from services.snapshot_service import regenerate_snapshots

    depot = await build_depot(db)
    patch_market(monkeypatch)
    uid = depot["user"].id
    await regenerate_snapshots(db, uid)
    snaps, txns = await load_return_inputs(db, uid)

    start_snap = next((s for s in reversed(snaps) if s.date <= start), None)
    end_snap = next(s for s in reversed(snaps) if s.date <= end)
    by_date = defaultdict(float)
    for t in txns:
        if not start < t.date <= end:
            continue
        if t.type in INFLOW_TYPES:
            by_date[t.date] -= float(t.total_chf)
        elif t.type in OUTFLOW_TYPES or t.type == TransactionType.dividend:
            by_date[t.date] += float(t.total_chf)
    flows = [(start_snap.date if start_snap else start,
              -float(start_snap.total_value_chf) if start_snap else 0.0)]
    flows += [(d, cf) for d, cf in sorted(by_date.items()) if cf]
    flows.append((end_snap.date, float(end_snap.total_value_chf)))

    rate = _calculate_xirr_from_data(snaps, txns, start, end)

    assert rate == pytest.approx(xirr(flows), abs=1e-9)
    if start == snaps[0].date:
        # Die Rate hinter total_return_pct, als Zahl gepinnt (HEAD: -0.164618).
        assert rate == pytest.approx(-0.154129, abs=1e-6)
