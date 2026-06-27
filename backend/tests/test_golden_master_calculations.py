"""Golden-Master / Charakterisierungs-Tests fuer die Korrektheits-Invarianten.

Referenziert aus CLAUDE.md ("Korrektheits-Invarianten — das Vertrauen in die
Zahlen"). Zweck: die DEFINITIONEN der Kern-Berechnungen mit exakt von Hand
berechneten Soll-Werten festnageln, damit eine *stille* Aenderung an einer
Formel (Annualisierungs-Basis, Dietz-Gewichtung, EMA-Periode, Cost-Basis-
Methode) den Test sofort rot faerbt — und man drumherum trotzdem frei
refactoren kann.

Abgedeckte Invarianten:
  1. Rendite: cost_basis_chf (inkl. Gebuehren, Weighted-Average-Sell) + perf_pct
  2. Jahres/YTD-Total = XIRR (MWR), Basis 365 Tage
  3. Monatlich = Modified Dietz (Tages-Gewichtung der Cashflows)
  4. Signal: MRS = EMA(13) auf Weekly-Daten (Ratio Stock/Benchmark)

Die Breakout-Definition (Donchian 20d, strict >, Volumen >= 1.5x) ist bereits
in tests/test_chart_pattern_detectors.py::TestBreakoutConfirm festgenagelt und
wird hier bewusst NICHT dupliziert.

Werte aendern sich nur mit bewusster Definitions-Migration — siehe CLAUDE.md.
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from models.bucket import BucketSystemRole
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import AssetType, Position, PriceSource, PricingMode
from models.transaction import Transaction, TransactionType
from services.performance_history_service import (
    _calculate_xirr_from_data,
    _monthly_returns_modified_dietz,
    calculate_xirr_for_period,
    deannualize_xirr,
    xirr,
)
from services.recalculate_service import _calculate_position_values
from services.snapshot_service import (
    _EXCLUDED_FROM_BUCKET_SUMS,
    _LIQUID_ASSET_TYPES,
    _calc_portfolio_value_fast,
    _calc_position_value_chf,
)
from services.stock_scorer import _compute_mrs_from_close


# --- Invariante 2: XIRR (MWR), Annualisierungs-Basis 365 Tage ---

class TestGoldenMasterXIRR:
    """Exakte Pins auf 365-Tage-Faellen — annualisierte Rate als Dezimalbruch.

    Bewusst 2023->2024 (kein Schaltjahr = exakt 365 Tage), damit der Exponent
    (d-d0).days/365.0 == 1.0 ist und die Soll-Rate EXAKT herauskommt. Eine
    Aenderung der Basis (z.B. 360 oder 365.25) bricht diese Pins.
    """

    def test_one_year_ten_percent_exact(self):
        # -1000 -> +1100 ueber exakt 365 Tage => 1+r = 1.1 => r = 0.10
        result = xirr([(date(2023, 1, 1), -1000), (date(2024, 1, 1), 1100)])
        assert result == pytest.approx(0.10, abs=1e-6)

    def test_one_year_doubling_exact(self):
        # -1000 -> +2000 ueber 365 Tage => r = 1.0 (100 %)
        result = xirr([(date(2023, 1, 1), -1000), (date(2024, 1, 1), 2000)])
        assert result == pytest.approx(1.0, abs=1e-6)

    def test_one_year_loss_exact(self):
        # -1000 -> +900 ueber 365 Tage => r = -0.10
        result = xirr([(date(2023, 1, 1), -1000), (date(2024, 1, 1), 900)])
        assert result == pytest.approx(-0.10, abs=1e-6)

    def test_same_day_cashflows_returns_none(self):
        # Degenerierter Fall (alle CF am selben Tag) -> None, nicht -99 %.
        assert xirr([(date(2024, 1, 1), -1000), (date(2024, 1, 1), 1000)]) is None

    def test_insufficient_cashflows_returns_none(self):
        assert xirr([]) is None
        assert xirr([(date(2024, 1, 1), -1000)]) is None


# --- Invariante 1: cost_basis_chf (inkl. Gebuehren, Weighted-Average-Sell) ---

def _txn(ttype, shares, total_chf, fees_chf=0.0, fx=1.0):
    t = MagicMock()
    t.type = ttype
    t.shares = shares
    t.total_chf = total_chf
    t.fees_chf = fees_chf
    t.fx_rate_to_chf = fx
    return t


class TestGoldenMasterCostBasis:
    """cost_basis_chf = Summe der total_chf (Gebuehren sind bereits darin),
    Sells reduzieren proportional ueber den gewichteten Durchschnittspreis."""

    def test_cost_basis_and_weighted_average_realized_pnl(self):
        # Buy 10 @ total 1000 (inkl. Gebuehren) -> cost 1000
        # Buy 10 @ total 1400               -> cost 2400, shares 20
        # Sell 10 @ proceeds 1500:
        #   avg_cost = 2400/20 = 120; allocated = 120*10 = 1200
        #   realized = 1500 - 1200 - 0 (fees) = 300
        #   cost_basis *= (1 - 10/20) = 1200; shares 10
        txns = [
            _txn(TransactionType.buy, 10, 1000.0),
            _txn(TransactionType.buy, 10, 1400.0),
            _txn(TransactionType.sell, 10, 1500.0),
        ]
        shares, cost, realized = _calculate_position_values(txns)

        assert shares == pytest.approx(10.0)
        assert cost == pytest.approx(1200.0)
        assert realized == pytest.approx(300.0)
        # Realized + zugeordnete Cost-Basis werden auf dem Sell festgehalten
        assert txns[2].realized_pnl_chf == 300.0
        assert txns[2].cost_basis_at_sale == 1200.0

    def test_perf_pct_definition(self):
        # perf_pct = ((value_chf / cost_basis_chf) - 1) * 100
        # value_chf = shares * price * fx. Hier explizit als Definitions-Pin,
        # da die Formel selbst in get_portfolio_summary() inline lebt.
        cost_basis_chf = 1200.0
        value_chf = 12 * 130.0 * 1.0  # shares * price * fx = 1560
        perf_pct = ((value_chf / cost_basis_chf) - 1) * 100
        assert perf_pct == pytest.approx(30.0)


# --- Invariante 3: Modified Dietz (monatlich, tages-gewichtete Cashflows) ---

class TestGoldenMasterModifiedDietz:
    """R = (V_end - V_start - sum(CF)) / (V_start + sum(w_i * CF_i)),
    w_i = (days_in_month - (day-1)) / days_in_month."""

    async def test_monthly_returns_with_mid_month_cashflow(self, db):
        uid = __import__("uuid").uuid4()
        pos_id = __import__("uuid").uuid4()

        # Jan: 10000 -> 11000, keine Cashflows => +10.00 %
        # Feb (Schaltjahr, 29 Tage): Start 11000 (= Jan-Ende), Ende 13200,
        #   Buy 1000 am 15.2. => weight = (29-14)/29 = 15/29
        #   weighted_cf = 1000 * 15/29 = 517.2414
        #   R = (13200 - 11000 - 1000) / (11000 + 517.2414) * 100 = 10.42 %
        db.add_all([
            PortfolioSnapshot(user_id=uid, date=date(2024, 1, 1),
                              total_value_chf=Decimal("10000"),
                              cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0")),
            PortfolioSnapshot(user_id=uid, date=date(2024, 1, 31),
                              total_value_chf=Decimal("11000"),
                              cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0")),
            PortfolioSnapshot(user_id=uid, date=date(2024, 2, 29),
                              total_value_chf=Decimal("13200"),
                              cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0")),
        ])
        db.add(Transaction(
            user_id=uid, position_id=pos_id, type=TransactionType.buy,
            date=date(2024, 2, 15), shares=Decimal("1"),
            price_per_share=Decimal("1000"), currency="CHF",
            total_chf=Decimal("1000"),
        ))
        await db.commit()

        res = await _monthly_returns_modified_dietz(db, uid, date(2024, 1, 1))
        by = {(r["year"], r["month"]): r["return_pct"] for r in res}

        assert by[(2024, 1)] == pytest.approx(10.0, abs=0.01)
        assert by[(2024, 2)] == pytest.approx(10.42, abs=0.01)


# --- Invariante 4: MRS = EMA(13) auf Weekly-Daten, Ratio Stock/Benchmark ---

class TestGoldenMasterMRS:
    """Mansfield RS = (rs.iloc[-1] / EMA13(rs).iloc[-1] - 1) * 100,
    rs = stock_weekly / bench_weekly, EMA mit adjust=False (alpha = 2/14 = 1/7)."""

    def _fridays(self, n):
        return pd.date_range("2024-01-05", periods=n, freq="W-FRI")

    def test_equal_series_is_zero(self):
        idx = self._fridays(20)
        flat = pd.Series([100.0] * 20, index=idx)
        assert _compute_mrs_from_close(flat, flat) == pytest.approx(0.0, abs=0.001)

    def test_ema13_step_response_exact(self):
        # bench konstant 100; stock 19x 100, dann 107 => rs = [1.0]*19 + [1.07]
        # EMA(13, adjust=False), alpha = 1/7:
        #   ema_last = 6/7 * 1.0 + 1/7 * 1.07 = 1.01
        #   mrs = (1.07 / 1.01 - 1) * 100 = 5.94
        # Pinnt span=13 (alpha=1/7) UND adjust=False UND Ratio-Richtung.
        idx = self._fridays(20)
        bench = pd.Series([100.0] * 20, index=idx)
        stock = pd.Series([100.0] * 19 + [107.0], index=idx)
        assert _compute_mrs_from_close(stock, bench) == pytest.approx(5.94, abs=0.01)

    def test_insufficient_weeks_returns_none(self):
        # < period + 1 (= 14) gemeinsame Wochen -> None
        idx = self._fridays(10)
        s = pd.Series([100.0] * 10, index=idx)
        assert _compute_mrs_from_close(s, s) is None


# ======================================================================
# XIRR / deannualize / period-XIRR — Edge-Cases (Workflow gen+verifiziert)
# ======================================================================

# ======================================================================
# Golden-Master-Erweiterung: XIRR / deannualize_xirr / period-XIRR
# Ergaenzt TestGoldenMasterXIRR (nur 1-CF-365-Tage-Faelle) um Mehr-Cashflow-,
# Teiljahr-, Totalverlust-, Reihenfolge- und Vorzeichen-Pins.
# Quelle: backend/services/performance_history_service.py
#   xirr (Zeile 24, 365.0-Basis in Zeile 50, -0.99-Clamp in Zeile 72/75)
#   deannualize_xirr (Zeile 94, Formel Zeile 98, Guard Zeile 96/97)
#   _calculate_xirr_from_data (Zeile 128, Vorzeichen Zeile 164/177, Merge Zeile 187)
#   calculate_xirr_for_period (Zeile 101, DB-Pfad)
# ======================================================================


class TestGoldenMasterXIRRMultiCashflow:
    """Exakte Pins mit MEHREREN Cashflows bei ganzzahligen Jahres-Exponenten.

    Bewusst kalenderjahresweise 2022->2023->2024 gewaehlt: keines dieser
    Jahre ist ein Schaltjahr, jeder Schritt ist exakt 365 Tage, also sind
    die Exponenten (d-d0).days/365.0 exakt 0, 1, 2 (bzw. 0, -1, -2). Damit
    ist die NPV-Nullstelle von Hand loesbar und die 365er-Annualisierungs-
    Basis (Zeile 50) ohne Toleranz-Spielraum festgenagelt.
    """

    def test_two_intermediate_cashflows_exact_ten_percent(self):
        # Cashflows (bereits sortiert, Aufrufer-Pflicht laut Signatur):
        #   2022-01-01: -1000  (exp 0)
        #   2023-01-01: -1100  (exp 1, 365 Tage)
        #   2024-01-01: +2420  (exp 2, 730 Tage)
        # NPV(r) = -1000 - 1100/(1+r) + 2420/(1+r)^2
        # Bei r = 0.10:  -1000 - 1100/1.1 + 2420/1.21
        #              =  -1000 - 1000    + 2000          = 0
        # => Nullstelle r = 0.10 exakt. Pinnt 365er-Basis + Dezimalbruch-Konvention.
        result = xirr([
            (date(2022, 1, 1), -1000),
            (date(2023, 1, 1), -1100),
            (date(2024, 1, 1), 2420),
        ])
        assert result == pytest.approx(0.10, abs=1e-6)

    def test_order_independence_reversed_input_same_irr(self):
        # Dieselben drei Cashflows in UMGEKEHRTER Reihenfolge. Die Funktion
        # sortiert NICHT selbst und nimmt d0 = cashflows[0][0] (Zeile 37) ->
        # d0 wird hier das SPAETESTE Datum, alle Exponenten werden negativ.
        # Mathematisch ist NPV' = (1+r)^(T/365) * NPV (positiver Faktor),
        # also hat NPV' dieselbe Nullstelle. => r = 0.10 unveraendert.
        # Beleg: bei d0 = 2024-01-01 ist NPV(r) = 2420 - 1100(1+r) - 1000(1+r)^2,
        #   bei r=0.10: 2420 - 1210 - 1210 = 0. Bestaetigt Reihenfolge-Invarianz
        #   (wichtig, weil _calculate_xirr_from_data in Zeile 192 sortiert, xirr nicht).
        result = xirr([
            (date(2024, 1, 1), 2420),
            (date(2023, 1, 1), -1100),
            (date(2022, 1, 1), -1000),
        ])
        assert result == pytest.approx(0.10, abs=1e-6)

    def test_near_total_loss_clamps_to_minus_099(self):
        # -1000 -> +10 ueber 365 Tage. Echte Nullstelle:
        #   NPV = -1000 + 10/(1+r) = 0  =>  1+r = 10/1000 = 0.01  =>  r = -0.99
        # Das liegt exakt auf der Bisection-Untergrenze -0.99 (Zeile 75) bzw.
        # dem Newton-Clamp (Zeile 72). Pinnt diesen maximalen Verlust: wuerde
        # der Clamp z.B. auf -0.999 geaendert, faengt dieser Test den Bruch.
        result = xirr([(date(2023, 1, 1), -1000), (date(2024, 1, 1), 10)])
        assert result == pytest.approx(-0.99, abs=1e-6)


class TestGoldenMasterDeannualizeXIRR:
    """deannualize_xirr(rate_pct, days): Eingabe UND Ausgabe in PROZENT.
    Formel (Zeile 98): ((1 + rate_pct/100)^(days/365.0) - 1) * 100.
    """

    def test_full_year_equals_input_rate(self):
        # days = 365 => Exponent 365/365 = 1 => (1.10^1 - 1)*100 = 10.0 exakt.
        # Pinnt die 365er-Basis ohne Toleranz: mit 365.25 kaeme 9.9929 heraus.
        assert deannualize_xirr(10.0, 365) == pytest.approx(10.0, abs=1e-9)

    def test_two_years_exact_compound(self):
        # days = 730 => Exponent 2 => (1.10^2 - 1)*100 = (1.21 - 1)*100 = 21.0 exakt.
        # Pinnt Zinseszins-Compoundierung + PROZENT-Konvention des Parameters.
        assert deannualize_xirr(10.0, 730) == pytest.approx(21.0, abs=1e-9)

    def test_half_year_partial_period(self):
        # days = 182 => Exponent 182/365 = 0.4986301...
        # (1.10^0.4986301 - 1)*100
        #   = (exp(0.4986301 * ln 1.10) - 1)*100
        #   = (exp(0.4986301 * 0.09531018) - 1)*100
        #   = (exp(0.04752452) - 1)*100
        #   = (1.0486717 - 1)*100 = 4.8672
        # Charakterisiert das Teiljahr-Verhalten (Periodenrendite < p.a.-Rate).
        assert deannualize_xirr(10.0, 182) == pytest.approx(4.8672, abs=0.01)

    def test_zero_days_guard_returns_zero(self):
        # days <= 0 -> 0.0 (Guard Zeile 96/97), nicht NaN/Negativ.
        assert deannualize_xirr(10.0, 0) == 0.0

    def test_negative_days_guard_returns_zero(self):
        # days = -1 faellt ebenfalls unter days <= 0 -> 0.0.
        assert deannualize_xirr(10.0, -1) == 0.0


# --- Hilfen fuer _calculate_xirr_from_data (reine Funktion, MagicMock statt DB) ---

def _xirr_snap(d, total_value, net_cf=0):
    """Minimaler Snapshot-Mock: nur .date, .total_value_chf, .net_cash_flow_chf
    werden von _calculate_xirr_from_data gelesen (Zeile 136/139/149/158)."""
    s = MagicMock()
    s.date = d
    s.total_value_chf = Decimal(str(total_value))
    s.net_cash_flow_chf = Decimal(str(net_cf))
    return s


def _xirr_txn(d, ttype, total_chf):
    """Minimaler Transaktions-Mock: .date, .type, .total_chf (Zeile 162-168)."""
    t = MagicMock()
    t.date = d
    t.type = ttype
    t.total_chf = Decimal(str(total_chf))
    return t


class TestGoldenMasterXIRRFromData:
    """Vorzeichen- und Merge-Konventionen von _calculate_xirr_from_data.

    Alle Faelle sind so konstruiert, dass die korrekte Vorzeichen-/Merge-Wahl
    exakt r = 0.10 ergibt; jede stille Drift verschiebt die Nullstelle weg.
    """

    def test_inflow_transaction_becomes_negative_cf(self):
        # Snapshots: 2022-01-01 = 1000 (Start), 2024-01-01 = 2420 (Ende).
        # Buy 1100 am 2023-01-01: INFLOW -> XIRR-CF = -1100 (Kapital raus, Zeile 164).
        # Ergibt Cashflows [-1000, -1100, +2420] => r = 0.10 (siehe Multi-CF-Herleitung).
        # Wuerde der Buy als +1100 verbucht, waere die Nullstelle voellig anders.
        snaps = [_xirr_snap(date(2022, 1, 1), 1000), _xirr_snap(date(2024, 1, 1), 2420)]
        txns = [_xirr_txn(date(2023, 1, 1), TransactionType.buy, 1100)]
        rate = _calculate_xirr_from_data(snaps, txns, date(2022, 1, 1), date(2024, 1, 1))
        assert rate == pytest.approx(0.10, abs=1e-6)

    def test_outflow_transaction_becomes_positive_cf(self):
        # Snapshots: 2022-01-01 = 1000 (Start), 2024-01-01 = 1089 (Ende).
        # Sell 110 am 2023-01-01: OUTFLOW -> XIRR-CF = +110 (Kapital zurueck, Zeile 166).
        # NPV(0.10) = -1000 + 110/1.1 + 1089/1.21 = -1000 + 100 + 900 = 0 => r = 0.10.
        snaps = [_xirr_snap(date(2022, 1, 1), 1000), _xirr_snap(date(2024, 1, 1), 1089)]
        txns = [_xirr_txn(date(2023, 1, 1), TransactionType.sell, 110)]
        rate = _calculate_xirr_from_data(snaps, txns, date(2022, 1, 1), date(2024, 1, 1))
        assert rate == pytest.approx(0.10, abs=1e-6)

    def test_snapshot_inflow_is_inverted(self):
        # Kein Txn-CF; stattdessen Snapshot net_cash_flow_chf = +1100 am 2023-01-01.
        # Positiv = Inflow im Snapshot -> wird zu -1100 im XIRR (Inversion Zeile 177).
        # Cashflows [-1000, -1100, +2420] => r = 0.10. Pinnt die Snapshot-Inversion.
        snaps = [
            _xirr_snap(date(2022, 1, 1), 1000),
            _xirr_snap(date(2023, 1, 1), 1500, net_cf=1100),
            _xirr_snap(date(2024, 1, 1), 2420),
        ]
        rate = _calculate_xirr_from_data(snaps, [], date(2022, 1, 1), date(2024, 1, 1))
        assert rate == pytest.approx(0.10, abs=1e-6)

    def test_snapshot_cf_dominates_when_much_larger(self):
        # Auf 2023-01-01 konkurrieren Txn-Buy 100 (txn_cf=-100) und Snapshot ncf 1100
        # (snap_cf=-1100). Merge (Zeile 187): nimm Snapshot, wenn
        #   abs(snap) > abs(txn) * 1.1  =>  1100 > 110 (wahr) => -1100 gewinnt.
        # Cashflows [-1000, -1100, +2420] => r = 0.10.
        snaps = [
            _xirr_snap(date(2022, 1, 1), 1000),
            _xirr_snap(date(2023, 1, 1), 1500, net_cf=1100),
            _xirr_snap(date(2024, 1, 1), 2420),
        ]
        txns = [_xirr_txn(date(2023, 1, 1), TransactionType.buy, 100)]
        rate = _calculate_xirr_from_data(snaps, txns, date(2022, 1, 1), date(2024, 1, 1))
        assert rate == pytest.approx(0.10, abs=1e-6)

    def test_transaction_cf_wins_within_11_threshold(self):
        # Grenzfall, der die 1.1-Schwelle (Zeile 187) gegen eine 1.0-Drift pinnt:
        # Txn-Buy 1000 (txn_cf=-1000) vs. Snapshot ncf 1050 (snap_cf=-1050) am 2023-01-01.
        #   abs(snap) > abs(txn)*1.1  =>  1050 > 1100 (FALSCH) => Txn-CF -1000 gewinnt.
        # End-Snapshot 2310 gewaehlt, sodass MIT Txn-CF gilt:
        #   NPV(0.10) = -1000 - 1000/1.1 + 2310/1.21 = -1000 - 909.0909 + 1909.0909 = 0 => r=0.10
        # Haette der Snapshot (-1050) gewonnen, waere die Nullstelle != 0.10.
        # Faellt die Schwelle auf 1.0 (1050 > 1000), broeche dieser Test rot.
        snaps = [
            _xirr_snap(date(2022, 1, 1), 1000),
            _xirr_snap(date(2023, 1, 1), 1500, net_cf=1050),
            _xirr_snap(date(2024, 1, 1), 2310),
        ]
        txns = [_xirr_txn(date(2023, 1, 1), TransactionType.buy, 1000)]
        rate = _calculate_xirr_from_data(snaps, txns, date(2022, 1, 1), date(2024, 1, 1))
        assert rate == pytest.approx(0.10, abs=1e-6)


class TestGoldenMasterXIRRPeriodDB:
    """Voller DB-Pfad calculate_xirr_for_period: seedet echte ORM-Rows in
    In-Memory-SQLite und prueft die Query+Berechnung end-to-end (FK aus,
    beliebige user_id/position_id zulaessig laut Test-Setup)."""

    async def test_period_xirr_from_seeded_rows(self, db):
        # Snapshots 2022-01-01 = 1000 (Start) und 2024-01-01 = 2420 (Ende),
        # Buy 1100 am 2023-01-01 -> XIRR-Input [-1000, -1100, +2420] => r = 0.10
        # (identische Herleitung wie test_two_intermediate_cashflows_exact_ten_percent,
        #  hier aber durch DB-Query + Decimal->float-Konvertierung des echten Pfades).
        uid = uuid.uuid4()
        pos_id = uuid.uuid4()
        db.add_all([
            PortfolioSnapshot(user_id=uid, date=date(2022, 1, 1),
                              total_value_chf=Decimal("1000"),
                              cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0")),
            PortfolioSnapshot(user_id=uid, date=date(2024, 1, 1),
                              total_value_chf=Decimal("2420"),
                              cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0")),
        ])
        db.add(Transaction(
            user_id=uid, position_id=pos_id, type=TransactionType.buy,
            date=date(2023, 1, 1), shares=Decimal("11"),
            price_per_share=Decimal("100"), currency="CHF",
            total_chf=Decimal("1100"),
        ))
        await db.commit()

        rate = await calculate_xirr_for_period(db, uid, date(2022, 1, 1), date(2024, 1, 1))
        assert rate == pytest.approx(0.10, abs=1e-6)


# ======================================================================
# Modified Dietz — Edge-Cases (Withdrawal, Snapshot-CF, Verkettung, Fallback)
# ======================================================================

# --- Invariante 3 (Erweiterung): Modified Dietz — Edge-Cases ---
#
# Diese Faelle nageln die *Definition* der monatlichen Modified-Dietz-Rendite an
# Stellen fest, die der bestehende Test (Mid-Month-Buy + Schaltjahr) noch nicht
# beruehrt: das OUTFLOW-Vorzeichen einer Withdrawal, den Snapshot-CF-Pfad
# (manuelle Aenderung via net_cash_flow_chf, der die Transaktions-CF ersetzt),
# die Verkettung ueber drei Monate (prev_month_end wird month_start) und den
# Denominator-Fallback (|denominator| < 100). Belege: services/
# performance_history_service.py:286-416, constants/cashflow.py.
#
# Gewicht je Cashflow:  w_i = (days_in_month - (txn.date.day - 1)) / days_in_month
#                       (Zeile 366-367; day_of_month ist 0-basiert)
# Formel:               R = (V_end - V_start - sum(CF)) / (V_start + sum(w_i*CF_i)) * 100
# OUTFLOW (sell/withdrawal/delivery_out): cf = -total_chf  (Zeile 361-362)


def _gm_snap(uid, d, value, cf="0"):
    """PortfolioSnapshot-Row mit allen NOT-NULL-Feldern (SQLite, FK aus)."""
    return PortfolioSnapshot(
        user_id=uid,
        date=d,
        total_value_chf=Decimal(str(value)),
        cash_chf=Decimal("0"),
        net_cash_flow_chf=Decimal(str(cf)),
    )


def _gm_txn(uid, pos, ttype, d, total):
    """Transaction-Row analog zum bestehenden Green-Test (Zeile 146-151)."""
    return Transaction(
        user_id=uid,
        position_id=pos,
        type=ttype,
        date=d,
        shares=Decimal("1"),
        price_per_share=Decimal("0"),
        currency="CHF",
        total_chf=Decimal(str(total)),
    )


class TestGoldenMasterModifiedDietzEdgeCases:
    """Edge-Cases der Modified-Dietz-Definition — jeder Soll-Wert von Hand."""

    async def test_mid_month_withdrawal_is_negative_outflow(self, db):
        # Eine Withdrawal ist ein OUTFLOW: cf = -total_chf (Zeile 361-362), das
        # zieht den Denominator RUNTER (nicht rauf wie ein Buy).
        #
        # Jan 2023: nur ein Snapshot (31.1. = 10000) -> erster Monat mit < 2
        #   Snapshots gibt 0.0 zurueck und setzt prev_month_end = 10000
        #   (Zeile 341-344).
        # Feb 2023 (28 Tage, KEIN Schaltjahr):
        #   V_start = prev_month_end = 10000;  V_end = 9400
        #   Withdrawal 500 CHF am 15.2. -> cf = -500
        #   w = (28 - (15-1)) / 28 = 14/28 = 0.5
        #   weighted_cf = 0.5 * (-500) = -250
        #   denominator = 10000 + (-250) = 9750  (>= 100)
        #   R = (9400 - 10000 - (-500)) / 9750 * 100
        #     = (-100) / 9750 * 100 = -1.0256... -> -1.03
        # Wuerde das Vorzeichen still gedreht (Withdrawal als INFLOW), waere der
        # Denominator 10250 und der Zaehler -1100 -> ganz anderes Ergebnis.
        uid = uuid.uuid4()
        pos = uuid.uuid4()
        db.add_all([
            _gm_snap(uid, date(2023, 1, 31), 10000),
            _gm_snap(uid, date(2023, 2, 28), 9400),
        ])
        db.add(_gm_txn(uid, pos, TransactionType.withdrawal, date(2023, 2, 15), 500))
        await db.commit()

        res = await _monthly_returns_modified_dietz(db, uid, date(2023, 1, 1))
        by = {(r["year"], r["month"]): r["return_pct"] for r in res}

        assert by[(2023, 1)] == pytest.approx(0.0, abs=0.001)
        assert by[(2023, 2)] == pytest.approx(-1.03, abs=0.01)

    async def test_snapshot_cashflow_path_overrides_transaction_cf(self, db):
        # Snapshot-CF-Pfad: wenn |snap_cf_total| > |txn_cf_total| * 1.1 (Zeile 385),
        # ersetzt der aus net_cash_flow_chf gespeiste CF die Transaktions-CF
        # KOMPLETT (es wird NICHT addiert). Das faengt manuelle Positions-
        # aenderungen, die keine Transaction haben.
        #
        # Jan 2023: ein Snapshot (31.1. = 10000) -> 0.0, prev_month_end = 10000.
        # Feb 2023 (28 Tage):
        #   Transaktion: Buy 100 CHF am 10.2. -> txn_cf_total = 100
        #   Snapshots:   15.2. total=11000 mit net_cash_flow_chf = 1000
        #                28.2. total=12100 mit net_cash_flow_chf = 0
        #   snap_cf_total = 1000;  Schwelle: |1000| > |100|*1.1 = 110 -> WAHR
        #   => total_cf = 1000 (snap), die Buy-CF von 100 wird ignoriert.
        #   w(15.2.) = (28-14)/28 = 0.5 -> snap_cf_weighted = 1000*0.5 = 500
        #   V_start = 10000;  V_end = 12100 (letzter Snapshot des Monats)
        #   denominator = 10000 + 500 = 10500
        #   R = (12100 - 10000 - 1000) / 10500 * 100 = 1100/10500*100
        #     = 10.476... -> 10.48
        # Wuerde der txn-Pfad faelschlich greifen (total_cf=100), waere der
        # Zaehler 2000 und das Ergebnis ~19 % — der Test wuerde rot.
        uid = uuid.uuid4()
        pos = uuid.uuid4()
        db.add_all([
            _gm_snap(uid, date(2023, 1, 31), 10000),
            _gm_snap(uid, date(2023, 2, 15), 11000, cf="1000"),
            _gm_snap(uid, date(2023, 2, 28), 12100),
        ])
        db.add(_gm_txn(uid, pos, TransactionType.buy, date(2023, 2, 10), 100))
        await db.commit()

        res = await _monthly_returns_modified_dietz(db, uid, date(2023, 1, 1))
        by = {(r["year"], r["month"]): r["return_pct"] for r in res}

        assert by[(2023, 2)] == pytest.approx(10.48, abs=0.01)

    async def test_three_month_chaining_uses_prev_month_end(self, db):
        # Verkettung (Zeile 329/336-337/414): der START-Wert eines Monats ist der
        # LETZTE Snapshot des Vormonats (prev_month_end_value), NICHT der erste
        # Snapshot des Monats und NICHT eine Kostenbasis. Drei Monate ohne
        # Cashflows machen das exakt nachpruefbar.
        #
        # Jan 2024: 1.1. = 10000, 31.1. = 12000  -> erster Monat MIT 2 Snapshots
        #   R = (12000-10000)/10000*100 = 20.0 ;  prev = 12000
        # Feb 2024 (Schaltjahr, nur ein Snapshot 29.2. = 13200):
        #   V_start = prev = 12000  (NICHT der eigene erste Snapshot)
        #   R = (13200-12000)/12000*100 = 10.0 ;  prev = 13200
        # Mar 2024 (31.3. = 12540):
        #   V_start = prev = 13200
        #   R = (12540-13200)/13200*100 = -660/13200*100 = -5.0 ;  prev = 12540
        # Bricht die Verkettung (z.B. Reset auf Monats-Erst-Snapshot), aendern
        # sich Feb und Mar sofort.
        uid = uuid.uuid4()
        db.add_all([
            _gm_snap(uid, date(2024, 1, 1), 10000),
            _gm_snap(uid, date(2024, 1, 31), 12000),
            _gm_snap(uid, date(2024, 2, 29), 13200),
            _gm_snap(uid, date(2024, 3, 31), 12540),
        ])
        await db.commit()

        res = await _monthly_returns_modified_dietz(db, uid, date(2024, 1, 1))
        by = {(r["year"], r["month"]): r["return_pct"] for r in res}

        assert by[(2024, 1)] == pytest.approx(20.0, abs=0.01)
        assert by[(2024, 2)] == pytest.approx(10.0, abs=0.01)
        assert by[(2024, 3)] == pytest.approx(-5.0, abs=0.01)

    async def test_denominator_fallback_simple_return_when_start_large(self, db):
        # Denominator-Fallback (Zeile 395-401): wenn fast alles raus-/reingeht und
        # |denominator| < 100, faellt die Funktion auf die EINFACHE Rendite
        # (V_end-V_start)/V_start zurueck — sofern V_start > 100.
        #
        # Jan 2023: ein Snapshot (31.1. = 10000) -> 0.0, prev = 10000.
        # Feb 2023 (28 Tage):
        #   Withdrawal 9950 CHF am 1.2. -> cf = -9950
        #   w(1.2.) = (28 - (1-1))/28 = 28/28 = 1.0
        #   weighted_cf = -9950 ; denominator = 10000 - 9950 = 50  (|50| < 100!)
        #   V_start = 10000 (> 100) -> Fallback simple return:
        #   R = (V_end - V_start)/V_start * 100 = (200-10000)/10000*100 = -98.0
        # Die normale Dietz-Formel ueber denominator=50 waere sinnlos gross;
        # der Fallback haelt das Ergebnis bei -98.0.
        uid = uuid.uuid4()
        pos = uuid.uuid4()
        db.add_all([
            _gm_snap(uid, date(2023, 1, 31), 10000),
            _gm_snap(uid, date(2023, 2, 28), 200),
        ])
        db.add(_gm_txn(uid, pos, TransactionType.withdrawal, date(2023, 2, 1), 9950))
        await db.commit()

        res = await _monthly_returns_modified_dietz(db, uid, date(2023, 1, 1))
        by = {(r["year"], r["month"]): r["return_pct"] for r in res}

        assert by[(2023, 2)] == pytest.approx(-98.0, abs=0.01)

    async def test_denominator_fallback_zero_when_start_tiny(self, db):
        # Zweiter Zweig des Fallbacks (Zeile 400-401): ist |denominator| < 100 UND
        # V_start <= 100, gibt die Funktion 0.0 zurueck (kein simple return), um
        # absurde Prozentwerte bei Mikro-Portfolios zu vermeiden.
        #
        # Jan 2023: ein Snapshot (31.1. = 50) -> erster Monat < 2 Snapshots -> 0.0,
        #   prev_month_end = 50.
        # Feb 2023 (28.2. = 80, keine Cashflows):
        #   V_start = prev = 50 ; weighted_cf = 0 ; denominator = 50 (< 100)
        #   V_start = 50 ist NICHT > 100 -> return_pct = 0.0
        # Obwohl der Wert von 50 auf 80 (+60 %) stieg, ist der Soll-Wert bewusst
        # 0.0 — ein Bruch dieser Guard wuerde hier sofort != 0 liefern.
        uid = uuid.uuid4()
        db.add_all([
            _gm_snap(uid, date(2023, 1, 31), 50),
            _gm_snap(uid, date(2023, 2, 28), 80),
        ])
        await db.commit()

        res = await _monthly_returns_modified_dietz(db, uid, date(2023, 1, 1))
        by = {(r["year"], r["month"]): r["return_pct"] for r in res}

        assert by[(2023, 2)] == pytest.approx(0.0, abs=0.001)


# ======================================================================
# cost_basis / realized P&L — Edge-Cases
# ======================================================================

class TestGoldenMasterPositionValueEdges:
    """Edge-Case-Pins fuer _calculate_position_values (recalculate_service.py:23-80).

    Ergaenzt die Basis-Faelle in TestGoldenMasterCostBasis. Wiederverwendet den
    modul-lokalen Helper _txn(ttype, shares, total_chf, fees_chf=0.0, fx=1.0).
    Alle Soll-Werte sind von Hand hergeleitet (siehe Kommentar je Fall), NIE durch
    Aufruf der getesteten Funktion. Klemmt damit die Kern-Definition der Cost-Basis-
    und Realized-P&L-Mechanik fest: stille Aenderungen werden sofort rot.
    """

    def test_oversell_guard_clamps_to_holding(self):
        # Oversell-Guard (recalculate_service.py:47-52): es wird mehr verkauft als
        # vorhanden -> sell_shares wird auf den Bestand geklemmt.
        # Buy 10 @ total 1000 -> shares 10, cost 1000
        # Sell 15 @ proceeds 1800, fees 0:
        #   sell_shares (15) > shares (10) -> clamp auf 10
        #   avg_cost = 1000/10 = 100; allocated = 100*10 = 1000
        #   realized = 1800 - 1000 - 0 = 800
        #   sell_ratio = 10/10 = 1 -> cost_basis *= (1-1) = 0   (NIE negativ!)
        #   shares = max(0, 10-10) = 0
        # Ohne Clamp waere cost_basis = 1000*(1-1.5) = -500 und realized = 300 ->
        # dieser Fall faengt einen Wegfall des Guards exakt ab.
        txns = [
            _txn(TransactionType.buy, 10, 1000.0),
            _txn(TransactionType.sell, 15, 1800.0),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == pytest.approx(0.0, abs=1e-9)
        assert cost == pytest.approx(0.0, abs=1e-9)  # nie negativ trotz Oversell
        assert realized == pytest.approx(800.0, abs=1e-9)
        assert txns[1].cost_basis_at_sale == 1000.0
        assert txns[1].realized_pnl_chf == 800.0

    def test_sell_with_fees_reduces_realized(self):
        # Sell mit fees_chf: realized = proceeds - allocated_cost - fees (Zeile 59).
        # Buy 10 @ total 1000 -> shares 10, cost 1000
        # Sell 10 @ proceeds 1500, fees 50:
        #   avg_cost = 1000/10 = 100; allocated = 100*10 = 1000
        #   realized = 1500 - 1000 - 50 = 450
        #   cost_basis *= (1 - 10/10) = 0; shares 0
        txns = [
            _txn(TransactionType.buy, 10, 1000.0),
            _txn(TransactionType.sell, 10, 1500.0, fees_chf=50.0),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == pytest.approx(0.0, abs=1e-9)
        assert cost == pytest.approx(0.0, abs=1e-9)
        assert realized == pytest.approx(450.0, abs=1e-9)
        assert txns[1].cost_basis_at_sale == 1000.0
        assert txns[1].realized_pnl_chf == 450.0

    def test_realized_pnl_converted_to_txn_currency(self):
        # realized_pnl (Txn-Waehrung) = realized_chf / fx_rate_to_chf, round(2) (Zeile 65-66).
        # Buy 10 @ total_chf 900 -> shares 10, cost 900
        # Sell 10 @ proceeds_chf 1200, fees 0, fx = 0.9:
        #   avg_cost = 900/10 = 90; allocated = 900
        #   realized_chf = 1200 - 900 - 0 = 300
        #   realized_pnl (Fremdwhg) = round(300 / 0.9, 2) = round(333.3333..., 2) = 333.33
        # Pinnt sowohl die fx-Division als auch das Runden auf 2 Stellen.
        txns = [
            _txn(TransactionType.buy, 10, 900.0),
            _txn(TransactionType.sell, 10, 1200.0, fx=0.9),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == pytest.approx(0.0, abs=1e-9)
        assert cost == pytest.approx(0.0, abs=1e-9)
        assert realized == pytest.approx(300.0, abs=1e-9)   # CHF-Summe unveraendert
        assert txns[1].realized_pnl_chf == 300.0            # CHF-Feld
        assert txns[1].realized_pnl == 333.33               # Txn-Waehrung via fx

    def test_fx_zero_guard_falls_back_to_one(self):
        # FX-Zero-Guard (Zeile 65): fx_rate_to_chf == 0 -> intern 1.0, keine Division durch 0.
        # Buy 10 @ total 1000 -> shares 10, cost 1000
        # Sell 10 @ proceeds 1300, fees 0, fx = 0:
        #   realized_chf = 1300 - 1000 = 300
        #   fx-Guard: 0 > 0 False -> fx = 1.0
        #   realized_pnl = round(300 / 1.0, 2) = 300.0
        txns = [
            _txn(TransactionType.buy, 10, 1000.0),
            _txn(TransactionType.sell, 10, 1300.0, fx=0.0),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == pytest.approx(0.0, abs=1e-9)
        assert realized == pytest.approx(300.0, abs=1e-9)
        assert txns[1].realized_pnl_chf == 300.0
        assert txns[1].realized_pnl == 300.0  # fx=0 -> Fallback 1.0, keine ZeroDivision

    def test_delivery_in_additive_delivery_out_reductive(self):
        # delivery_in in ADDITIVE_TYPES, delivery_out in REDUCTIVE_TYPES (Zeile 19-20).
        # delivery_out laeuft durch denselben realized-Pfad wie sell.
        # delivery_in 10 @ total 1000 -> shares 10, cost 1000
        # delivery_out 4 @ proceeds 600, fees 0:
        #   avg_cost = 1000/10 = 100; allocated = 100*4 = 400
        #   realized = 600 - 400 - 0 = 200
        #   sell_ratio = 4/10 = 0.4 -> cost_basis *= 0.6 = 600
        #   shares = 10 - 4 = 6
        txns = [
            _txn(TransactionType.delivery_in, 10, 1000.0),
            _txn(TransactionType.delivery_out, 4, 600.0),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == pytest.approx(6.0, abs=1e-9)
        assert cost == pytest.approx(600.0, abs=1e-9)
        assert realized == pytest.approx(200.0, abs=1e-9)
        assert txns[1].cost_basis_at_sale == 400.0
        assert txns[1].realized_pnl_chf == 200.0

    def test_sell_without_holding_yields_zero(self):
        # Sell ohne Bestand (else-Zweig, Zeile 73-76): shares == 0 -> alle Felder 0.
        # Sell 10 @ proceeds 1500, fees 0, kein vorheriger Buy:
        #   shares == 0 -> if shares > 0 ... False -> else
        #   cost_basis_at_sale = 0, realized_pnl_chf = 0, realized_pnl = 0
        #   shares = max(0, 0-10) = 0
        txns = [
            _txn(TransactionType.sell, 10, 1500.0),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == pytest.approx(0.0, abs=1e-9)
        assert cost == pytest.approx(0.0, abs=1e-9)
        assert realized == pytest.approx(0.0, abs=1e-9)
        assert txns[0].cost_basis_at_sale == 0
        assert txns[0].realized_pnl_chf == 0
        assert txns[0].realized_pnl == 0

    def test_two_sequential_sells_use_updated_avg_cost(self):
        # Mehrere Sells nacheinander: jeder nutzt den aktuellen gewichteten
        # Durchschnitt der verbleibenden Position (kein Drift).
        # Buy 10 @ 1000  -> shares 10, cost 1000
        # Buy 10 @ 2000  -> shares 20, cost 3000  (avg 150)
        # Sell 5 @ 1000:
        #   avg = 3000/20 = 150; allocated = 150*5 = 750
        #   realized = 1000 - 750 = 250
        #   sell_ratio = 5/20 = 0.25 -> cost *= 0.75 = 2250; shares 15
        # Sell 5 @ 1000:
        #   avg = 2250/15 = 150; allocated = 150*5 = 750
        #   realized = 1000 - 750 = 250
        #   sell_ratio = 5/15 = 1/3 -> cost *= 2/3 = 1500; shares 10
        # total realized = 500; final shares 10, cost 1500
        txns = [
            _txn(TransactionType.buy, 10, 1000.0),
            _txn(TransactionType.buy, 10, 2000.0),
            _txn(TransactionType.sell, 5, 1000.0),
            _txn(TransactionType.sell, 5, 1000.0),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == pytest.approx(10.0, abs=1e-9)
        assert cost == pytest.approx(1500.0, abs=1e-9)
        assert realized == pytest.approx(500.0, abs=1e-9)
        assert txns[2].realized_pnl_chf == 250.0
        assert txns[3].realized_pnl_chf == 250.0
        assert txns[2].cost_basis_at_sale == 750.0
        assert txns[3].cost_basis_at_sale == 750.0


# ======================================================================
# Assetklassen-Ausschluss (PE/Immobilien/Vorsorge) + count_as_cash
# ======================================================================

# ---------------------------------------------------------------------------
# Invariante 2 (CLAUDE.md): Assetklassen-Ausschluss
#   "Immobilien, Vorsorge und Private Equity zaehlen NICHT zur liquiden
#    Performance / zum liquiden Vermoegen."
# Plus count_as_cash (T-Bill-/Geldmarkt-ETFs zaehlen zusaetzlich als Cash,
# aber OHNE Doppelzaehlung im Gesamtwert).
#
# Diese Golden-Master nageln die Definition der liquiden Snapshot-Summe fest:
# eine stille Aenderung (PE-Ausschluss faellt weg, Cash-Saldo wird ploetzlich
# als Marktwert statt cost_basis bewertet, count_as_cash doppelt gezaehlt,
# pension aus dem Cash-Topf entfernt) faerbt den Test sofort rot.
#
# Belege:
#   services/snapshot_service.py:289-342  _calc_position_value_chf (pur)
#   services/snapshot_service.py:28-110   _calc_portfolio_value_fast (DB)
#   services/snapshot_service.py:219-235  _LIQUID_ASSET_TYPES / _EXCLUDED_FROM_BUCKET_SUMS
# ---------------------------------------------------------------------------


def _pos_ns(**over):
    """Minimal-Position als SimpleNamespace fuer die pure Einzel-Bewertung.

    _calc_position_value_chf liest nur diese Attribute (snapshot_service.py:
    294-342) — kein DB-Row, kein ORM noetig. Defaults = einfache CHF-Aktie.
    """
    base = dict(
        type=AssetType.stock,
        cost_basis_chf=Decimal("1000"),
        currency="CHF",
        shares=Decimal("10"),
        coingecko_id=None,   # kein Crypto-Cache-Pfad
        gold_org=False,      # kein Metall-Cache-Pfad
        yfinance_ticker=None,
        ticker="TEST",
        current_price=Decimal("110"),
    )
    base.update(over)
    return SimpleNamespace(**base)


class TestGoldenMasterPositionLiquidValue:
    """Pin auf _calc_position_value_chf (snapshot_service.py:289).

    Die Funktion ist async, hat aber fuer PE/cash/pension keinen I/O — sie wird
    aus der (dank asyncio_mode=auto automatisch laufenden) async-Testfunktion
    heraus awaited. Fuer den Wertschriften-Pfad wird services.cache.get auf None
    gepatcht, damit der Fallback auf pos.current_price greift (Zeile 333).
    """

    async def test_private_equity_returns_zero(self):
        # Herleitung: Private Equity ist komplett aus dem liquiden Wert
        # ausgeschlossen. snapshot_service.py:294-295 gibt 0.0 zurueck BEVOR
        # irgendein Kurs/FX angefasst wird — auch wenn shares & current_price
        # gesetzt sind. Soll = 0.0, unabhaengig von shares/price.
        pos = _pos_ns(type=AssetType.private_equity,
                      shares=Decimal("5"), current_price=Decimal("1000"))
        v = await _calc_position_value_chf(pos, {})
        assert v == 0.0

    async def test_normal_stock_is_market_value(self, monkeypatch):
        # Herleitung (Wertschriften-Bewertung = shares x price x fx):
        #   shares=10, current_price=110, currency=CHF -> fx=1.0 (_fx_or_none
        #   gibt fuer CHF 1.0, snapshot_service.py:275-276).
        #   value = 10 x 110 x 1.0 = 1100.0
        # cache.get->None erzwingt den current_price-Fallback (Zeile 333).
        monkeypatch.setattr("services.cache.get", lambda k: None)
        v = await _calc_position_value_chf(_pos_ns(), {})
        assert v == pytest.approx(1100.0, abs=1e-9)

    async def test_cash_is_saldo_not_market_value(self):
        # Herleitung: Cash wird als Saldo (cost_basis_chf) bewertet, NICHT als
        # shares x price (snapshot_service.py:296-307). CHF -> kein FX.
        #   cost_basis_chf=5000 -> Soll = 5000.0
        # Pinnt, dass Cash niemals ueber Kurs/Shares laeuft (waere sonst 0,
        # da shares hier irrelevant).
        pos = _pos_ns(type=AssetType.cash, cost_basis_chf=Decimal("5000"))
        v = await _calc_position_value_chf(pos, {})
        assert v == pytest.approx(5000.0, abs=1e-9)

    async def test_pension_is_saldo(self):
        # Herleitung: Vorsorge wird wie Cash als Saldo bewertet
        # (snapshot_service.py:296). cost_basis_chf=8000 (CHF) -> Soll = 8000.0.
        # Pinnt, dass pension den Cash-Pfad nimmt (Saldo), nicht den
        # Wertschriften-Pfad.
        pos = _pos_ns(type=AssetType.pension, cost_basis_chf=Decimal("8000"))
        v = await _calc_position_value_chf(pos, {})
        assert v == pytest.approx(8000.0, abs=1e-9)

    async def test_cash_foreign_currency_fx_converted(self):
        # Herleitung: Fremdwaehrungs-Cash wird mit der FX-Rate multipliziert
        # (snapshot_service.py:298-306). cost_basis_chf=1000 (hier USD-Saldo),
        # fx_rates={'USD':0.9} -> 1000 x 0.9 = 900.0.
        # Pinnt die FX-Anwendung auf Cash-Salden (kein stilles fx=1.0).
        pos = _pos_ns(type=AssetType.cash, cost_basis_chf=Decimal("1000"),
                      currency="USD")
        v = await _calc_position_value_chf(pos, {"USD": 0.9})
        assert v == pytest.approx(900.0, abs=1e-9)

    async def test_real_estate_with_zero_shares_is_zero(self):
        # Charakterisierung des IST-Zustands: _calc_position_value_chf hat KEINEN
        # expliziten real_estate-Ausschluss. Eine Immobilie hat in der Praxis
        # shares=0 -> der shares<=0-Guard (snapshot_service.py:309-311) liefert
        # 0.0. Soll = 0.0. (Hinweis: faengt den Guard, NICHT einen expliziten
        # Assetklassen-Ausschluss; eine Immobilie mit shares>0 wuerde bewertet —
        # bekannte Inkonsistenz, hier bewusst als IST gepinnt.)
        pos = _pos_ns(type=AssetType.real_estate, shares=Decimal("0"),
                      current_price=Decimal("500000"))
        v = await _calc_position_value_chf(pos, {})
        assert v == 0.0


def _mk_pos(uid, **over):
    """Position-Row fuer die DB-Fixture. NOT-NULL-Pflichtfelder gesetzt;
    FK-Constraints sind in SQLite aus -> bucket_id ist eine beliebige UUID,
    kein User-/Bucket-Row noetig (snapshot_service.py:37-40 filtert nur per
    user_id + is_active)."""
    base = dict(
        user_id=uid,
        bucket_id=uuid.uuid4(),
        ticker="X",
        name="X",
        type=AssetType.stock,
        currency="CHF",
        shares=Decimal("10"),
        cost_basis_chf=Decimal("1000"),
        current_price=Decimal("110"),
        count_as_cash=False,
        is_active=True,
        coingecko_id=None,
        gold_org=False,
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
    )
    base.update(over)
    return Position(**base)


class TestGoldenMasterPortfolioLiquidValue:
    """Pin auf _calc_portfolio_value_fast (snapshot_service.py:28) ->
    (total_value_chf, cash_chf).

    Zwei externe Abhaengigkeiten gemockt:
      - services.utils.get_fx_rates_batch -> feste FX-Map (kein Netz)
      - services.cache.get -> None (Fallback auf pos.current_price)
    """

    async def test_private_equity_excluded_from_total(self, db, monkeypatch):
        # Herleitung:
        #   Aktie:  shares=10 x price=110 x fx(CHF)=1.0 = 1100  -> zaehlt
        #   PE:     shares=3, price=1000 -> WUERDE 3000 ergeben, ist aber
        #           ausgeschlossen (snapshot_service.py:47-48) -> Beitrag 0
        #   total = 1100 ; cash = 0 (keine Cash-/count_as_cash-Position)
        monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {"USD": 0.9})
        monkeypatch.setattr("services.cache.get", lambda k: None)
        uid = uuid.uuid4()
        db.add_all([
            _mk_pos(uid, ticker="AAA", shares=Decimal("10"), current_price=Decimal("110")),
            _mk_pos(uid, ticker="PE", type=AssetType.private_equity,
                    shares=Decimal("3"), current_price=Decimal("1000")),
        ])
        await db.commit()
        total, cash = await _calc_portfolio_value_fast(db, uid)
        assert total == pytest.approx(1100.0, abs=1e-6)
        assert cash == pytest.approx(0.0, abs=1e-6)

    async def test_count_as_cash_not_double_counted(self, db, monkeypatch):
        # Herleitung: count_as_cash-ETF wird regulaer bepreist und EINMAL in
        # total_value gezaehlt, zusaetzlich (mit demselben Wert) in cash_value
        # (snapshot_service.py:106-108) — KEIN Doppelzaehlen im total.
        #   shares=20 x price=50 x fx(CHF)=1.0 = 1000
        #   total = 1000 ; cash = 1000 (gleicher Wert, nicht 2000 im total)
        monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
        monkeypatch.setattr("services.cache.get", lambda k: None)
        uid = uuid.uuid4()
        db.add(_mk_pos(uid, ticker="TBILL", type=AssetType.etf,
                       shares=Decimal("20"), current_price=Decimal("50"),
                       count_as_cash=True))
        await db.commit()
        total, cash = await _calc_portfolio_value_fast(db, uid)
        assert total == pytest.approx(1000.0, abs=1e-6)
        assert cash == pytest.approx(1000.0, abs=1e-6)

    async def test_cash_and_pension_in_total_and_cash(self, db, monkeypatch):
        # Herleitung: Cash UND Vorsorge fliessen als Saldo (cost_basis_chf) in
        # total_value UND cash_value (snapshot_service.py:49-65).
        #   Cash:     5000 (CHF) -> +5000 total, +5000 cash
        #   Pension:  8000 (CHF) -> +8000 total, +8000 cash
        #   total = 13000 ; cash = 13000
        # Pinnt explizit, dass pension hier zum Cash-Topf zaehlt (Kommentar
        # snapshot_service.py:225 "Vorsorge zaehlt zu cash im PortfolioSnapshot").
        monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
        monkeypatch.setattr("services.cache.get", lambda k: None)
        uid = uuid.uuid4()
        db.add_all([
            _mk_pos(uid, ticker="CASH", type=AssetType.cash,
                    shares=Decimal("0"), cost_basis_chf=Decimal("5000")),
            _mk_pos(uid, ticker="PK", type=AssetType.pension,
                    shares=Decimal("0"), cost_basis_chf=Decimal("8000")),
        ])
        await db.commit()
        total, cash = await _calc_portfolio_value_fast(db, uid)
        assert total == pytest.approx(13000.0, abs=1e-6)
        assert cash == pytest.approx(13000.0, abs=1e-6)

    async def test_full_mix_aggregate(self, db, monkeypatch):
        # Herleitung (Komposition aller Regeln in einem Aggregat):
        #   Aktie:           10 x 110 x 1.0 = 1100   -> total +1100
        #   count_as_cash:   20 x 50  x 1.0 = 1000   -> total +1000, cash +1000
        #   Cash-Saldo:                       5000   -> total +5000, cash +5000
        #   Private Equity:  ausgeschlossen      0   -> total +0
        #   total = 1100 + 1000 + 5000 + 0 = 7100
        #   cash  = 1000 + 5000           = 6000
        monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
        monkeypatch.setattr("services.cache.get", lambda k: None)
        uid = uuid.uuid4()
        db.add_all([
            _mk_pos(uid, ticker="AAA", shares=Decimal("10"), current_price=Decimal("110")),
            _mk_pos(uid, ticker="TBILL", type=AssetType.etf, shares=Decimal("20"),
                    current_price=Decimal("50"), count_as_cash=True),
            _mk_pos(uid, ticker="CASH", type=AssetType.cash,
                    shares=Decimal("0"), cost_basis_chf=Decimal("5000")),
            _mk_pos(uid, ticker="PE", type=AssetType.private_equity,
                    shares=Decimal("3"), current_price=Decimal("1000")),
        ])
        await db.commit()
        total, cash = await _calc_portfolio_value_fast(db, uid)
        assert total == pytest.approx(7100.0, abs=1e-6)
        assert cash == pytest.approx(6000.0, abs=1e-6)


class TestGoldenMasterExclusionSets:
    """Konstanten-Pins (snapshot_service.py:219-235). Exakte Mengen-Gleichheit
    faengt sowohl Hinzufuegen (z.B. real_estate/PE wandert ins Liquid-Set) als
    auch Entfernen (z.B. pension faellt raus) — staerker als reine Membership."""

    def test_liquid_asset_types_exact(self):
        # Soll (snapshot_service.py:219-226): stock, etf, crypto, commodity,
        # cash, pension. real_estate und private_equity FEHLEN bewusst.
        assert _LIQUID_ASSET_TYPES == {
            AssetType.stock,
            AssetType.etf,
            AssetType.crypto,
            AssetType.commodity,
            AssetType.cash,
            AssetType.pension,
        }

    def test_excluded_from_bucket_sums_exact(self):
        # Soll (snapshot_service.py:232-235): genau real_estate + private_equity
        # werden aus den Bucket-Summen ausgeschlossen.
        assert _EXCLUDED_FROM_BUCKET_SUMS == {
            BucketSystemRole.real_estate,
            BucketSystemRole.private_equity,
        }


# ======================================================================
# MRS-Erweiterung + Modified-Dietz-Randgewichte
# ======================================================================

# ===========================================================================
# Invariante 4 (Signal): MRS = EMA(13, adjust=False) auf Weekly-Daten,
# rs = stock_weekly / bench_weekly. ERWEITERUNG der bestehenden
# TestGoldenMasterMRS (5.94-Step) um:
#   - groessere Step-Up-Response (anderes exaktes EMA-Ergebnis)
#   - Underperformance (negatives MRS)
#   - Zwei-Schritt-EMA-Rekursion (beweist adjust=False ueber 2 Steps)
#   - Ratio-Richtung (Benchmark steigt, Stock flach -> negatives MRS)
#   - WEEKLY-Resampling-Beweis (taegliche Daten kollabieren auf Freitags-Werte)
# EMA-Rekursion (adjust=False, span=13 -> alpha = 2/(13+1) = 1/7):
#   ema[0] = rs[0];  ema[i] = (1/7)*rs[i] + (6/7)*ema[i-1]
# ===========================================================================
class TestMRSExtended:
    """Zusaetzliche exakte EMA(13,adjust=False)-Charakterisierungen.

    Alle Soll-Werte rein algebraisch hergeleitet (Newton/EMA von Hand),
    NIE durch Aufruf der Funktion bestimmt.
    """

    def _fridays(self, n):
        # n echte W-FRI-Stuetzpunkte (bereits woechentlich -> Resample No-op)
        return pd.date_range("2024-01-05", periods=n, freq="W-FRI")

    def test_ema13_step_up_14_percent_exact(self):
        # bench konstant 100; stock 19x 100, dann 114  => rs = [1.0]*19 + [1.14]
        # rs ist 19 Wochen konstant 1.0 -> EMA bleibt 1.0 bis Woche 19.
        # Letzte Woche: ema = 6/7*1.0 + 1/7*1.14 = (6 + 1.14)/7 = 7.14/7 = 1.02
        # mrs = (1.14/1.02 - 1)*100 = 0.12/1.02*100 = 11.7647... -> 11.76
        idx = self._fridays(20)
        bench = pd.Series([100.0] * 20, index=idx)
        stock = pd.Series([100.0] * 19 + [114.0], index=idx)
        assert _compute_mrs_from_close(stock, bench) == pytest.approx(11.76, abs=0.01)

    def test_ema13_underperformance_negative_mrs_exact(self):
        # bench konstant 100; stock 19x 100, dann 93  => rs = [1.0]*19 + [0.93]
        # ema_last = 6/7*1.0 + 1/7*0.93 = (6 + 0.93)/7 = 6.93/7 = 0.99
        # mrs = (0.93/0.99 - 1)*100 = -0.06/0.99*100 = -6.0606... -> -6.06
        # Pinnt, dass Unterperformance ein NEGATIVES MRS liefert (Vorzeichen).
        idx = self._fridays(20)
        bench = pd.Series([100.0] * 20, index=idx)
        stock = pd.Series([100.0] * 19 + [93.0], index=idx)
        assert _compute_mrs_from_close(stock, bench) == pytest.approx(-6.06, abs=0.01)

    def test_ema13_two_step_recursion_exact(self):
        # bench konstant 100; stock 18x 100, dann 107, 107 => rs = [1.0]*18 + [1.07, 1.07]
        # ema bleibt 1.0 bis Woche 18.
        # Woche 19: ema = 6/7*1.0   + 1/7*1.07 = 7.07/7 = 1.01
        # Woche 20: ema = 6/7*1.01  + 1/7*1.07 = (6.06 + 1.07)/7 = 7.13/7 = 1.0185714286
        # mrs = (1.07/1.0185714286 - 1)*100 = (1.07*7/7.13 - 1)*100
        #     = (7.49/7.13 - 1)*100 = (1.0504908836 - 1)*100 = 5.0491 -> 5.05
        # Zwei aufeinanderfolgende Steps trennen adjust=False (rekursiv) sauber
        # von adjust=True (gewichtetes Gesamt-Mittel) -- staerker als 1-Step.
        idx = self._fridays(20)
        bench = pd.Series([100.0] * 20, index=idx)
        stock = pd.Series([100.0] * 18 + [107.0, 107.0], index=idx)
        assert _compute_mrs_from_close(stock, bench) == pytest.approx(5.05, abs=0.01)

    def test_ratio_direction_benchmark_in_denominator(self):
        # Beweist rs = STOCK / BENCH (Benchmark im Nenner):
        # stock konstant 100; bench 19x 100, dann 105 => rs = [1.0]*19 + [100/105]
        # rs_last = 100/105 = 20/21
        # ema_last = 6/7*1.0 + 1/7*(20/21) = (126/21 + 20/21)/7 = (146/21)/7 = 146/147
        # mrs = ((20/21)/(146/147) - 1)*100 = (20/21 * 147/146 - 1)*100
        #     = (140/146 - 1)*100 = (70/73 - 1)*100 = (-3/73)*100 = -4.10958... -> -4.11
        # Steigt der Benchmark bei flachem Stock, MUSS MRS negativ sein.
        idx = self._fridays(20)
        stock = pd.Series([100.0] * 20, index=idx)
        bench = pd.Series([100.0] * 19 + [105.0], index=idx)
        assert _compute_mrs_from_close(stock, bench) == pytest.approx(-4.11, abs=0.01)

    def test_daily_data_collapses_to_weekly_w_fri(self):
        # BEWEIS: resample('W-FRI').last() greift nur die Freitags-Werte.
        # 140 Kalendertage ab Sa 2024-01-06 -> Fr 2024-05-24 = exakt 20 ganze
        # Wochen (= 20 Freitage). Nicht-Freitags-Tage werden mit 999.0 vergiftet:
        # jede ANDERE Aggregation (mean/first) oder W-MON statt W-FRI ergaebe
        # vollkommen andere Werte. Die Freitags-Werte sind so gesetzt, dass die
        # woechentliche rs-Serie identisch zum bekannten 5.94-Step ist:
        #   rs_weekly = [1.0]*19 + [1.07] -> ema_last = 6/7 + 1.07/7 = 7.07/7 = 1.01
        #   mrs = (1.07/1.01 - 1)*100 = 0.06/1.01*100 = 5.9405... -> 5.94
        idx = pd.date_range("2024-01-06", periods=140, freq="D")  # Sa .. Fr
        fridays = idx[idx.dayofweek == 4]  # 20 Freitage
        bench = pd.Series([100.0] * len(idx), index=idx)
        stock = pd.Series([999.0] * len(idx), index=idx)  # Nicht-Fr = Gift
        stock.loc[fridays[:-1]] = 100.0
        stock.loc[fridays[-1]] = 107.0
        assert _compute_mrs_from_close(stock, bench) == pytest.approx(5.94, abs=0.01)


# ===========================================================================
# Invariante 3 (Modified Dietz): RANDGEWICHTE der Cashflow-Gewichtung.
# w_i = (days_in_month - (day - 1)) / days_in_month.
# Bestehender Test deckt nur Mid-Month (15/29). Hier:
#   - 1. des Monats -> Gewicht (D - 0)/D = 1.0 (voll mitgewichtet)
#   - letzter Tag   -> Gewicht (D - (D-1))/D = 1/D (kaum gewichtet)
# Beide trennen die korrekte Formel von einem (D - day)/D-Off-by-one.
# Maerz 2024 = 31 Tage. Februar-End-Snapshot dient als Start fuer Maerz.
# ===========================================================================
class TestModifiedDietzBoundaryWeights:
    async def test_cashflow_first_of_month_weight_one(self, db):
        # Maerz-Start = Feb-Ende = 10000; Maerz-Ende = 12000; Buy 1000 am 1.3.
        # weight = (31 - (1-1))/31 = 31/31 = 1.0  -> weighted_cf = 1000
        # R = (12000 - 10000 - 1000) / (10000 + 1000) * 100
        #   = 1000 / 11000 * 100 = 9.0909... -> 9.09
        # (Off-by-one (31-1)/31 ergaebe 9.12 -> waere unterscheidbar.)
        uid = uuid.uuid4()
        db.add_all([
            PortfolioSnapshot(user_id=uid, date=date(2024, 2, 29),
                              total_value_chf=Decimal("10000"),
                              cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0")),
            PortfolioSnapshot(user_id=uid, date=date(2024, 3, 31),
                              total_value_chf=Decimal("12000"),
                              cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0")),
        ])
        db.add(Transaction(
            user_id=uid, position_id=uuid.uuid4(), type=TransactionType.buy,
            date=date(2024, 3, 1), shares=Decimal("1"),
            price_per_share=Decimal("1000"), currency="CHF", total_chf=Decimal("1000"),
        ))
        await db.commit()
        res = await _monthly_returns_modified_dietz(db, uid, date(2024, 2, 1))
        by = {(r["year"], r["month"]): r["return_pct"] for r in res}
        assert by[(2024, 3)] == pytest.approx(9.09, abs=0.01)

    async def test_cashflow_last_day_weight_minimal(self, db):
        # Maerz-Start = 10000; Maerz-Ende = 12000; Buy 1000 am 31.3.
        # weight = (31 - (31-1))/31 = 1/31  -> weighted_cf = 1000/31 = 32.258
        # R = (12000 - 10000 - 1000) / (10000 + 32.258) * 100
        #   = 1000 / 10032.258 * 100 = 9.9678... -> 9.97
        # (Off-by-one (31-31)/31 = 0 ergaebe glatt 10.0 -> unterscheidbar.)
        uid = uuid.uuid4()
        db.add_all([
            PortfolioSnapshot(user_id=uid, date=date(2024, 2, 29),
                              total_value_chf=Decimal("10000"),
                              cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0")),
            PortfolioSnapshot(user_id=uid, date=date(2024, 3, 31),
                              total_value_chf=Decimal("12000"),
                              cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0")),
        ])
        db.add(Transaction(
            user_id=uid, position_id=uuid.uuid4(), type=TransactionType.buy,
            date=date(2024, 3, 31), shares=Decimal("1"),
            price_per_share=Decimal("1000"), currency="CHF", total_chf=Decimal("1000"),
        ))
        await db.commit()
        res = await _monthly_returns_modified_dietz(db, uid, date(2024, 2, 1))
        by = {(r["year"], r["month"]): r["return_pct"] for r in res}
        assert by[(2024, 3)] == pytest.approx(9.97, abs=0.01)
