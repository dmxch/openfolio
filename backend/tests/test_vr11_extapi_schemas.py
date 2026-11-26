"""Vollreview 11/2026, externe API: Eingabe-Schemas.

K006 (Datum ohne Grenzen), K019 (coingecko_id frei wählbar), K023 (Ticker ohne
Muster), K110 (Zeitzone in expires_at), K111 (Enum-Werte und null bei
Positionen), K149 (Schema-Grenzen länger als die DB-Spalten).
"""

import typing
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from api import external_v1_schemas as schemas
from api.external_v1_schemas import (
    ExternalAlertCreate,
    ExternalAlertUpdate,
    ExternalDividendConfirm,
    ExternalMetalCreate,
    ExternalMetalExpenseCreate,
    ExternalMetalUpdate,
    ExternalMortgageCreate,
    ExternalPEHoldingCreate,
    ExternalPEHoldingUpdate,
    ExternalPEValuationCreate,
    ExternalPendingOrderCreate,
    ExternalPendingOrderFill,
    ExternalPendingOrderUpdate,
    ExternalPositionCreate,
    ExternalPositionUpdate,
    ExternalPropertyCreate,
    ExternalPropertyExpenseCreate,
    ExternalPropertyIncomeCreate,
    ExternalPropertyUpdate,
    ExternalStopLossBatchItem,
    ExternalStopLossUpdate,
    ExternalTagCreate,
    ExternalTransactionCreate,
    ExternalTransactionUpdate,
    ExternalWatchlistAdd,
)
from models.pending_order import PendingOrder
from models.position import Position, PriceSource, PricingMode, Style
from models.precious_metal_expense import PreciousMetalExpense
from models.precious_metal_item import PreciousMetalItem
from models.price_alert import PriceAlert
from models.private_equity import PrivateEquityHolding, PrivateEquityValuation
from models.property import Mortgage, Property, PropertyExpense, PropertyIncome
from models.transaction import Transaction
from models.watchlist import WatchlistItem
from models.watchlist_tag import WatchlistTag

TODAY = date.today()


def _position(**overrides) -> dict:
    return {"ticker": "AAPL", "name": "Apple", "type": "stock", **overrides}


# --- K006: Buchungs- und Fill-Daten ---


_BOOKING_CASES = [
    (ExternalTransactionCreate, "date", {"position_id": None, "ticker": "AAPL", "type": "buy"}),
    (ExternalTransactionUpdate, "date", {}),
    (ExternalPendingOrderFill, "fill_date", {"price_per_share": 10.0}),
    (ExternalDividendConfirm, "date", {"total_chf": 5.0}),
]


@pytest.mark.parametrize("model, field, base", _BOOKING_CASES, ids=lambda v: getattr(v, "__name__", None))
@pytest.mark.parametrize("bad", ["0002-01-01", "1700-01-01", "1969-12-31"])
def test_booking_date_rejects_dates_before_1970(model, field, base, bad):
    """Ohne Grenze lief der Snapshot-Regen Tag für Tag ab dem Jahr 2."""
    with pytest.raises(ValidationError):
        model(**base, **{field: bad})


@pytest.mark.parametrize("model, field, base", _BOOKING_CASES, ids=lambda v: getattr(v, "__name__", None))
def test_booking_date_rejects_far_future_and_accepts_today(model, field, base):
    with pytest.raises(ValidationError):
        model(**base, **{field: (TODAY + timedelta(days=30)).isoformat()})
    assert getattr(model(**base, **{field: TODAY.isoformat()}), field) == TODAY
    assert getattr(model(**base, **{field: "1970-01-01"}), field) == date(1970, 1, 1)


_PURCHASE_CASES = [
    (ExternalMetalCreate, "purchase_date",
     {"metal_type": "gold", "form": "bar", "weight_grams": 100.0, "purchase_price_chf": 1.0}),
    (ExternalMetalUpdate, "purchase_date", {}),
    (ExternalMetalUpdate, "sold_date", {}),
    (ExternalPropertyCreate, "purchase_date",
     {"name": "Haus", "property_type": "efh", "purchase_price": 1.0}),
    (ExternalPropertyUpdate, "purchase_date", {}),
    (ExternalPEHoldingCreate, "purchase_date",
     {"company_name": "Acme AG", "num_shares": 1, "nominal_value": 1.0}),
    (ExternalPEHoldingUpdate, "purchase_date", {}),
]


