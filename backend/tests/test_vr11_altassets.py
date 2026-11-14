"""Regressionstests zum Vollreview vom 13.11.2026, Fixer «altassets».

Befunde: K006 (Kauf- und Buchungsdatum), K051 (Wechsel der Metallart),
K052 (Datum im Update-Schema), K123 (negative Hypothek-Restschuld),
K149 (Feldlängen), X38 (null auf Pflichtfeldern).
"""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from api import precious_metals as pm_api
from api import private_equity as pe_api
from api import real_estate as re_api
from models.position import Position
from models.precious_metal_expense import PreciousMetalExpense
from models.precious_metal_item import PreciousMetalItem
from models.private_equity import PrivateEquityDividend, PrivateEquityHolding, PrivateEquityValuation
from models.property import Mortgage, MortgageType, Property, PropertyExpense, PropertyIncome
from models.user import User
from services.property_service import _mortgage_to_dict

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"
TODAY = date.today()
# Zwei Tage voraus: «morgen» ist erlaubt, und UTC und Ortszeit liegen höchstens einen Tag auseinander.
FUTURE = (TODAY + timedelta(days=2)).isoformat()

GOLD = {
    "metal_type": "gold",
    "form": "bar",
    "weight_grams": 31.1035,
    "purchase_date": "2025-01-15",
    "purchase_price_chf": 5800.0,
}
METAL_EXPENSE = {"date": "2025-03-01", "category": "storage", "amount": 120.0}
PROPERTY = {"name": "Testhaus", "property_type": "efh", "purchase_price": 850000.0}
MORTGAGE = {"name": "1. Hypothek", "type": "fixed", "amount": 600000.0, "interest_rate": 1.5}
PROPERTY_EXPENSE = {"date": "2025-03-01", "category": "maintenance", "amount": 1500.0}
PROPERTY_INCOME = {"date": "2025-03-01", "amount": 2000.0}
HOLDING = {"company_name": "Test AG", "num_shares": 100, "nominal_value": 1000.0}
PE_DIVIDEND = {"payment_date": "2025-06-15", "dividend_per_share": 2.5, "fiscal_year": 2024}


@pytest.fixture(autouse=True)
def no_side_effects():
    """Kein Snapshot-Regen, kein Cache, kein SARON-Abruf über die echte Session."""
    saron = AsyncMock(return_value={"saron_rate": None})
    with (
        patch("api.precious_metals.trigger_snapshot_regen"),
        patch("api.precious_metals.invalidate_portfolio_cache"),
        patch("api.private_equity.invalidate_portfolio_cache"),
        patch("services.property_service.get_real_estate_market_data", saron),
    ):
        yield


