"""Vollreview 11/2026, Fixer yfcache: yf_patch.py.

- K023: Symbole werden einzeln geprüft, yfinance bekommt eine Liste.
- K059: eigener Pool für Ticker-Abrufe, Wartezeit am Lock begrenzt.
- K116: fast_info-Felder werden unter dem Lock gelesen.

Netzfrei: yf.download und yf.Ticker sind ersetzt.
"""
from __future__ import annotations

import contextvars
import logging
import re
import threading
from pathlib import Path

import pandas as pd
import pytest

import yf_patch


class _Download:
    def __init__(self):
        self.calls: list[tuple[object, dict]] = []

    def __call__(self, tickers, **kwargs):
        self.calls.append((tickers, kwargs))
        return pd.DataFrame({"Close": [1.0]})


@pytest.fixture
def download(monkeypatch):
    fake = _Download()
    monkeypatch.setattr(yf_patch.yf, "download", fake)
    return fake


def _no_ticker(*args, **kwargs):
    raise AssertionError("yf.Ticker darf hier nicht aufgerufen werden")


# --- K023: Symbolprüfung ------------------------------------------------------


class TestDownloadSymbols:
    def test_list_element_with_separators_is_dropped_not_fanned_out(self, download):
        """Ein Listenelement ist genau ein Symbol. «A,B,C» aus einem Request darf
        nicht zu drei Yahoo-Abrufen werden."""
        yf_patch.yf_download(["AAPL", "A,B,C", "MSFT GOOG", "^GSPC"], period="5d")
        assert download.calls[0][0] == ["AAPL", "^GSPC"]

    def test_single_string_becomes_a_list(self, download):
        yf_patch.yf_download("EURCHF=X", period="5d")
        assert download.calls[0][0] == ["EURCHF=X"]

    @pytest.mark.parametrize(
        "joined",
        ["AAPL ^GSPC", "AAPL,MSFT", "AAPL ^GSPC,BRK-B", "EURCHF=X USDCHF=X", " AAPL", "AAPL,"],
    )
    def test_string_is_one_symbol_and_is_never_split(self, download, caplog, joined):
        """Eine Zeichenkette ist genau EIN Symbol. Mit Leerzeichen oder Komma ist
        sie ungültig und wird verworfen, nicht in mehrere Symbole geteilt."""
        with caplog.at_level(logging.WARNING, logger="yf_patch"):
            result = yf_patch.yf_download(joined, period="5d")
        assert download.calls == []
        assert isinstance(result, pd.DataFrame) and result.empty
        messages = [r.getMessage() for r in caplog.records if r.name == "yf_patch"]
        assert len(messages) == 1
        assert "dropped 1 invalid ticker symbol(s)" in messages[0]

    def test_no_backend_caller_passes_a_joined_string_literal(self):
        """Mehrere Symbole kommen als Liste. Ein Aufrufer, der sie in einer
        Zeichenkette verbindet, bekäme sonst still einen leeren Frame."""
        backend = Path(yf_patch.__file__).resolve().parent
        # Erstes Argument als Literal mit Leerzeichen oder Komma, direkt
        # (yf_download("A B")) oder über asyncio.to_thread(yf_download, "A B").
        joined = re.compile(r"""yf_download\s*[(,]\s*f?(["'])(?:(?!\1)[^\n])*[ ,](?:(?!\1)[^\n])*\1""")
        offenders = [
            f"{path.relative_to(backend)}: {match.group(0)}"
            for path in sorted(backend.rglob("*.py"))
            if path.relative_to(backend).parts[0] != "tests"
            for match in joined.finditer(path.read_text(encoding="utf-8"))
        ]
        assert offenders == []

    @pytest.mark.parametrize(
        "symbol",
        ["AAPL;rm", "../../etc", "A" * 31, "", "AAPL\n", "AA PL", "A/B", None, 42],
    )
    def test_invalid_symbol_never_reaches_yahoo(self, download, symbol):
        result = yf_patch.yf_download([symbol], period="5d")
        assert download.calls == []
        assert isinstance(result, pd.DataFrame) and result.empty

    @pytest.mark.parametrize(
        "symbol", ["AAPL", "^GSPC", "BRK-B", "EURCHF=X", "GC=F", "BTC-USD", "M&M.NS", "0P0000A1B2.SW"]
    )
    def test_real_yahoo_symbols_pass(self, download, symbol):
        yf_patch.yf_download([symbol], period="5d")
        assert download.calls[0][0] == [symbol]

    def test_duplicates_are_sent_once(self, download):
        yf_patch.yf_download(["AAPL", "MSFT", "AAPL"], period="5d")
        assert download.calls[0][0] == ["AAPL", "MSFT"]

    def test_dropped_symbols_are_logged_truncated(self, download, caplog):
        with caplog.at_level(logging.WARNING, logger="yf_patch"):
            yf_patch.yf_download(["AAPL", "X" * 500, "A,B"], period="5d")
        messages = [r.getMessage() for r in caplog.records if r.name == "yf_patch"]
        assert len(messages) == 1
        assert "dropped 2 invalid ticker symbol(s)" in messages[0]
        assert len(messages[0]) < 200

    def test_threads_stay_off(self, download):
        yf_patch.yf_download(["AAPL"], period="5d", threads=True)
        assert download.calls[0][1]["threads"] is False
        assert download.calls[0][1]["progress"] is False