@pytest.mark.parametrize("model, field, base", _PURCHASE_CASES, ids=lambda v: getattr(v, "__name__", None))
def test_purchase_date_has_lower_bound_1900(model, field, base):
    """Kaufdaten dürfen vor 1970 liegen (Erbstück, altes Haus), aber nicht im Jahr 2."""
    with pytest.raises(ValidationError) as exc:
        model(**base, **{field: "1899-12-31"})
    assert schemas.PURCHASE_DATE_ERROR in str(exc.value)
    with pytest.raises(ValidationError):
        model(**base, **{field: "0002-01-01"})
    assert getattr(model(**base, **{field: "1950-06-01"}), field) == date(1950, 6, 1)
    assert getattr(model(**base, **{field: "1900-01-01"}), field) == date(1900, 1, 1)


# --- K023: Ticker, die an Yahoo gehen ---


@pytest.mark.parametrize("bad", ["AA,AB,AC", "AAPL MSFT", "A" * 31, "AAPL;DROP", "ÄPFEL"])
def test_watchlist_ticker_must_be_single_symbol(bad):
    """yfinance zerlegt «AA,AB AC» in drei Abrufe; der Worker lädt gespeicherte Ticker jede Minute."""
    with pytest.raises(ValidationError):
        ExternalWatchlistAdd(ticker=bad, name="x")


def test_pending_order_schema_leaves_the_ticker_format_to_the_route():
    """R-importtx-4: Das Schema kennt die Positionen des Users nicht.

    Muster und Besitz prüft die Route mit api.orders.resolve_order_ticker
    (tests/test_vr11_w6_handoffs.py: «AAPL MSFT» ohne Position 422, «BRK B» mit
    eigener Position 201). Das Schema hält nur Länge und Leerraum.
    """
    order = ExternalPendingOrderCreate(ticker=" brk b ", side="sell", shares=1, limit_price=1)
    assert order.ticker == "brk b"
    for bad in ["", "   ", "A" * 31]:
        with pytest.raises(ValidationError):
            ExternalPendingOrderCreate(ticker=bad, side="buy", shares=1, limit_price=1)


@pytest.mark.parametrize("good", ["AAPL", "brk-b", "^GSPC", "USDCHF=X", "IB01.L", "BTC-USD", "BF_B", "M&M.NS"])
def test_watchlist_and_pending_order_accept_market_tickers(good):
    assert ExternalWatchlistAdd(ticker=good, name="x").ticker == good
    assert ExternalPendingOrderCreate(ticker=good, side="buy", shares=1, limit_price=1).ticker == good


def test_ticker_whitespace_at_the_edges_is_still_stripped():
    """Bisher entfernte der Handler die Leerzeichen; das Muster darf das nicht zu einem 422 machen."""
    assert ExternalWatchlistAdd(ticker="  nvda ", name="x").ticker == "nvda"
    assert ExternalPendingOrderCreate(ticker=" nvda\n", side="buy", shares=1, limit_price=1).ticker == "nvda"


@pytest.mark.parametrize("asset_type", ["stock", "etf", "bond", "crypto"])
def test_position_create_checks_ticker_for_market_types(asset_type):
    with pytest.raises(ValidationError):
        ExternalPositionCreate(**_position(type=asset_type, ticker="AA,AB AC"))
    assert ExternalPositionCreate(**_position(type=asset_type, ticker="AAPL")).ticker == "AAPL"


@pytest.mark.parametrize("asset_type", ["cash", "pension", "real_estate", "private_equity", "commodity"])
def test_position_create_keeps_free_text_ticker_for_other_types(asset_type):
    pos = ExternalPositionCreate(**_position(type=asset_type, ticker="Konto Säule 3a, VIAC"))
    assert pos.ticker == "Konto Säule 3a, VIAC"


def test_position_create_gold_org_position_keeps_free_text_ticker():
    assert ExternalPositionCreate(**_position(type="etf", ticker="Gold 1 oz", gold_org=True)).gold_org is True


