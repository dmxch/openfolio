"""Fast-Follow zu v0.57.3 (Audit-Finding, LOW): der Post-Refresh-Sektor-Coverage-
Check im Worker (_check_sector_coverage_after_refresh) las EtfHolding.weight_pct
bisher ohne isfinite-Guard - der letzte ungehaertete Consumer derselben Spalte
(Quelle + die 4 anderen Consumer in concentration_service sind seit v0.57.2/
v0.57.3 gehaertet).

Ohne Guard vergiftet eine (historisch persistierte) NaN-Row `classified`/
`unclassified` zu NaN -> `classified_pct` wird NaN -> `NaN < SCHWELLE` ist
in Python IMMER False -> die Degraded-Warnung wird fuer den betroffenen ETF
still unterdrueckt, obwohl die echte (nicht-NaN) Coverage weit unter der
Schwelle liegt. Rein interne Log-Diagnostik, keine user-facing Zahl betroffen -
aber genau die Art von Silent-Decay, gegen die dieser Check antritt.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import pytest

import worker

pytestmark = pytest.mark.asyncio


def _fake_session_with_rows(rows):
    @asynccontextmanager
    async def _session():
        class _Result:
            def all(self_inner):
                return rows

        class _Db:
            async def execute(self_inner, *args, **kwargs):
                return _Result()

        yield _Db()

    return _session


async def test_nan_weight_row_does_not_suppress_degraded_warning(monkeypatch, caplog):
    # AAPL klassifiziert (10.0%), BADROW mit NaN-Gewicht (Datenfehler, sollte
    # ausgefiltert werden), XYZ unklassifiziert (5.0%, echte Luecke).
    rows = [
        ("SWDA", "AAPL", 10.0),
        ("SWDA", "BADROW", float("nan")),
        ("SWDA", "XYZ", 5.0),
    ]
    monkeypatch.setattr(worker, "async_session", _fake_session_with_rows(rows))

    import services.sector_classification_service as scs
    monkeypatch.setattr(
        scs, "classify_tickers_bulk",
        lambda tickers: {"AAPL": "Technology", "XYZ": None},
    )

    with caplog.at_level(logging.WARNING, logger="worker"):
        await worker._check_sector_coverage_after_refresh()

    # Kern-Assertion: die NaN-Row wird ausgefiltert -> classified=10.0,
    # unclassified=5.0 (nur XYZ) -> classified_pct = 66.67% < 95%-Schwelle
    # -> Warnung MUSS feuern (vorher: total/classified_pct wurden NaN,
    # die Warnung wurde still unterdrueckt).
    warnings = [r.message for r in caplog.records if "sector-coverage degraded" in r.message]
    assert len(warnings) == 1
    assert "SWDA" in warnings[0]
    assert "66.7%" in warnings[0]
    # Die NaN-Row darf nicht als unclassified-Ticker auftauchen.
    assert "BADROW" not in warnings[0]


async def test_all_nan_weights_no_crash_no_warning(monkeypatch, caplog):
    """Sind ALLE Gewichte eines ETF NaN, ist total<=0 nach dem Filter ->
    der ETF wird sauber uebersprungen statt eine NaN-basierte Falsch-Meldung
    zu produzieren."""
    rows = [("SWDA", "BADROW", float("nan"))]
    monkeypatch.setattr(worker, "async_session", _fake_session_with_rows(rows))

    import services.sector_classification_service as scs
    monkeypatch.setattr(scs, "classify_tickers_bulk", lambda tickers: {})

    with caplog.at_level(logging.WARNING, logger="worker"):
        await worker._check_sector_coverage_after_refresh()

    assert not any("sector-coverage degraded" in r.message for r in caplog.records)