async def _login(client: AsyncClient, email: str = "altassets@example.com") -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _post(client, headers, url: str, body: dict) -> dict:
    res = await client.post(url, json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _metal_positions(db, email: str = "altassets@example.com") -> dict[str, Position]:
    user_id = (await db.execute(select(User.id).where(User.email == email))).scalar_one()
    rows = await db.execute(
        select(Position).where(Position.user_id == user_id).execution_options(populate_existing=True)
    )
    return {p.ticker: p for p in rows.scalars().all()}


# ---------------------------------------------------------------------------
# K051 — Wechsel der Metallart
# ---------------------------------------------------------------------------


class TestMetalTypeChange:
    async def test_old_position_is_emptied(self, client, db):
        headers = await _login(client)
        item = await _post(client, headers, "/api/precious-metals", GOLD)
        before = await _metal_positions(db)
        assert float(before["XAUCHF=X"].shares) == pytest.approx(1.0)

        res = await client.put(
            f"/api/precious-metals/{item['id']}", json={"metal_type": "silver"}, headers=headers,
        )
        assert res.status_code == 200, res.text

        after = await _metal_positions(db)
        assert float(after["XAUCHF=X"].shares) == 0
        assert float(after["XAUCHF=X"].cost_basis_chf) == 0
        assert after["XAUCHF=X"].is_active is False
        assert float(after["XAGCHF=X"].shares) == pytest.approx(1.0)
        assert float(after["XAGCHF=X"].cost_basis_chf) == pytest.approx(5800.0)

    async def test_old_position_keeps_remaining_items(self, client, db):
        headers = await _login(client)
        first = await _post(client, headers, "/api/precious-metals", GOLD)
        await _post(client, headers, "/api/precious-metals", GOLD)

        res = await client.put(
            f"/api/precious-metals/{first['id']}", json={"metal_type": "platinum"}, headers=headers,
        )
        assert res.status_code == 200, res.text

        after = await _metal_positions(db)
        assert float(after["XAUCHF=X"].shares) == pytest.approx(1.0)
        assert after["XAUCHF=X"].is_active is True
        assert float(after["XPTCHF=X"].shares) == pytest.approx(1.0)

    @pytest.mark.parametrize("body", [{"metal_type": "bronze"}, {"form": "ring"}])
    async def test_update_rejects_unknown_enum_value(self, client, db, body):
        headers = await _login(client)
        item = await _post(client, headers, "/api/precious-metals", GOLD)

        res = await client.put(f"/api/precious-metals/{item['id']}", json=body, headers=headers)

        assert res.status_code == 422
        stored = await db.get(PreciousMetalItem, uuid.UUID(item["id"]))
        assert (stored.metal_type, stored.form) == ("gold", "bar")


# ---------------------------------------------------------------------------
# K052 — Datum in den Update-Schemas
# ---------------------------------------------------------------------------


class TestUpdateDate:
    @pytest.mark.parametrize("schema", [pm_api.ExpenseUpdate, re_api.ExpenseUpdate, re_api.IncomeUpdate])
    async def test_schema_accepts_date(self, schema):
        assert schema(date="2025-04-02").date == date(2025, 4, 2)

    async def test_metal_expense_date_can_be_changed(self, client, db):
        headers = await _login(client)
        exp = await _post(client, headers, "/api/precious-metals/expenses", METAL_EXPENSE)

        res = await client.put(
            f"/api/precious-metals/expenses/{exp['id']}",
            json={**METAL_EXPENSE, "date": "2025-04-02"},
            headers=headers,
        )

        assert res.status_code == 200, res.text
        assert res.json()["date"] == "2025-04-02"

    async def test_property_expense_and_income_date_can_be_changed(self, client, db):
        headers = await _login(client)
        prop = await _post(client, headers, "/api/properties", PROPERTY)
        exp = await _post(client, headers, f"/api/properties/{prop['id']}/expenses", PROPERTY_EXPENSE)
        inc = await _post(client, headers, f"/api/properties/{prop['id']}/income", PROPERTY_INCOME)

        res_exp = await client.put(
            f"/api/properties/expenses/{exp['id']}", json={"date": "2025-04-02"}, headers=headers,
        )
        res_inc = await client.put(
            f"/api/properties/income/{inc['id']}", json={"date": "2025-04-03"}, headers=headers,
        )

        assert res_exp.status_code == 200, res_exp.text
        assert res_inc.status_code == 200, res_inc.text
        assert (await db.get(PropertyExpense, uuid.UUID(exp["id"]))).date == date(2025, 4, 2)
        assert (await db.get(PropertyIncome, uuid.UUID(inc["id"]))).date == date(2025, 4, 3)


# ---------------------------------------------------------------------------
# K006 — Grenzen für Kauf- und Buchungsdatum
# ---------------------------------------------------------------------------


class TestPurchaseDate:
    async def test_validator_bounds(self):
        tomorrow = TODAY + timedelta(days=1)
        assert re_api.check_purchase_date(date(1900, 1, 1)) == date(1900, 1, 1)
        assert re_api.check_purchase_date(tomorrow) == tomorrow
        for bad in (date(1899, 12, 31), date(2, 1, 1), TODAY + timedelta(days=3)):
            with pytest.raises(ValueError):
                re_api.check_purchase_date(bad)

    @pytest.mark.parametrize("bad", ["0002-01-01", "1899-12-31", FUTURE])
    async def test_create_rejects_out_of_range(self, client, bad):
        headers = await _login(client)

        metal = await client.post("/api/precious-metals", json={**GOLD, "purchase_date": bad}, headers=headers)
        prop = await client.post("/api/properties", json={**PROPERTY, "purchase_date": bad}, headers=headers)
        holding = await client.post("/api/private-equity", json={**HOLDING, "purchase_date": bad}, headers=headers)

        assert (metal.status_code, prop.status_code, holding.status_code) == (422, 422, 422)

    async def test_create_accepts_purchase_before_1970(self, client):
        headers = await _login(client)
        old = "1950-06-01"

        await _post(client, headers, "/api/precious-metals", {**GOLD, "purchase_date": old})
        await _post(client, headers, "/api/properties", {**PROPERTY, "purchase_date": old})
        await _post(client, headers, "/api/private-equity", {**HOLDING, "purchase_date": old})

    @pytest.mark.parametrize("field", ["purchase_date", "sold_date"])
    async def test_metal_update_rejects_out_of_range(self, client, db, field):
        headers = await _login(client)
        item = await _post(client, headers, "/api/precious-metals", GOLD)

        res = await client.put(
            f"/api/precious-metals/{item['id']}", json={field: "0002-01-01"}, headers=headers,
        )

        assert res.status_code == 422
        stored = await db.get(PreciousMetalItem, uuid.UUID(item["id"]))
        assert stored.purchase_date == date(2025, 1, 15)
        assert stored.sold_date is None

    async def test_property_and_holding_update_reject_out_of_range(self, client):
        headers = await _login(client)
        prop = await _post(client, headers, "/api/properties", PROPERTY)
        holding = await _post(client, headers, "/api/private-equity", HOLDING)

        res_prop = await client.put(
            f"/api/properties/{prop['id']}", json={"purchase_date": "0002-01-01"}, headers=headers,
        )
        res_pe = await client.put(
            f"/api/private-equity/{holding['id']}", json={"purchase_date": FUTURE}, headers=headers,
        )

        assert (res_prop.status_code, res_pe.status_code) == (422, 422)


class TestBookingDate:
    @pytest.mark.parametrize("bad", ["0002-01-01", "1969-12-31", FUTURE])
    async def test_create_rejects_out_of_range(self, client, bad):
        headers = await _login(client)
        prop = await _post(client, headers, "/api/properties", PROPERTY)
        holding = await _post(client, headers, "/api/private-equity", HOLDING)

        results = [
            await client.post("/api/precious-metals/expenses", json={**METAL_EXPENSE, "date": bad}, headers=headers),
            await client.post(
                f"/api/properties/{prop['id']}/expenses", json={**PROPERTY_EXPENSE, "date": bad}, headers=headers,
            ),
            await client.post(
                f"/api/properties/{prop['id']}/income", json={**PROPERTY_INCOME, "date": bad}, headers=headers,
            ),
            await client.post(
                f"/api/private-equity/{holding['id']}/dividends",
                json={**PE_DIVIDEND, "payment_date": bad},
                headers=headers,
            ),
        ]

        assert [r.status_code for r in results] == [422, 422, 422, 422]

    async def test_update_rejects_out_of_range(self, client, db):
        headers = await _login(client)
        prop = await _post(client, headers, "/api/properties", PROPERTY)
        holding = await _post(client, headers, "/api/private-equity", HOLDING)
        metal_exp = await _post(client, headers, "/api/precious-metals/expenses", METAL_EXPENSE)
        prop_exp = await _post(client, headers, f"/api/properties/{prop['id']}/expenses", PROPERTY_EXPENSE)
        prop_inc = await _post(client, headers, f"/api/properties/{prop['id']}/income", PROPERTY_INCOME)
        await _post(client, headers, f"/api/private-equity/{holding['id']}/dividends", PE_DIVIDEND)
        dividend_id = str((await db.execute(select(PrivateEquityDividend.id))).scalar_one())

        results = [
            await client.put(
                f"/api/precious-metals/expenses/{metal_exp['id']}", json={"date": "1969-12-31"}, headers=headers,
            ),
            await client.put(
                f"/api/properties/expenses/{prop_exp['id']}", json={"date": "1969-12-31"}, headers=headers,
            ),
            await client.put(f"/api/properties/income/{prop_inc['id']}", json={"date": FUTURE}, headers=headers),
            await client.put(
                f"/api/private-equity/{holding['id']}/dividends/{dividend_id}",
                json={"payment_date": FUTURE},
                headers=headers,
            ),
        ]

        assert [r.status_code for r in results] == [422, 422, 422, 422]
        assert (await db.get(PrivateEquityDividend, uuid.UUID(dividend_id))).payment_date == date(2025, 6, 15)


# ---------------------------------------------------------------------------
# X38 — ausdrückliches null auf Pflichtfeldern
# ---------------------------------------------------------------------------


class TestExplicitNull:
    @pytest.mark.parametrize(
        "field", ["metal_type", "form", "weight_grams", "purchase_date", "purchase_price_chf", "is_sold"],
    )
    async def test_metal_item_update(self, client, db, field):
        headers = await _login(client)
        item = await _post(client, headers, "/api/precious-metals", GOLD)

        res = await client.put(f"/api/precious-metals/{item['id']}", json={field: None}, headers=headers)

        assert res.status_code == 422, res.text
        assert field in res.json()["detail"]
        stored = await db.get(PreciousMetalItem, uuid.UUID(item["id"]))
        assert getattr(stored, field) is not None

    async def test_metal_item_update_keeps_null_on_optional_fields(self, client):
        headers = await _login(client)
        item = await _post(client, headers, "/api/precious-metals", {**GOLD, "manufacturer": "Valcambi"})

        res = await client.put(
            f"/api/precious-metals/{item['id']}",
            json={"manufacturer": None, "sold_date": None, "notes": None},
            headers=headers,
        )

        assert res.status_code == 200, res.text
        assert res.json()["manufacturer"] is None

    @pytest.mark.parametrize("field", ["date", "category", "amount", "recurring"])
    async def test_metal_expense_update(self, client, db, field):
        headers = await _login(client)
        exp = await _post(client, headers, "/api/precious-metals/expenses", METAL_EXPENSE)

        res = await client.put(f"/api/precious-metals/expenses/{exp['id']}", json={field: None}, headers=headers)

        assert res.status_code == 422, res.text
        stored = await db.get(PreciousMetalExpense, uuid.UUID(exp["id"]))
        assert getattr(stored, field) is not None

    async def test_metal_expense_update_keeps_null_on_optional_fields(self, client):
        headers = await _login(client)
        exp = await _post(client, headers, "/api/precious-metals/expenses", {**METAL_EXPENSE, "metal_type": "gold"})

        res = await client.put(
            f"/api/precious-metals/expenses/{exp['id']}",
            json={"metal_type": None, "frequency": None, "description": None},
            headers=headers,
        )

        assert res.status_code == 200, res.text
        assert res.json()["metal_type"] is None

    async def test_real_estate_updates(self, client, db):
        headers = await _login(client)
        prop = await _post(client, headers, "/api/properties", PROPERTY)
        mortgage = await _post(client, headers, f"/api/properties/{prop['id']}/mortgages", MORTGAGE)
        exp = await _post(client, headers, f"/api/properties/{prop['id']}/expenses", PROPERTY_EXPENSE)
        inc = await _post(client, headers, f"/api/properties/{prop['id']}/income", PROPERTY_INCOME)

        cases = [
            (f"/api/properties/{prop['id']}", ("name", "property_type", "purchase_price")),
            (f"/api/properties/mortgages/{mortgage['id']}", ("name", "type", "amount", "interest_rate")),
            (f"/api/properties/expenses/{exp['id']}", ("date", "category", "amount")),
            (f"/api/properties/income/{inc['id']}", ("date", "amount")),
        ]
        for url, fields in cases:
            for field in fields:
                res = await client.put(url, json={field: None}, headers=headers)
                assert res.status_code == 422, f"{url} {field}: {res.status_code} {res.text}"

        # Nullbare Spalten lassen sich weiter leeren.
        res = await client.put(
            f"/api/properties/{prop['id']}", json={"purchase_date": None, "estimated_value": None}, headers=headers,
        )
        assert res.status_code == 200, res.text
        assert float((await db.get(Mortgage, uuid.UUID(mortgage["id"]))).amount) == 600000.0


# ---------------------------------------------------------------------------
# K123 — Restschuld der Hypothek
# ---------------------------------------------------------------------------


def _mortgage(**overrides) -> Mortgage:
    base = {
        "id": uuid.uuid4(),
        "property_id": uuid.uuid4(),
        "name": "Hypothek",
        "type": MortgageType.fixed,
        "amount": 100000,
        "interest_rate": 1.5,
        "is_active": True,
    }
    base.update(overrides)
    return Mortgage(**base)


class TestMortgageBalance:
    async def test_balance_never_negative(self):
        d = _mortgage(amortization_monthly=1000, start_date=date(2015, 1, 1))

        result = _mortgage_to_dict(d)

        assert result["current_amount"] == 0
        assert result["total_amortized"] == 100000

    async def test_running_amortization_is_unchanged(self):
        start = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)  # Erster des Vormonats

        result = _mortgage_to_dict(_mortgage(amortization_monthly=1000, start_date=start))

        assert result["total_amortized"] == 1000
        assert result["current_amount"] == 99000

    async def test_summary_does_not_count_overpaid_mortgage_as_asset(self, client):
        headers = await _login(client)
        prop = await _post(client, headers, "/api/properties", PROPERTY)
        await _post(
            client, headers, f"/api/properties/{prop['id']}/mortgages",
            {**MORTGAGE, "amount": 100000.0, "amortization_monthly": 1000.0, "start_date": "2015-01-01"},
        )

        summary = (await client.get("/api/properties", headers=headers)).json()

        assert summary["total_mortgage_chf"] == 0
        assert summary["total_equity_chf"] == 850000.0
        assert summary["properties"][0]["current_mortgage"] == 0


