"""Vollreview 11/2026, Welle 3, externe API: Datumsgrenzen der Schreib-Schemas.

K006: Kaufdaten hatten extern keine Obergrenze, und die Ausgaben und Einnahmen
von Immobilien nahmen jedes Datum an, weil ihre Routen das interne Schema
umgehen.
"""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from api import external_v1_schemas as schemas
from api import real_estate
from api.external_v1_schemas import (
    ExternalMetalCreate,
    ExternalMetalUpdate,
    ExternalPEHoldingCreate,
    ExternalPEHoldingUpdate,
    ExternalPropertyCreate,
    ExternalPropertyExpenseCreate,
    ExternalPropertyExpenseUpdate,
    ExternalPropertyIncomeCreate,
    ExternalPropertyIncomeUpdate,
    ExternalPropertyUpdate,
)
from api.validation import BOOKING_DATE_ERROR
from dateutils import utcnow
from tests.test_external_ui_parity import api_auth, rw_tokens

BASE = "/api/v1/external"
UTC_TODAY = utcnow().date()

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

_EXPENSE = {"category": "repair", "amount": 100.0}
_INCOME = {"amount": 100.0}
_PROPERTY_BOOKING_CASES = [
    (ExternalPropertyExpenseCreate, _EXPENSE),
    (ExternalPropertyExpenseUpdate, {}),
    (ExternalPropertyIncomeCreate, _INCOME),
    (ExternalPropertyIncomeUpdate, {}),
]


@pytest.mark.parametrize("model, field, base", _PURCHASE_CASES, ids=lambda v: getattr(v, "__name__", None))
def test_purchase_date_has_upper_bound_tomorrow(model, field, base):
    """Ein Kaufdatum im Jahr 2999 liess die Tagesbewertung nie beginnen."""
    for bad in (UTC_TODAY + timedelta(days=2), date(2999, 1, 1)):
        with pytest.raises(ValidationError) as exc:
            model(**base, **{field: bad.isoformat()})
        assert schemas.PURCHASE_DATE_ERROR in str(exc.value)
    for good in (UTC_TODAY, UTC_TODAY + timedelta(days=1), date(1900, 1, 1)):
        assert getattr(model(**base, **{field: good.isoformat()}), field) == good


def test_purchase_date_rule_equals_the_internal_one():
    assert schemas.PURCHASE_DATE_ERROR == real_estate.PURCHASE_DATE_ERROR
    assert schemas.PURCHASE_DATE_ERROR == "Datum muss zwischen 01.01.1900 und morgen liegen"
    assert schemas.MIN_PURCHASE_DATE == real_estate.MIN_PURCHASE_DATE


@pytest.mark.parametrize("model, base", _PROPERTY_BOOKING_CASES, ids=lambda v: getattr(v, "__name__", None))
def test_property_expense_and_income_dates_are_booking_dates(model, base):
    for bad in ("0002-01-01", "1969-12-31", (UTC_TODAY + timedelta(days=2)).isoformat()):
        with pytest.raises(ValidationError) as exc:
            model(**base, date=bad)
        assert BOOKING_DATE_ERROR in str(exc.value)
    for good in (date(1970, 1, 1), UTC_TODAY, UTC_TODAY + timedelta(days=1)):
        assert model(**base, date=good.isoformat()).date == good


@pytest.mark.parametrize("model", [ExternalPropertyExpenseUpdate, ExternalPropertyIncomeUpdate])
def test_property_updates_still_work_without_a_date(model):
    assert model(amount=5.0).model_dump(exclude_unset=True) == {"amount": 5.0}


@pytest.mark.asyncio
async def test_routes_reject_dates_outside_the_bounds(client):
    """Die Routen rufen property_service direkt auf: die Grenze muss im externen Schema stehen."""
    w, _ = await rw_tokens(client, "w3-k006-routes@example.com")
    h = api_auth(w)
    house = {"name": "Haus", "property_type": "efh", "purchase_price": 500000}
    new_year = date(UTC_TODAY.year, 1, 1).isoformat()

    future = await client.post(f"{BASE}/immobilien", json={**house, "purchase_date": "2999-01-01"}, headers=h)
    assert future.status_code == 422, future.text

    created = await client.post(f"{BASE}/immobilien", json={**house, "purchase_date": "1950-06-01"}, headers=h)
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    for path, body in (("ausgaben", _EXPENSE), ("einnahmen", _INCOME)):
        for bad in ("0002-01-01", "2999-01-01"):
            res = await client.post(f"{BASE}/immobilien/{pid}/{path}", json={**body, "date": bad}, headers=h)
            assert res.status_code == 422, (path, bad, res.text)
        ok = await client.post(
            f"{BASE}/immobilien/{pid}/{path}", json={**body, "date": UTC_TODAY.isoformat()}, headers=h,
        )
        assert ok.status_code == 201, (path, ok.text)
        entry_id = ok.json()["id"]
        res = await client.put(f"{BASE}/immobilien/{path}/{entry_id}", json={"date": "0002-01-01"}, headers=h)
        assert res.status_code == 422, (path, res.text)
        moved = await client.put(f"{BASE}/immobilien/{path}/{entry_id}", json={"date": new_year}, headers=h)
        assert moved.status_code == 200, (path, moved.text)

    # Je eine Zeile, mit dem zuletzt angenommenen Datum: kein abgelehnter Aufruf hat
    # geschrieben. Die Detailansicht zeigt nur Buchungen des laufenden Jahres.
    detail = (await client.get(f"{BASE}/immobilien/{pid}", headers=h)).json()
    assert [e["date"] for e in detail["expenses"]] == [new_year]
    assert [i["date"] for i in detail["income"]] == [new_year]