@pytest.mark.parametrize("model, base", [(ExternalPositionCreate, _position()), (ExternalPositionUpdate, {})])
def test_yfinance_ticker_must_be_single_symbol(model, base):
    with pytest.raises(ValidationError):
        model(**base, yfinance_ticker="AAPL,MSFT")
    with pytest.raises(ValidationError):
        model(**base, yfinance_ticker="A" * 31)
    assert model(**base, yfinance_ticker="NESN.SW").yfinance_ticker == "NESN.SW"
    # Leerer String heisst «nicht gesetzt», wie in api/positions.py.
    assert model(**base, yfinance_ticker="").yfinance_ticker == ""


# --- K019: coingecko_id ---


def test_coingecko_id_is_only_allowed_for_crypto_positions():
    """ticker=AAPL plus coingecko_id=bitcoin überschrieb den AAPL-Kurs aller Nutzer."""
    with pytest.raises(ValidationError) as exc:
        ExternalPositionCreate(**_position(type="stock", coingecko_id="bitcoin"))
    assert "nur beim Typ Krypto" in str(exc.value)
    pos = ExternalPositionCreate(**_position(type="crypto", ticker="BTC-USD", coingecko_id="bitcoin"))
    assert pos.coingecko_id == "bitcoin"


@pytest.mark.parametrize("bad", ["Bitcoin", "bit coin", "bitcoin,ethereum", "a" * 61, "bitcoin?x=1", "../global"])
def test_coingecko_id_must_match_the_pattern(bad):
    with pytest.raises(ValidationError):
        ExternalPositionCreate(**_position(type="crypto", ticker="BTC-USD", coingecko_id=bad))
    with pytest.raises(ValidationError):
        ExternalPositionUpdate(coingecko_id=bad)


def test_position_update_coingecko_id_with_explicit_non_crypto_type_is_rejected():
    with pytest.raises(ValidationError):
        ExternalPositionUpdate(type="stock", coingecko_id="bitcoin")
    # Ohne Typ im Body entscheidet der gespeicherte Typ: das prüft die Kernlogik.
    assert ExternalPositionUpdate(coingecko_id="bitcoin").coingecko_id == "bitcoin"
    assert ExternalPositionUpdate(type="crypto", coingecko_id="bitcoin").coingecko_id == "bitcoin"
    assert ExternalPositionUpdate(coingecko_id="").coingecko_id == ""
    assert ExternalPositionUpdate(coingecko_id=None).coingecko_id is None


def test_coingecko_pattern_matches_the_one_the_price_refresh_uses():
    from services.cache_service import COINGECKO_ID_PATTERN

    assert schemas.COINGECKO_ID_PATTERN == COINGECKO_ID_PATTERN


def test_coingecko_id_length_follows_the_price_cache_key():
    """R-pricecache-5: «CG:<id>» muss in price_cache.ticker passen, sonst schreibt der Worker keine Zeile."""
    from services.cache_service import COINGECKO_ID_MAX_LEN

    longest = "a" * COINGECKO_ID_MAX_LEN
    pos = ExternalPositionCreate(**_position(type="crypto", ticker="BTC-USD", coingecko_id=longest))
    assert pos.coingecko_id == longest
    with pytest.raises(ValidationError) as exc:
        ExternalPositionCreate(**_position(type="crypto", ticker="BTC-USD", coingecko_id=longest + "a"))
    assert f"höchstens {COINGECKO_ID_MAX_LEN} Zeichen" in str(exc.value)
    with pytest.raises(ValidationError):
        ExternalPositionUpdate(coingecko_id=longest + "a")


def test_market_ticker_types_match_the_internal_list():
    from api.positions import _MARKET_TICKER_TYPES

    assert tuple(schemas.MARKET_TICKER_TYPES) == tuple(_MARKET_TICKER_TYPES)


# --- K110: Zeitzone in expires_at ---