# ---------------------------------------------------------------------------
# K149 — Schema-Grenzen gegen Spaltenlängen
# ---------------------------------------------------------------------------

SCHEMA_TABLES: list[tuple[type[BaseModel], type]] = [
    (pm_api.PreciousMetalCreate, PreciousMetalItem),
    (pm_api.PreciousMetalUpdate, PreciousMetalItem),
    (pm_api.ExpenseCreate, PreciousMetalExpense),
    (pm_api.ExpenseUpdate, PreciousMetalExpense),
    (re_api.PropertyCreate, Property),
    (re_api.PropertyUpdate, Property),
    (re_api.MortgageCreate, Mortgage),
    (re_api.MortgageUpdate, Mortgage),
    (re_api.ExpenseCreate, PropertyExpense),
    (re_api.ExpenseUpdate, PropertyExpense),
    (re_api.IncomeCreate, PropertyIncome),
    (re_api.IncomeUpdate, PropertyIncome),
    (pe_api.HoldingCreate, PrivateEquityHolding),
    (pe_api.HoldingUpdate, PrivateEquityHolding),
    (pe_api.ValuationCreate, PrivateEquityValuation),
    (pe_api.ValuationUpdate, PrivateEquityValuation),
]


def _max_length(schema: type[BaseModel], field: str) -> int | None:
    return next((m.max_length for m in schema.model_fields[field].metadata if hasattr(m, "max_length")), None)


