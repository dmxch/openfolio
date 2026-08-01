"""Tests fuer den Stampede-Schutz im Thread-Pfad (``cache.single_flight``).

Der Cache-Miss-Pfad der Kursabfragen laeuft synchron und wird aus async-Handlern
via ``asyncio.to_thread`` aufgerufen — die Nebenlaeufigkeit entsteht ueber
Threads. Ohne Schutz laedt bei kaltem Cache jeder gleichzeitige Request dieselbe
Reihe erneut; parallele yfinance-Bursts sind die dokumentierte Ursache
stundenlanger IP-Sperren.

Die Tests benutzen echte Threads. Ein Test mit sequentiellen Aufrufen wuerde
genau das nicht pruefen, worum es geht.
"""
from __future__ import annotations

import threading
import time

import pytest

from services import cache


def _run_concurrently(fn, n: int, timeout: float = 10.0) -> list:
    """n Threads starten, alle moeglichst gleichzeitig loslassen, Ergebnisse sammeln."""
    start = threading.Barrier(n)
    results: list = [None] * n
    errors: list = []

    def worker(i: int):
        try:
            start.wait(timeout=timeout)
            results[i] = fn()
        except Exception as e:  # pragma: no cover — nur zur Diagnose
            errors.append(e)

    # daemon=True: bei einem Deadlock-Regress feuert die Assertion, ohne dass
    # der Pytest-Prozess am Interpreter-Exit auf den haengenden Thread wartet
    # (das ergaebe einen CI-Timeout statt einer lesbaren Fehlermeldung).
    threads = [
        threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout)
    assert not errors, f"Worker-Fehler: {errors}"
    assert all(not t.is_alive() for t in threads), "Thread haengt — Deadlock?"
    return results


def test_only_one_thread_produces(monkeypatch):
    """Acht gleichzeitige Anfragen auf denselben Key → genau ein Producer-Lauf."""
    key = f"sf-test-{time.monotonic_ns()}"
    calls: list[int] = []
    store: dict = {}
    lock = threading.Lock()

    def produce():
        with cache.single_flight(key) as leader:
            if not leader:
                return store.get(key)
            with lock:
                calls.append(1)
            # Downloadzeit — ohne sie startet niemand parallel. Grosszuegig
            # bemessen, damit ein kurz descheduleter Thread nicht faelschlich
            # Zweit-Leader wird und den Test flaky macht.
            time.sleep(0.2)
            store[key] = "wert"
            return store[key]

    results = _run_concurrently(produce, 8)
    assert len(calls) == 1, f"{len(calls)} Producer-Laeufe statt 1"
    assert all(r == "wert" for r in results), f"Follower ohne Ergebnis: {results}"


def test_leader_exception_releases_waiters(monkeypatch):
    """Stirbt der Leader an einer Exception, duerfen die Follower nicht bis zum
    Timeout haengen — der Eintrag muss auch im Fehlerfall abgeraeumt werden."""
    key = f"sf-boom-{time.monotonic_ns()}"
    seen: list[str] = []
    lock = threading.Lock()

    def produce():
        try:
            with cache.single_flight(key, timeout=5.0) as leader:
                with lock:
                    seen.append("leader" if leader else "follower")
                if leader:
                    raise RuntimeError("Download kaputt")
                return "follower-fertig"
        except RuntimeError:
            return "leader-fehler"

    t0 = time.monotonic()
    results = _run_concurrently(produce, 4)
    elapsed = time.monotonic() - t0

    assert "leader-fehler" in results
    assert elapsed < 4.0, f"Follower liefen in den Timeout ({elapsed:.1f}s)"
    # Der Key darf nach dem Fehler nicht als "in Arbeit" haengenbleiben.
    assert key not in cache._inflight


def test_timeout_lets_follower_produce_itself():
    """Haengt der Leader, laedt der Follower nach dem Timeout selbst.

    Doppelt laden ist unschoen, haengen ist schlimmer.
    """
    key = f"sf-hang-{time.monotonic_ns()}"
    # Leader-Event von Hand setzen, ohne dass je ein Leader fertig wird.
    with cache._inflight_lock:
        cache._inflight[key] = threading.Event()
    try:
        with cache.single_flight(key, timeout=0.1) as leader:
            assert leader is True, "Follower muss nach Timeout selbst produzieren"
    finally:
        with cache._inflight_lock:
            cache._inflight.pop(key, None)


def test_different_keys_do_not_block_each_other():
    """Zwei verschiedene Keys laufen parallel — der Schutz ist pro Key.

    Bewusst OHNE Stoppuhr: eine Zeitgrenze waere auf ausgelasteter CI ein
    Flake-Kandidat. Stattdessen haelt Thread A den Key `ka` nachweislich besetzt,
    waehrend der Haupt-Thread `kb` betritt — kommt er durch, ist die
    Key-Unabhaengigkeit bewiesen, egal wie langsam die Maschine ist.
    """
    ka = f"sf-a-{time.monotonic_ns()}"
    kb = f"sf-b-{time.monotonic_ns()}"
    a_drin = threading.Event()
    a_darf_raus = threading.Event()

    def halte_ka():
        with cache.single_flight(ka) as leader:
            assert leader is True
            a_drin.set()
            a_darf_raus.wait(timeout=10.0)

    ta = threading.Thread(target=halte_ka, daemon=True)
    ta.start()
    try:
        assert a_drin.wait(timeout=10.0), "Thread A hat ka nie betreten"
        # A sitzt jetzt garantiert in single_flight(ka).
        with cache.single_flight(kb) as leader:
            assert leader is True, "kb wurde durch den offenen ka blockiert"
    finally:
        a_darf_raus.set()
        ta.join(timeout=10.0)
    assert not ta.is_alive()


def test_benchmark_closes_downloads_once_under_concurrency(monkeypatch):
    """Der reale Konsument: acht gleichzeitige Aufrufe → ein yfinance-Download."""
    import pandas as pd

    from services import benchmark_service

    ticker = f"SFTEST{time.monotonic_ns()}"
    downloads: list[str] = []
    lock = threading.Lock()
    store: dict = {}

    def fake_download(t, **kw):
        with lock:
            downloads.append(t)
        time.sleep(0.05)
        idx = pd.to_datetime(["2026-06-29", "2026-06-30"])
        return pd.DataFrame({"Close": [100.0, 101.0]}, index=idx)

    monkeypatch.setattr(benchmark_service, "yf_download", fake_download)
    monkeypatch.setattr(benchmark_service.cache, "get", lambda k: store.get(k))
    monkeypatch.setattr(
        benchmark_service.cache, "set", lambda k, v, ttl=None: store.__setitem__(k, v)
    )

    results = _run_concurrently(lambda: benchmark_service._get_benchmark_closes(ticker), 8)

    assert len(downloads) == 1, f"{len(downloads)} Downloads statt 1"
    assert all(r is not None and len(r) == 2 for r in results), (
        f"Nicht alle Aufrufer bekamen die Reihe: {results}"
    )