@pytest.mark.parametrize("model, base", [
    (ExternalAlertCreate, {"ticker": "AAPL", "alert_type": "price_above", "target_value": 1.0}),
    (ExternalAlertUpdate, {}),
])
def test_expires_at_with_timezone_becomes_naive_utc(model, base):
    """Die Spalte ist «timestamp without time zone»; asyncpg lehnt einen Wert mit tzinfo ab."""
    z = model(**base, expires_at="2026-12-31T00:00:00Z").expires_at
    assert z == datetime(2026, 12, 31, 0, 0) and z.tzinfo is None
    offset = model(**base, expires_at="2026-12-31T01:30:00+02:00").expires_at
    assert offset == datetime(2026, 12, 30, 23, 30) and offset.tzinfo is None
    aware = model(**base, expires_at=datetime(2026, 7, 1, 12, tzinfo=timezone(timedelta(hours=-5)))).expires_at
    assert aware == datetime(2026, 7, 1, 17) and aware.tzinfo is None
    naive = model(**base, expires_at="2026-12-31T08:00:00").expires_at
    assert naive == datetime(2026, 12, 31, 8, 0) and naive.tzinfo is None


# --- K111: Enum-Werte und null bei Positionen ---


def _literal_values(annotation) -> set[str]:
    if typing.get_origin(annotation) is typing.Union:
        for arm in typing.get_args(annotation):
            if typing.get_origin(arm) is typing.Literal:
                return set(typing.get_args(arm))
        raise AssertionError(f"kein Literal-Arm in {annotation!r}")
    assert typing.get_origin(annotation) is typing.Literal, f"kein Literal: {annotation!r}"
    return set(typing.get_args(annotation))


@pytest.mark.parametrize("field, enum", [
    ("style", Style), ("pricing_mode", PricingMode), ("price_source", PriceSource),
])
@pytest.mark.parametrize("model", [ExternalPositionCreate, ExternalPositionUpdate])
def test_position_literals_cover_exactly_the_internal_enums(model, field, enum):
    """Zwei handgepflegte Listen derselben Wahrheit: ein neuer Enum-Wert fällt hier auf."""
    assert _literal_values(model.model_fields[field].annotation) == {e.value for e in enum}


@pytest.mark.parametrize("payload", [
    {"style": "foo"},
    {"pricing_mode": None},
    {"price_source": None},
    {"pricing_mode": "sometimes"},
    {"price_source": "bloomberg"},
])
def test_position_create_rejects_invalid_enum_values_and_null(payload):
    """Vorher kam der Wert durch und das interne Schema warf im Handler: 500 statt 422."""
    with pytest.raises(ValidationError):
        ExternalPositionCreate(**_position(**payload))


def test_position_create_defaults_match_the_internal_schema():
    from api.positions import PositionCreate

    ext = ExternalPositionCreate(**_position())
    internal = PositionCreate(**ext.model_dump())
    assert internal.pricing_mode is PricingMode.auto
    assert internal.price_source is PriceSource.yahoo
    assert internal.style is None


@pytest.mark.parametrize("field", schemas._POSITION_NOT_NULL_FIELDS)
def test_position_update_rejects_explicit_null_for_not_null_columns(field):
    with pytest.raises(ValidationError) as exc:
        ExternalPositionUpdate(**{field: None})
    assert f"{field} darf nicht null sein" in str(exc.value)


def test_position_update_not_null_fields_are_not_null_in_the_model():
    for field in schemas._POSITION_NOT_NULL_FIELDS:
        column = Position.__table__.c[field]
        # gold_org und is_active sind in der DB nullbar, ein null ist dort trotzdem kein Zustand.
        assert column.nullable is False or field in ("gold_org", "is_active"), field


def test_position_update_still_allows_clearing_nullable_fields():
    upd = ExternalPositionUpdate(style=None, sector=None, industry=None, notes=None, isin=None)
    assert upd.model_dump(exclude_unset=True) == {
        "style": None, "sector": None, "industry": None, "notes": None, "isin": None,
    }
    with pytest.raises(ValidationError):
        ExternalPositionUpdate(style="foo")


# --- K149: Schema-Grenzen gegen Spaltenlängen ---


def _max_length(model, field: str) -> int | None:
    lengths = [
        m.max_length for m in model.model_fields[field].metadata
        if getattr(m, "max_length", None) is not None
    ]
    return min(lengths) if lengths else None