class TestColumnLengths:
    @pytest.mark.parametrize("schema,model", SCHEMA_TABLES, ids=lambda v: f"{v.__module__}.{v.__name__}")
    async def test_schema_limit_fits_column(self, schema, model):
        checked = 0
        for name in schema.model_fields:
            column = model.__table__.c.get(name)
            # Enum-Spalten prüft der Enum selbst, Text-Spalten haben keine Länge.
            if column is None or isinstance(column.type, sa.Enum) or not isinstance(column.type, sa.String):
                continue
            if column.type.length is None:
                continue
            limit = _max_length(schema, name)
            assert limit is not None, f"{schema.__name__}.{name}: max_length fehlt"
            assert limit <= column.type.length, f"{schema.__name__}.{name}: {limit} > {column.type.length}"
            checked += 1
        assert checked > 0

    async def test_manufacturer_longer_than_column_is_rejected(self, client):
        headers = await _login(client)

        too_long = await client.post("/api/precious-metals", json={**GOLD, "manufacturer": "x" * 101}, headers=headers)
        fits = await client.post("/api/precious-metals", json={**GOLD, "manufacturer": "x" * 100}, headers=headers)

        assert too_long.status_code == 422
        assert fits.status_code == 201

    async def test_schema_rejects_long_manufacturer_on_update(self):
        with pytest.raises(ValidationError):
            pm_api.PreciousMetalUpdate(manufacturer="x" * 101)
