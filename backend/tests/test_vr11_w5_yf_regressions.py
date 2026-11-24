"""Vollreview 11/2026, Welle 5, Fixer «yf»: Fehler, die die Fixes selbst einführten.

R-yfanalysis-1  None von yfinance ist ein gescheiterter Abruf, kein Titel ohne Dividende
R-yfanalysis-4  yf_download ohne gültiges Symbol liefert die Frame-Form von yfinance
R-yfanalysis-6  GBp wird nur dort zu GBP, wo der Pence-Divisor die Kurse teilt

Netzfrei: yf.download und yf.Ticker sind ersetzt.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import select

import services.cache_service as cache_service
import services.dividend_service as ds
import yf_patch
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services import cache
from services.bucket_service import create_bucket, create_system_buckets
from services.history_service import _build_price_series
from services.snapshot_service import _build_close_series, regenerate_snapshots
from services.ticker_info_service import _normalize_currency, get_ticker_info_cached


def _no_yahoo(*args, **kwargs):
    raise AssertionError("Yahoo darf hier nicht gefragt werden")


# --- R-yfanalysis-1: Dividenden-Negativ-Cache --------------------------------------


class _RecordingCache:
    """Dict-Cache, der die TTL je Schlüssel festhält."""

    def __init__(self):
        self.store: dict = {}
        self.ttls: dict = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value
        self.ttls[key] = ttl


class TestDividendFetchFailure:
    def _setup(self, monkeypatch, answers: list):
        """``answers``: was yf_ticker_attr(…, "dividends") der Reihe nach liefert."""
        recording = _RecordingCache()
        calls: list[str] = []

        def _attr(ticker, attr):
            assert attr == "dividends"
            calls.append(ticker)
            return answers[len(calls) - 1]

        monkeypatch.setattr(ds, "cache", recording)
        monkeypatch.setattr(ds, "yf_ticker_attr", _attr)
        monkeypatch.setattr(ds, "yf_fast_info", lambda t, fields: {"currency": "USD"})
        monkeypatch.setattr(ds, "get_fx_rate", lambda c, t="CHF": 0.9)
        return recording, calls

    def test_none_from_yfinance_is_cached_only_briefly(self, monkeypatch, caplog):
        """Yahoo-Timeout: yfinance wirft nicht, ``dividends`` ist None. Das darf
        nicht sechs Stunden als «keine Dividende» gelten."""
        recording, calls = self._setup(monkeypatch, [None])
        since = date.today() - timedelta(days=365)

        with caplog.at_level("WARNING", logger=ds.logger.name):
            assert ds.fetch_dividends("KO", since, shares=10.0) == []

        assert recording.ttls == {f"divs_ps:KO:{since.isoformat()}": ds._ERROR_CACHE_TTL}
        assert ds._ERROR_CACHE_TTL == 300
        assert any("KO" in r.getMessage() for r in caplog.records)

    def test_failed_fetch_heals_after_the_short_ttl(self, monkeypatch):
        """Nach Ablauf der kurzen Frist liefert der nächste Abruf die Dividende."""
        paid = pd.Series([0.5], index=[pd.Timestamp(date.today() - timedelta(days=30))])
        recording, calls = self._setup(monkeypatch, [None, paid])
        since = date.today() - timedelta(days=365)

        assert ds.fetch_dividends("KO", since, shares=10.0) == []
        # Innerhalb der Frist: aus dem Cache, Yahoo wird nicht erneut gefragt (K009).
        assert ds.fetch_dividends("KO", since, shares=10.0) == []
        assert calls == ["KO"]

        recording.store.clear()  # die 300 Sekunden sind um
        rows = ds.fetch_dividends("KO", since, shares=10.0)

        assert rows[0]["total_chf"] == pytest.approx(10 * 0.5 * 0.9)
        assert list(recording.ttls.values()) == [3600]

    def test_empty_series_keeps_the_long_negative_cache(self, monkeypatch):
        """Titel ohne Dividende: leere Series, weiterhin sechs Stunden (K009)."""
        recording, calls = self._setup(monkeypatch, [pd.Series([], dtype=float)])

        assert ds.fetch_dividends("NODIV", date.today() - timedelta(days=365), shares=1.0) == []
        assert list(recording.ttls.values()) == [ds._EMPTY_CACHE_TTL]
        assert ds._EMPTY_CACHE_TTL == 6 * 3600


# --- R-yfanalysis-4: Frame ohne gültiges Symbol ------------------------------------


class _FailingTicker:
    """Ersetzt yfinance.multi.Ticker: jeder Kursabruf scheitert."""

    def __init__(self, *args, **kwargs):
        pass

    def history(self, *args, **kwargs):
        raise RuntimeError("network down")


class TestDownloadWithoutValidSymbol:
    def test_single_invalid_symbol_yields_an_empty_series_not_none(self, monkeypatch):
        """Ein Freitext-Ticker als einziges Symbol: beide Reihenbauer liefern eine
        leere Kursreihe. Mit einem spaltenlosen Frame gaben sie None zurück."""
        monkeypatch.setattr(yf_patch.yf, "download", _no_yahoo)

        frame = yf_patch.yf_download(["ROCHE GS"], start="2026-01-01", auto_adjust=True)

        assert frame.empty and "Close" in frame.columns
        assert _build_close_series(frame, ["ROCHE GS"]) == {"ROCHE GS": ([], [])}
        assert _build_price_series(frame, ["ROCHE GS"], {}) == {"ROCHE GS": []}

    def test_two_invalid_symbols_still_yield_empty_series(self, monkeypatch):
        monkeypatch.setattr(yf_patch.yf, "download", _no_yahoo)

        frame = yf_patch.yf_download(["ROCHE GS", "A,B"], start="2026-01-01")

        assert _build_close_series(frame, ["ROCHE GS", "A,B"]) == {
            "ROCHE GS": ([], []), "A,B": ([], []),
        }
        assert _build_price_series(frame, ["ROCHE GS", "A,B"], {}) == {"ROCHE GS": [], "A,B": []}

    @pytest.mark.parametrize(
        "symbols,kwargs",
        [
            (["ROCHE GS"], {}),
            (["roche gs"], {"auto_adjust": True}),
            (["ROCHE GS"], {"group_by": "ticker"}),
            (["ROCHE GS"], {"actions": True}),
            (["ROCHE GS"], {"multi_level_index": False}),
            (["ROCHE GS"], {"multi_level_index": False, "group_by": "ticker"}),
            (["A B", "C,D"], {}),
        ],
    )
    def test_frame_matches_what_yfinance_returns_for_failed_symbols(
        self, monkeypatch, symbols, kwargs
    ):
        """Die Aufrufer kennen die Form, die yfinance für gescheiterte Symbole
        liefert. Der Wrapper liefert dieselbe, ohne Yahoo zu fragen."""
        monkeypatch.setattr("yfinance.multi.Ticker", _FailingTicker)
        expected = yf_patch.yf.download(list(symbols), progress=False, threads=False, **kwargs)

        monkeypatch.setattr(yf_patch.yf, "download", _no_yahoo)
        result = yf_patch.yf_download(list(symbols), **kwargs)

        pd.testing.assert_frame_equal(result, expected)

    def test_group_by_ticker_keeps_the_ticker_level_first(self, monkeypatch):
        monkeypatch.setattr(yf_patch.yf, "download", _no_yahoo)

        frame = yf_patch.yf_download(["A B", "C,D"], period="5d", group_by="ticker")

        assert frame.empty
        assert list(frame.columns.names) == ["Ticker", "Price"]
        assert frame["A B"]["Close"].dropna().empty and frame["C,D"]["Close"].dropna().empty

    @pytest.mark.parametrize("tickers", [[], [None], [42, None]])
    def test_nothing_to_label_stays_a_plain_empty_frame(self, monkeypatch, tickers):
        monkeypatch.setattr(yf_patch.yf, "download", _no_yahoo)

        frame = yf_patch.yf_download(tickers, period="5d")

        assert isinstance(frame, pd.DataFrame) and frame.empty

    def test_generator_argument_is_read_once(self, monkeypatch):
        monkeypatch.setattr(yf_patch.yf, "download", _no_yahoo)

        frame = yf_patch.yf_download((t for t in ["ROCHE GS"]), period="5d")

        assert list(frame["Close"].columns) == ["ROCHE GS"]

    @pytest.mark.asyncio
    async def test_regen_runs_for_a_depot_with_only_a_free_text_ticker(self, db, monkeypatch):
        """Szenario des Fundes: einzige Kursposition ist ein CHF-Titel mit
        Freitext-Ticker, kein FX-Paar. Der Regen endete mit «No price data
        returned» und liess die alten Snapshots stehen."""
        user = User(email=f"w5{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
        db.add(user)
        await db.commit()
        db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
        await db.commit()
        await db.refresh(user)
        await create_system_buckets(db, user.id)
        await db.commit()
        bucket = await create_bucket(db, user.id, name="Core")
        await db.commit()
        pos = Position(
            user_id=user.id, bucket_id=bucket.id, ticker="ROCHE GS", name="Roche GS",
            type=AssetType.stock, currency="CHF", shares=Decimal("10"),
            cost_basis_chf=Decimal("1000"), is_active=True,
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)
        db.add(Transaction(
            user_id=user.id, position_id=pos.id, type=TransactionType.buy,
            date=date.today() - timedelta(days=10), shares=Decimal("10"),
            price_per_share=Decimal("100"), currency="CHF", total_chf=Decimal("1000"),
        ))
        # Der Regen schreibt nur Werktage. Fällt «vor drei Tagen» auf ein Wochenende,
        # rückt der Tag auf den Freitag davor; sonst scheiterte der Test dienstags und mittwochs.
        stale_day = date.today() - timedelta(days=3)
        while stale_day.weekday() >= 5:
            stale_day -= timedelta(days=1)
        db.add(PortfolioSnapshot(
            user_id=user.id, date=stale_day, total_value_chf=Decimal("4321"),
            cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0"),
        ))
        await db.commit()
        monkeypatch.setattr(yf_patch.yf, "download", _no_yahoo)
        monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})

        result = await regenerate_snapshots(db, user.id)

        assert "error" not in result
        assert result["snapshots_created"] > 0
        snaps = list((await db.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user.id)
            .order_by(PortfolioSnapshot.date)
            .execution_options(populate_existing=True)
        )).scalars().all())
        by_day = {s.date: float(s.total_value_chf) for s in snaps}
        # Ohne Kursreihe zählt der Einstandswert; der alte Wert 4321 ist ersetzt.
        assert by_day[stale_day] == 1000.0
        assert float(snaps[-1].total_value_chf) == 1000.0


# --- R-yfanalysis-6: GBp nur mit Pence-Divisor zu GBP ------------------------------


def _patch_info(monkeypatch, info: dict) -> list[str]:
    calls: list[str] = []

    def fake(ticker, attr):
        calls.append(ticker)
        return dict(info)

    monkeypatch.setattr(yf_patch, "yf_ticker_attr", fake)
    return calls


class TestPenceCurrencyFollowsTheDivisor:
    @pytest.fixture(autouse=True)
    def _clean_ticker_info(self):
        # Der Cache überlebt Tests: eigene Schlüssel vorher und nachher entfernen.
        keys = ("ticker_info:SHEP.AQ", "ticker_info:BP.L")
        for key in keys:
            cache.delete(key)
        yield
        for key in keys:
            cache.delete(key)

    @pytest.mark.parametrize("raw", ["GBp", "GBX", "gbx", " GBp "])
    @pytest.mark.parametrize("ticker", ["SHEP.AQ", "BARC.IL", "VODL.XC", "SHEL", "SHEL.l"])
    def test_pence_without_divisor_is_unknown(self, raw, ticker):
        """Ohne Divisor bleiben die Kurse in Pence. GBP ergäbe den 100-fachen Wert."""
        assert _normalize_currency(raw, ticker) is None

    @pytest.mark.parametrize("raw", ["GBp", "GBX", "gbx", " GBp "])
    def test_pence_on_a_london_ticker_is_gbp(self, raw):
        assert _normalize_currency(raw, "SHEL.L") == "GBP"

    @pytest.mark.parametrize("ticker", ["SHEL.L", "SHEP.AQ", "AAPL"])
    @pytest.mark.parametrize("raw,expected", [("GBP", "GBP"), ("gbp", "GBP"), ("USD", "USD"), ("ZAc", None)])
    def test_other_codes_do_not_depend_on_the_ticker(self, raw, expected, ticker):
        """Pfund (GBP) ist kein Pence: der Code bleibt für jeden Ticker GBP. Auch
        ein .L-Ticker in USD behält USD, die Endung sagt nichts über die Währung."""
        assert _normalize_currency(raw, ticker) == expected

    @pytest.mark.parametrize("ticker", ["SHEL.L", "SHEP.AQ", "BARC.IL", "VODL.XC", "AAPL", "SHEL.l"])
    def test_gbp_exactly_where_cache_service_divides_prices(self, monkeypatch, ticker):
        """Die Position führt GBP genau dann, wenn der Kurs in Pfund ankommt.
        Wer die Bedingung in cache_service._pence_divisor ändert, zieht
        ticker_info_service nach — sonst scheitert dieser Test."""
        monkeypatch.setattr(cache_service, "_quote_currency", lambda t: "GBp")

        prices_in_pounds = cache_service._pence_divisor(ticker) == 100.0

        assert (_normalize_currency("GBp", ticker) == "GBP") == prices_in_pounds

    @pytest.mark.asyncio
    async def test_pence_title_outside_london_keeps_the_booking_currency(self, monkeypatch):
        """Szenario des Fundes: Yahoo führt den Titel in GBp ohne Endung .L. Der
        Kurs bleibt in Pence (Divisor 1.0), die Position darf nicht GBP erhalten."""
        monkeypatch.setattr(cache_service, "_quote_currency", lambda t: "GBp")
        _patch_info(monkeypatch, {"shortName": "Shepherd Neame", "currency": "GBp"})

        info = await get_ticker_info_cached("SHEP.AQ")

        assert cache_service._pence_divisor("SHEP.AQ") == 1.0
        assert info["shortName"] == "Shepherd Neame"
        assert info["currency"] is None  # Aufrufer behält die Währung der Buchung
        assert cache.get("ticker_info:SHEP.AQ")["currency"] is None

    @pytest.mark.asyncio
    async def test_cached_entry_is_normalized_per_ticker_on_read(self, monkeypatch):
        calls = _patch_info(monkeypatch, {})
        cache.set("ticker_info:SHEP.AQ", {"shortName": "Shepherd", "longName": None, "currency": "GBp"})
        cache.set("ticker_info:BP.L", {"shortName": "BP", "longName": None, "currency": "GBp"})

        assert (await get_ticker_info_cached("SHEP.AQ"))["currency"] is None
        assert (await get_ticker_info_cached("BP.L"))["currency"] == "GBP"
        assert calls == []
