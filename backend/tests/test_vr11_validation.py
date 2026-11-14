"""Vollreview 11/2026, Fundament: api/validation.py und constants/currencies.py."""

from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ValidationError

from api.validation import (
    BOOKING_DATE_ERROR,
    MARKET_TICKER_PATTERN,
    MIN_BOOKING_DATE,
    BookingDate,
    CurrencyCode,
    MarketTicker,
    check_booking_date,
    escape_like,
    is_iso_currency,
    is_market_ticker,
)
from constants.currencies import ISO_4217_CODES
from dateutils import utcnow


class _Booking(BaseModel):
    date: BookingDate


class _Quote(BaseModel):
    ticker: MarketTicker
    currency: CurrencyCode


class TestBookingDate:
    def test_bounds_are_inclusive(self):
        tomorrow = utcnow().date() + timedelta(days=1)
        assert check_booking_date(MIN_BOOKING_DATE) == MIN_BOOKING_DATE
        assert check_booking_date(tomorrow) == tomorrow

    @pytest.mark.parametrize("bad", [date(1969, 12, 31), date(1, 1, 1), date(9999, 12, 31)])
    def test_rejects_out_of_range(self, bad):
        with pytest.raises(ValueError, match="01.01.1970"):
            check_booking_date(bad)

    def test_rejects_day_after_tomorrow(self):
        with pytest.raises(ValueError):
            check_booking_date(utcnow().date() + timedelta(days=2))

    def test_accepts_datetime_without_type_error(self):
        # Import-Zeilen tragen teils datetime; datetime < date wirft sonst TypeError.
        value = datetime(2024, 5, 1, 13, 30)
        assert check_booking_date(value) is value
        with pytest.raises(ValueError):
            check_booking_date(datetime(1900, 1, 1))

    def test_pydantic_type(self):
        assert _Booking(date="2024-03-01").date == date(2024, 3, 1)
        with pytest.raises(ValidationError) as exc:
            _Booking(date="0001-01-01")
        assert BOOKING_DATE_ERROR in str(exc.value)
        with pytest.raises(ValidationError):
            _Booking(date="9999-12-31")


class TestMarketTicker:
    @pytest.mark.parametrize("ticker", ["AAPL", "BRK-B", "^GSPC", "EURCHF=X", "ROG.SW", "BT&T", "a_b", "X" * 30])
    def test_accepts(self, ticker):
        assert is_market_ticker(ticker)
        assert _Quote(ticker=ticker, currency="CHF").ticker == ticker

    @pytest.mark.parametrize(
        "ticker",
        ["", "X" * 31, "AA PL", "AAPL\n", "AAPL;DROP", "../etc", "A%B", "A/B", "ÄBC", "A'B"],
    )
    def test_rejects(self, ticker):
        assert not is_market_ticker(ticker)
        with pytest.raises(ValidationError):
            _Quote(ticker=ticker, currency="CHF")

    def test_non_string_is_no_ticker(self):
        assert not is_market_ticker(None)

    def test_pattern_is_the_contract(self):
        assert MARKET_TICKER_PATTERN == r"^[A-Za-z0-9.^=&_-]{1,30}$"

    async def test_usable_as_path_parameter(self):
        app = FastAPI()

        @app.get("/t/{ticker}")
        async def read(ticker: MarketTicker):
            return {"ticker": ticker}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/t/NESN.SW")).json() == {"ticker": "NESN.SW"}
            assert (await c.get("/t/NESN%20SW")).status_code == 422
            assert (await c.get("/t/" + "A" * 31)).status_code == 422


class TestCurrency:
    def test_normalises_to_upper(self):
        assert _Quote(ticker="A", currency="chf").currency == "CHF"
        assert _Quote(ticker="A", currency="Usd").currency == "USD"

    @pytest.mark.parametrize("bad", ["", "CH", "CHFF", "C1F", " CHF", "CH F", "ÄÖÜ"])
    def test_rejects_anything_but_three_letters(self, bad):
        with pytest.raises(ValidationError):
            _Quote(ticker="A", currency=bad)

    def test_iso_set_contains_required_codes(self):
        required = {"CHF", "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "SEK", "NOK", "DKK", "HKD", "SGD"}
        assert required <= ISO_4217_CODES
        assert isinstance(ISO_4217_CODES, frozenset)
        assert all(len(c) == 3 and c.isascii() and c.isupper() for c in ISO_4217_CODES)

    def test_is_iso_currency(self):
        assert is_iso_currency("CHF")
        assert is_iso_currency("usd")
        # Formal gültig (drei Buchstaben), aber keine Währung: genau dafür ist die Liste da.
        assert not is_iso_currency("ZZZ")
        assert not is_iso_currency("XXX")
        assert not is_iso_currency("X01")
        assert not is_iso_currency("")
        assert not is_iso_currency(None)


class TestEscapeLike:
    def test_escapes_wildcards_and_backslash(self):
        assert escape_like("100%") == "100\\%"
        assert escape_like("a_b") == "a\\_b"
        assert escape_like("a\\b") == "a\\\\b"
        # Backslash zuerst: sonst würde der Escape des Prozentzeichens nochmals escapt.
        assert escape_like("\\%") == "\\\\\\%"
        assert escape_like("plain") == "plain"

    async def test_escaped_pattern_matches_literally(self, db):
        from sqlalchemy import literal, select

        async def like(value: str, needle: str) -> bool:
            stmt = select(literal(value).like(f"%{escape_like(needle)}%", escape="\\"))
            return bool((await db.execute(stmt)).scalar())

        assert await like("50% Rabatt", "50%")
        assert not await like("50 Franken", "50%")
        assert await like("a_b", "a_b")
        assert not await like("axb", "a_b")