class TestTickerSymbols:
    @pytest.mark.parametrize("symbol", ["A,B", "AAPL MSFT", "../x", "", "A" * 31])
    def test_ticker_helpers_reject_invalid_symbols(self, monkeypatch, symbol):
        monkeypatch.setattr(yf_patch.yf, "Ticker", _no_ticker)
        with pytest.raises(ValueError):
            yf_patch.yf_ticker_attr(symbol, "info")
        with pytest.raises(ValueError):
            yf_patch.yf_earnings_dates(symbol)
        with pytest.raises(ValueError):
            yf_patch.yf_fast_info(symbol, ("currency",))
        assert yf_patch.yf_quote_currency(symbol) is None
        assert not yf_patch._ticker_lock.locked()


# --- K059: Lock mit Frist, eigener Pool ----------------------------------------


def _run_with_deadline(fn, seconds: float = 5.0) -> dict:
    """fn in einem Thread ausführen; hängt er, scheitert der Test statt zu stehen."""
    out: dict = {}

    def target():
        try:
            out["result"] = fn()
        except BaseException as e:  # noqa: BLE001 — der Test prüft den Typ
            out["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "Aufruf wartet ohne Frist auf das Ticker-Lock"
    return out


class TestTickerLock:
    @pytest.mark.parametrize(
        "call",
        [
            lambda: yf_patch.yf_ticker_attr("AAPL", "info"),
            lambda: yf_patch.yf_fast_info("AAPL", ("currency",)),
            lambda: yf_patch.yf_search("apple"),
            lambda: yf_patch.yf_earnings_dates("AAPL"),
        ],
        ids=["ticker_attr", "fast_info", "search", "earnings_dates"],
    )
    def test_waiting_for_the_lock_is_bounded(self, monkeypatch, call):
        monkeypatch.setattr(yf_patch, "_TICKER_LOCK_TIMEOUT_S", 0.05)
        monkeypatch.setattr(yf_patch.yf, "Ticker", _no_ticker)
        monkeypatch.setattr(yf_patch.yf, "Search", _no_ticker)

        assert yf_patch._ticker_lock.acquire(timeout=1)
        try:
            out = _run_with_deadline(call)
        finally:
            yf_patch._ticker_lock.release()

        assert isinstance(out.get("error"), yf_patch.YfTickerLockTimeout)

    def test_lock_timeout_is_twenty_seconds(self):
        assert yf_patch._TICKER_LOCK_TIMEOUT_S == 20.0

    def test_quote_currency_treats_a_busy_lock_as_unknown(self, monkeypatch):
        monkeypatch.setattr(yf_patch, "_TICKER_LOCK_TIMEOUT_S", 0.05)
        monkeypatch.setattr(yf_patch.yf, "Ticker", _no_ticker)
        assert yf_patch._ticker_lock.acquire(timeout=1)
        try:
            out = _run_with_deadline(lambda: yf_patch.yf_quote_currency("SHEL.L"))
        finally:
            yf_patch._ticker_lock.release()
        assert out == {"result": None}

    def test_lock_is_released_after_success_and_after_an_error(self, monkeypatch):
        class _Ticker:
            def __init__(self, symbol):
                self.info = {"symbol": symbol}

            @property
            def calendar(self):
                raise RuntimeError("yahoo down")

        monkeypatch.setattr(yf_patch.yf, "Ticker", _Ticker)
        assert yf_patch.yf_ticker_attr("AAPL", "info") == {"symbol": "AAPL"}
        assert not yf_patch._ticker_lock.locked()
        with pytest.raises(RuntimeError):
            yf_patch.yf_ticker_attr("AAPL", "calendar")
        assert not yf_patch._ticker_lock.locked()


class TestTickerPool:
    def test_pool_has_three_threads(self):
        assert yf_patch._ticker_executor._max_workers == 3

    async def test_yf_to_thread_runs_outside_the_default_executor(self):
        name = await yf_patch.yf_to_thread(lambda: threading.current_thread().name)
        assert name.startswith("yf-ticker")

    async def test_yf_to_thread_passes_arguments_and_context(self):
        var: contextvars.ContextVar[str] = contextvars.ContextVar("vr11_yfcache", default="unset")
        var.set("request-7")

        def work(a, b, *, c):
            return a + b + c, var.get()

        assert await yf_patch.yf_to_thread(work, 1, 2, c=3) == (6, "request-7")

    async def test_yf_to_thread_propagates_errors(self):
        def boom():
            raise RuntimeError("yahoo down")

        with pytest.raises(RuntimeError):
            await yf_patch.yf_to_thread(boom)


# --- K116: fast_info unter dem Lock --------------------------------------------


@pytest.fixture
def lazy_ticker(monkeypatch):
    """yf.Ticker, dessen fast_info wie das echte erst beim Feldzugriff «lädt»
    und dabei festhält, ob das Ticker-Lock gehalten wird."""
    locked_at_access: list[bool] = []

    class _FastInfo:
        @property
        def currency(self):
            locked_at_access.append(yf_patch._ticker_lock.locked())
            return "GBp"

        @property
        def last_price(self):
            locked_at_access.append(yf_patch._ticker_lock.locked())
            return 2512.5

    class _Ticker:
        def __init__(self, symbol):
            self.fast_info = _FastInfo()

    monkeypatch.setattr(yf_patch.yf, "Ticker", _Ticker)
    return locked_at_access


class TestFastInfo:
    def test_fields_are_read_while_the_lock_is_held(self, lazy_ticker):
        values = yf_patch.yf_fast_info("SHEL.L", ("last_price", "currency", "no_such_field"))
        assert values == {"last_price": 2512.5, "currency": "GBp", "no_such_field": None}
        assert lazy_ticker == [True, True]
        assert not yf_patch._ticker_lock.locked()

    def test_quote_currency_reads_under_the_lock(self, lazy_ticker):
        assert yf_patch.yf_quote_currency("SHEL.L") == "GBp"
        assert lazy_ticker == [True]

    def test_quote_currency_is_none_on_failure(self, monkeypatch):
        def broken(symbol):
            raise RuntimeError("yahoo down")

        monkeypatch.setattr(yf_patch.yf, "Ticker", broken)
        assert yf_patch.yf_quote_currency("SHEL.L") is None
        assert not yf_patch._ticker_lock.locked()