_LENGTH_CASES = [
    (ExternalAlertCreate, "ticker", PriceAlert.ticker),
    (ExternalAlertCreate, "note", PriceAlert.note),
    (ExternalAlertCreate, "currency", PriceAlert.currency),
    (ExternalAlertUpdate, "note", PriceAlert.note),
    (ExternalWatchlistAdd, "ticker", WatchlistItem.ticker),
    (ExternalWatchlistAdd, "name", WatchlistItem.name),
    (ExternalWatchlistAdd, "sector", WatchlistItem.sector),
    (ExternalPendingOrderCreate, "ticker", PendingOrder.ticker),
    (ExternalPendingOrderCreate, "currency", PendingOrder.currency),
    (ExternalPendingOrderCreate, "broker", PendingOrder.broker),
    (ExternalPendingOrderUpdate, "currency", PendingOrder.currency),
    (ExternalPendingOrderUpdate, "broker", PendingOrder.broker),
    (ExternalPendingOrderFill, "currency", Transaction.currency),
    (ExternalTransactionCreate, "ticker", Position.ticker),
    (ExternalTransactionCreate, "currency", Transaction.currency),
    (ExternalTransactionCreate, "stop_loss_method", Position.stop_loss_method),
    (ExternalTransactionUpdate, "currency", Transaction.currency),
    (ExternalDividendConfirm, "currency", Transaction.currency),
    (ExternalPositionCreate, "ticker", Position.ticker),
    (ExternalPositionCreate, "name", Position.name),
    (ExternalPositionCreate, "sector", Position.sector),
    (ExternalPositionCreate, "industry", Position.industry),
    (ExternalPositionCreate, "currency", Position.currency),
    (ExternalPositionCreate, "yfinance_ticker", Position.yfinance_ticker),
    (ExternalPositionCreate, "coingecko_id", Position.coingecko_id),
    (ExternalPositionCreate, "isin", Position.isin),
    (ExternalPositionUpdate, "ticker", Position.ticker),
    (ExternalPositionUpdate, "name", Position.name),
    (ExternalPositionUpdate, "sector", Position.sector),
    (ExternalPositionUpdate, "industry", Position.industry),
    (ExternalPositionUpdate, "currency", Position.currency),
    (ExternalPositionUpdate, "yfinance_ticker", Position.yfinance_ticker),
    (ExternalPositionUpdate, "coingecko_id", Position.coingecko_id),
    (ExternalPositionUpdate, "isin", Position.isin),
    (ExternalStopLossUpdate, "method", Position.stop_loss_method),
    (ExternalStopLossBatchItem, "method", Position.stop_loss_method),
    (ExternalPropertyCreate, "canton", Property.canton),
    (ExternalPropertyUpdate, "canton", Property.canton),
    (ExternalMortgageCreate, "name", Mortgage.name),
    (ExternalPropertyExpenseCreate, "description", PropertyExpense.description),
    (ExternalPropertyIncomeCreate, "description", PropertyIncome.description),
    (schemas.ExternalPropertyExpenseUpdate, "description", PropertyExpense.description),
    (schemas.ExternalPropertyIncomeUpdate, "description", PropertyIncome.description),
    (ExternalPEHoldingCreate, "currency", PrivateEquityHolding.currency),
    (ExternalPEHoldingUpdate, "currency", PrivateEquityHolding.currency),
    (ExternalPEValuationCreate, "source", PrivateEquityValuation.source),
    (ExternalMetalCreate, "manufacturer", PreciousMetalItem.manufacturer),
    (ExternalMetalCreate, "fineness", PreciousMetalItem.fineness),
    (ExternalMetalUpdate, "manufacturer", PreciousMetalItem.manufacturer),
    (ExternalMetalUpdate, "fineness", PreciousMetalItem.fineness),
    (ExternalMetalExpenseCreate, "description", PreciousMetalExpense.description),
    (ExternalTagCreate, "name", WatchlistTag.name),
    (ExternalTagCreate, "color", WatchlistTag.color),
]


@pytest.mark.parametrize(
    "model, field, column", _LENGTH_CASES,
    ids=[f"{m.__name__}.{f}" for m, f, _ in _LENGTH_CASES],
)
def test_schema_max_length_fits_the_db_column(model, field, column):
    """SQLite prüft keine VARCHAR-Länge: auf Postgres endete ein zu langer Wert als 500."""
    column_length = column.property.columns[0].type.length
    schema_length = _max_length(model, field)
    assert schema_length is not None, f"{model.__name__}.{field} hat keine Obergrenze"
    assert schema_length <= column_length, (
        f"{model.__name__}.{field}: Schema erlaubt {schema_length}, Spalte fasst {column_length}"
    )
