"""Tests fuer die UI-Paritaet der externen API (v0.45).

Deckt die neuen Schreib-Endpoints ab, die das interne UI 1:1 spiegeln:
Positionen, Immobilien, Private Equity, Edelmetalle, Buckets, Performance-
Aktionen, Settings/Onboarding sowie Scope-Enforcement quer ueber alle Domaenen.

Hinweis: die Test-DB baut via create_all (nicht Alembic), daher sind die
``api_write_log``-CHECK-Constraints hier unsichtbar (siehe Memory) — die
Whitelist-Vollstaendigkeit wird durch Migration 085 + manuelle Verifikation
gegen die echte DB abgesichert, nicht hier.
"""

import typing
from datetime import date

import pytest
from sqlalchemy import func, select

from api.external_v1_schemas import ExternalPositionCreate, ExternalPositionUpdate
from models.position import AssetType

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def jwt_auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def api_auth(api_key: str) -> dict:
    return {"X-API-Key": api_key}


async def make_token(client, jwt, name="t", write=False) -> str:
    res = await client.post(
        "/api/settings/api-tokens",
        json={"name": name, "write_access": write, "current_password": TEST_PASSWORD},
        headers=jwt_auth(jwt),
    )
    assert res.status_code == 201, res.text
    return res.json()["token"]


async def rw_tokens(client, email):
    """Liefert (write_token, read_token) fuer einen frischen User."""
    jwt = await register_and_login(client, email)
    w = await make_token(client, jwt, name="w", write=True)
    r = await make_token(client, jwt, name="r", write=False)
    return w, r


class TestPositions:
    async def test_create_update_delete_roundtrip_and_audit(self, client, db):
        w, _ = await rw_tokens(client, "par-pos-w@example.com")
        # cost_basis_chf=0 -> kein Snapshot-Regen, haelt den Test deterministisch.
        payload = {"ticker": "TESTPOS", "name": "Test Position", "type": "stock",
                   "currency": "CHF", "shares": 5, "cost_basis_chf": 0}
        res = await client.post("/api/v1/external/positions", json=payload, headers=api_auth(w))
        assert res.status_code == 201, res.text
        pos = res.json()
        assert pos["ticker"] == "TESTPOS"
        pid = pos["id"]

        upd = await client.put(f"/api/v1/external/positions/by-id/{pid}",
                               json={"name": "Renamed"}, headers=api_auth(w))
        assert upd.status_code == 200, upd.text
        assert upd.json()["name"] == "Renamed"

        from models.api_write_log import ApiWriteLog
        actions = {r.action for r in (await db.execute(select(ApiWriteLog))).scalars().all()}
        assert "position_create" in actions
        assert "position_update" in actions

        dele = await client.delete(f"/api/v1/external/positions/by-id/{pid}", headers=api_auth(w))
        assert dele.status_code == 204

    async def test_read_token_forbidden(self, client):
        _, r = await rw_tokens(client, "par-pos-r@example.com")
        res = await client.post("/api/v1/external/positions",
                                json={"ticker": "X", "name": "X", "type": "stock"},
                                headers=api_auth(r))
        assert res.status_code == 403


def _literal_values(annotation) -> set[str]:
    """Zieht die erlaubten Literal-Werte aus einer (ggf. Optional-)Annotation.

    ``Optional[Literal[...]]`` ist ``Union[Literal[...], None]`` — der Literal-Arm
    muss ausgepackt werden, sonst prueft man gegen die leere Menge und der Test
    waere immer gruen.
    """
    if typing.get_origin(annotation) is typing.Union:
        for arm in typing.get_args(annotation):
            if typing.get_origin(arm) is typing.Literal:
                return set(typing.get_args(arm))
        raise AssertionError(f"kein Literal-Arm in {annotation!r}")
    assert typing.get_origin(annotation) is typing.Literal, f"kein Literal: {annotation!r}"
    return set(typing.get_args(annotation))


class TestAssetTypeParity:
    """Jeder interne AssetType muss extern anlegbar sein.

    Der teure Fehler ist strukturell: das interne Enum (``models.position.AssetType``)
    und das externe ``Literal`` in den v1-Schemas sind zwei handgepflegte Listen
    derselben Wahrheit. Eine neue Assetklasse wird intern ergaenzt, extern vergessen
    — und die API lehnt sie ab (422), ohne dass ein Test rot wird, weil die
    bestehenden Faelle nur ``type="stock"`` abdecken. Genau so entsteht eine stille
    Paritaets-Luecke.

    Diese Tests sind generisch ueber ``AssetType`` parametrisiert: der NAECHSTE Typ
    faellt automatisch auf, ohne dass jemand daran denken muss.
    """

    # async trotz reiner Introspektion: das modulweite pytestmark setzt
    # asyncio auf jeden Test — eine sync-Funktion wuerde nur warnen.
    async def test_create_literal_covers_every_asset_type(self):
        assert _literal_values(ExternalPositionCreate.model_fields["type"].annotation) == {
            t.value for t in AssetType
        }

    async def test_update_literal_covers_every_asset_type(self):
        assert _literal_values(ExternalPositionUpdate.model_fields["type"].annotation) == {
            t.value for t in AssetType
        }

    @pytest.mark.parametrize("asset_type", list(AssetType), ids=lambda t: t.value)
    async def test_every_asset_type_is_creatable_externally(self, client, asset_type):
        """Der statische Literal-Vergleich beweist nur, dass der Wert durch die
        Validierung kommt — dieser Test beweist, dass er auch wirklich anlegbar ist
        (Bucket-Zuordnung, Guards, Persistenz).

        Cash/Vorsorge tragen bewusst Platzhalter-Ticker: ein handelbares Symbol auf
        type=cash/pension wird vom Guard (zu Recht) mit 422 abgelehnt.
        """
        w, _ = await rw_tokens(client, f"par-type-{asset_type.value}@example.com")
        placeholder = {"cash": "CASH_PARITY", "pension": "PENSION_PARITY"}
        ticker = placeholder.get(asset_type.value, f"PAR{asset_type.value.upper()}")
        # cost_basis_chf=0 -> kein Snapshot-Regen, haelt den Test deterministisch.
        payload = {"ticker": ticker, "name": f"Parity {asset_type.value}",
                   "type": asset_type.value, "currency": "CHF", "shares": 1,
                   "cost_basis_chf": 0}
        res = await client.post("/api/v1/external/positions", json=payload, headers=api_auth(w))
        assert res.status_code == 201, res.text
        assert res.json()["type"] == asset_type.value


class TestRealEstate:
    async def test_create_property_and_scope(self, client):
        w, r = await rw_tokens(client, "par-re@example.com")
        body = {"name": "Mehrfamilienhaus", "property_type": "mfh", "purchase_price": 1000000}
        forbidden = await client.post("/api/v1/external/immobilien", json=body, headers=api_auth(r))
        assert forbidden.status_code == 403
        res = await client.post("/api/v1/external/immobilien", json=body, headers=api_auth(w))
        assert res.status_code == 201, res.text
        assert res.json()["name"] == "Mehrfamilienhaus"


class TestPrivateEquity:
    async def test_create_holding_and_scope(self, client):
        w, r = await rw_tokens(client, "par-pe@example.com")
        body = {"company_name": "Acme AG", "num_shares": 100, "nominal_value": 100.0,
                "currency": "CHF"}
        forbidden = await client.post("/api/v1/external/private-equity", json=body, headers=api_auth(r))
        assert forbidden.status_code == 403
        res = await client.post("/api/v1/external/private-equity", json=body, headers=api_auth(w))
        assert res.status_code == 201, res.text
        assert res.json()["company_name"] == "Acme AG"


class TestPreciousMetals:
    async def test_create_item_and_scope(self, client):
        w, r = await rw_tokens(client, "par-pm@example.com")
        body = {"metal_type": "gold", "form": "bar", "weight_grams": 100.0,
                "purchase_date": date.today().isoformat(), "purchase_price_chf": 6000.0}
        forbidden = await client.post("/api/v1/external/precious-metals", json=body, headers=api_auth(r))
        assert forbidden.status_code == 403
        res = await client.post("/api/v1/external/precious-metals", json=body, headers=api_auth(w))
        assert res.status_code == 201, res.text
        assert res.json()["metal_type"] == "gold"


class TestBuckets:
    async def test_create_bucket_and_scope(self, client):
        w, r = await rw_tokens(client, "par-bucket@example.com")
        body = {"name": "Wachstum"}
        forbidden = await client.post("/api/v1/external/buckets", json=body, headers=api_auth(r))
        assert forbidden.status_code == 403
        res = await client.post("/api/v1/external/buckets", json=body, headers=api_auth(w))
        assert res.status_code == 201, res.text
        assert res.json()["name"] == "Wachstum"


class TestPerformanceActions:
    async def test_recalculate_scope_and_ok(self, client):
        w, r = await rw_tokens(client, "par-perf@example.com")
        forbidden = await client.post("/api/v1/external/performance/recalculate", headers=api_auth(r))
        assert forbidden.status_code == 403
        res = await client.post("/api/v1/external/performance/recalculate", headers=api_auth(w))
        assert res.status_code == 200, res.text
        assert "recalculated" in res.json()


class TestSettingsOnboarding:
    async def test_settings_patch_scope_and_ok(self, client):
        w, r = await rw_tokens(client, "par-settings@example.com")
        forbidden = await client.patch("/api/v1/external/settings",
                                       json={"base_currency": "CHF"}, headers=api_auth(r))
        assert forbidden.status_code == 403
        res = await client.patch("/api/v1/external/settings",
                                 json={"base_currency": "CHF"}, headers=api_auth(w))
        assert res.status_code == 200, res.text

    async def test_settings_never_exposes_secrets(self, client):
        w, _ = await rw_tokens(client, "par-settings-sec@example.com")
        res = await client.patch("/api/v1/external/settings",
                                 json={"base_currency": "CHF"}, headers=api_auth(w))
        assert res.status_code == 200
        for secret in ("fred_api_key", "fmp_api_key", "finnhub_api_key"):
            assert secret not in res.json()

    async def test_onboarding_step_complete(self, client):
        w, _ = await rw_tokens(client, "par-onb@example.com")
        res = await client.post("/api/v1/external/settings/onboarding/step-complete",
                                json={"step": "first_position"}, headers=api_auth(w))
        assert res.status_code == 200, res.text


class TestScopeSmoke:
    """Read-Token (kein write-Scope) muss bei JEDER neuen Mutation 403 geben."""

    async def test_write_endpoints_reject_read_token(self, client):
        _, r = await rw_tokens(client, "par-smoke@example.com")
        import uuid as _uuid
        fake = str(_uuid.uuid4())
        cases = [
            ("post", "/api/v1/external/dividends/" + fake + "/confirm",
             {"date": date.today().isoformat(), "total_chf": 10.0}),
            ("post", "/api/v1/external/screening/scan", None),
            ("put", "/api/v1/external/etf-sectors/SPY",
             {"sectors": [{"sector": "Technology", "weight_pct": 100.0}]}),
            ("patch", "/api/v1/external/eps-scanner/thresholds",
             {"super_quarter_yoy_pct": 30.0}),
            ("put", "/api/v1/external/analysis/resistance/AAPL",
             {"manual_resistance": 100.0}),
            ("post", "/api/v1/external/performance/regenerate-snapshots", None),
            ("post", "/api/v1/external/buckets/onboarding-dismiss", None),
            ("put", "/api/v1/external/settings/alert-preferences",
             {"category": "stop_loss", "is_enabled": True}),
        ]
        for method, url, body in cases:
            fn = getattr(client, method)
            res = await (fn(url, json=body, headers=api_auth(r)) if body is not None
                         else fn(url, headers=api_auth(r)))
            assert res.status_code == 403, f"{method.upper()} {url} -> {res.status_code} (erwartet 403)"


# ---------------------------------------------------------------------------
# Vollreview 11/2026, K033: Routen-Test über den ganzen Router.
#
# Jeder Handler ruft ``require_scope`` selbst auf und prüft das Eigentum an
# IDs von Hand. Die Tests oben decken eine handgepflegte Fallliste. Die Tests
# hier iterieren ``router.routes``: eine neue Route ohne Auth, ohne Scope-
# Prüfung oder ohne Eigentumsprüfung macht sie rot, ohne dass jemand daran
# denken muss.
# ---------------------------------------------------------------------------

import inspect
import re
import uuid as _uuid_mod
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.routing import APIRoute

EXT = "/api/v1/external"
_PATH_PARAM = re.compile(r"\{(\w+)\}")
# Steht in jedem Objekt des fremden Nutzers. Taucht es in einer Antwort an den
# Angreifer auf, hat eine Route fremde Daten ausgeliefert.
SECRET = "FREMDGEHEIM"


def _external_routes() -> list[APIRoute]:
    import api.external_v1 as ext
    return [r for r in ext.router.routes if isinstance(r, APIRoute)]


def _methods(route: APIRoute) -> list[str]:
    return sorted(route.methods - {"HEAD", "OPTIONS"})


def _fill_path(path: str, ids: dict | None = None) -> str:
    def _sub(match: re.Match) -> str:
        name = match.group(1)
        if ids and name in ids:
            return str(ids[name])
        if name.endswith("_id"):
            return str(_uuid_mod.uuid4())
        return "USD" if name == "from_currency" else "AAPL"
    return _PATH_PARAM.sub(_sub, path)


class _Untouchable:
    """Platzhalter für jeden Handler-Parameter ausser ``request``.

    Ein Handler, der vor der Scope-Prüfung auf db, user oder den Body zugreift,
    scheitert hier und nicht erst im Betrieb.
    """

    def __init__(self, name: str):
        object.__setattr__(self, "_name", name)

    def __getattr__(self, attr: str):
        raise AssertionError(f"Zugriff auf {self._name}.{attr} vor der Scope-Prüfung")


class TestEveryRoute:
    async def test_every_route_except_health_requires_an_api_key(self, client):
        failures = []
        checked = 0
        for route in _external_routes():
            if route.path == f"{EXT}/health":
                continue
            for method in _methods(route):
                res = await client.request(method, _fill_path(route.path))
                checked += 1
                if res.status_code != 401:
                    failures.append(f"{method} {route.path} -> {res.status_code}")
        assert not failures, "Routen ohne Auth: " + "; ".join(failures)
        assert checked >= 170  # kein leerer Durchlauf

    async def test_health_is_the_only_route_without_auth(self, client):
        res = await client.get(f"{EXT}/health")
        assert res.status_code == 200

    async def test_every_write_route_rejects_a_read_only_token_before_anything_else(self, monkeypatch):
        """Ruft jeden Nicht-GET-Handler direkt mit einem Read-Token auf.

        Über HTTP ginge das nicht einheitlich: bei Routen mit typisiertem Body
        prüft FastAPI den Body vor dem Handler und antwortete mit 422, bevor
        ``require_scope`` läuft. Der direkte Aufruf prüft genau die Zusage:
        die Scope-Prüfung ist die erste Handlung des Handlers.
        """
        from api.auth import limiter
        monkeypatch.setattr(limiter, "enabled", False)
        request = SimpleNamespace(state=SimpleNamespace(
            api_token=SimpleNamespace(id=_uuid_mod.uuid4(), name="r", scopes=["read"]),
        ))
        failures = []
        checked = 0
        for route in _external_routes():
            if not (route.methods - {"GET", "HEAD", "OPTIONS"}):
                continue
            checked += 1
            kwargs = {
                name: request if name == "request" else _Untouchable(name)
                for name in inspect.signature(route.endpoint).parameters
            }
            label = f"{'/'.join(_methods(route))} {route.path}"
            if "request" not in kwargs:
                failures.append(f"{label}: Handler ohne request-Parameter")
                continue
            try:
                await route.endpoint(**kwargs)
            except HTTPException as exc:
                if exc.status_code != 403:
                    failures.append(f"{label}: HTTP {exc.status_code} statt 403")
            except Exception as exc:  # noqa: BLE001 — jede andere Ausnahme ist der Befund
                failures.append(f"{label}: {type(exc).__name__}: {exc}")
            else:
                failures.append(f"{label}: kein 403")
        assert not failures, "Schreib-Routen ohne Scope-Prüfung an erster Stelle:\n" + "\n".join(failures)
        assert checked >= 80

    async def test_read_routes_do_not_require_the_write_scope(self, monkeypatch):
        """Gegenprobe: der direkte Aufruf oben darf nicht jede Route mit 403 beantworten."""
        from api.auth import limiter
        import api.external_v1 as ext
        monkeypatch.setattr(limiter, "enabled", False)
        request = SimpleNamespace(state=SimpleNamespace(
            api_token=SimpleNamespace(id=_uuid_mod.uuid4(), name="r", scopes=["read"]),
        ))
        assert await ext.external_health() == {"status": "ok", "api_version": "v1"}
        with pytest.raises(AssertionError, match="vor der Scope-Prüfung"):
            await ext.list_positions(request=request, db=_Untouchable("db"), user=_Untouchable("user"))


# Pfadparameter -> Objekt des fremden Nutzers. Ein neuer ``*_id``-Parameter
# fehlt hier und macht den Test rot, bis jemand das passende Objekt ergänzt.
_PARAM_TO_OBJECT = {
    "txn_id": "txn", "order_id": "order", "alert_id": "alert",
    "property_id": "property", "mortgage_id": "mortgage", "income_id": "property_income",
    "holding_id": "holding", "valuation_id": "valuation", "dividend_id": "pe_dividend",
    "tag_id": "tag", "bucket_id": "bucket", "rule_id": "rule", "profile_id": "profile",
    "pending_id": "pending_dividend", "scan_id": "scan",
}


def _foreign_ids(path: str, objects: dict) -> dict:
    ids = {}
    for name in _PATH_PARAM.findall(path):
        if not name.endswith("_id"):
            continue
        if name == "position_id":
            key = "pension" if "/vorsorge/" in path else "position"
        elif name == "expense_id":
            key = "metal_expense" if "/precious-metals/" in path else "property_expense"
        elif name == "item_id":
            key = "metal" if "/precious-metals/" in path else "watchlist_item"
        else:
            assert name in _PARAM_TO_OBJECT, (
                f"unbekannter ID-Parameter {name!r} in {path}: Objekt in _PARAM_TO_OBJECT ergänzen"
            )
            key = _PARAM_TO_OBJECT[name]
        ids[name] = objects[key]
    return ids


async def _seed_foreign_objects(client, db, token: str, email: str) -> dict:
    """Legt für den fremden Nutzer je ein Objekt jeder Art an, die eine Route per ID anspricht."""
    from models.import_profile import ImportProfile
    from models.pending_dividend import PendingDividend
    from models.private_equity import PrivateEquityDividend, PrivateEquityValuation
    from models.screening import ScreeningScan
    from models.transaction import Transaction, TransactionType
    from models.user import User

    h = api_auth(token)
    today = date.today().isoformat()
    user_id = (await db.execute(select(User.id).where(User.email == email))).scalar_one()

    async def _post(path: str, body: dict) -> dict:
        res = await client.post(f"{EXT}{path}", json=body, headers=h)
        assert res.status_code in (200, 201), f"Seed {path}: {res.status_code} {res.text}"
        return res.json()

    o: dict = {}
    o["position"] = (await _post("/positions", {
        "ticker": "FRGN", "name": SECRET, "type": "stock", "shares": 4, "cost_basis_chf": 0,
        "notes": SECRET,
    }))["id"]
    o["pension"] = (await _post("/positions", {
        "ticker": "PENSION_FRGN", "name": SECRET, "type": "pension", "cost_basis_chf": 0,
    }))["id"]
    o["order"] = (await _post("/pending-orders", {
        "ticker": "FRGN", "side": "buy", "shares": 1, "limit_price": 10, "notes": SECRET,
    }))["id"]
    o["watchlist_item"] = (await _post("/watchlist", {"ticker": "FRGNW", "name": SECRET}))["id"]
    o["tag"] = (await _post(f"/watchlist/{o['watchlist_item']}/tags", {"name": SECRET}))["id"]
    o["alert"] = (await _post("/alerts", {
        "ticker": "FRGNW", "alert_type": "price_above", "target_value": 1, "note": SECRET,
    }))["id"]
    o["property"] = (await _post("/immobilien", {
        "name": SECRET, "property_type": "efh", "purchase_price": 500000,
    }))["id"]
    o["mortgage"] = (await _post(f"/immobilien/{o['property']}/hypotheken", {
        "name": SECRET, "type": "fixed", "amount": 100000, "interest_rate": 1.5,
    }))["id"]
    o["property_expense"] = (await _post(f"/immobilien/{o['property']}/ausgaben", {
        "date": today, "category": "tax", "amount": 100, "description": SECRET,
    }))["id"]
    o["property_income"] = (await _post(f"/immobilien/{o['property']}/einnahmen", {
        "date": today, "amount": 100, "description": SECRET,
    }))["id"]
    o["holding"] = (await _post("/private-equity", {
        "company_name": SECRET, "num_shares": 10, "nominal_value": 100.0,
    }))["id"]
    await _post(f"/private-equity/{o['holding']}/valuations", {
        "valuation_date": today, "gross_value_per_share": 150.0, "notes": SECRET,
    })
    await _post(f"/private-equity/{o['holding']}/dividends", {
        "payment_date": today, "dividend_per_share": 2.0, "fiscal_year": 2025, "notes": SECRET,
    })
    # Die IDs aus der DB: die Antwort kommt in den Tests aus derselben Session
    # wie das Anlegen der Beteiligung und kennt die neuen Kindzeilen noch nicht.
    o["valuation"] = str((await db.execute(select(PrivateEquityValuation.id))).scalar_one())
    o["pe_dividend"] = str((await db.execute(select(PrivateEquityDividend.id))).scalar_one())
    o["metal"] = (await _post("/precious-metals", {
        "metal_type": "gold", "form": "bar", "weight_grams": 100.0, "purchase_date": today,
        "purchase_price_chf": 6000.0, "notes": SECRET,
    }))["id"]
    o["metal_expense"] = (await _post("/precious-metals/expenses", {
        "date": today, "category": "storage", "amount": 50, "description": SECRET,
    }))["id"]
    o["bucket"] = (await _post("/buckets", {"name": SECRET}))["id"]
    o["rule"] = (await _post("/buckets/import-rules", {
        "bucket_id": o["bucket"], "source": "ibkr", "ticker_pattern": "FRGN*",
    }))["id"]

    # Ohne eigene Schreib-Route oder mit Nebenwirkung (Snapshot-Regen): direkt in die DB.
    position_id = _uuid_mod.UUID(o["position"])
    txn = Transaction(
        user_id=user_id, position_id=position_id, type=TransactionType.buy, date=date.today(),
        shares=4, price_per_share=10, currency="CHF", fx_rate_to_chf=1, total_chf=40,
    )
    profile = ImportProfile(user_id=user_id, name=SECRET, column_mapping={"a": "b"}, type_mapping={"c": "d"})
    pending = PendingDividend(
        user_id=user_id, position_id=position_id, ex_date=date.today(), dividend_per_share=1,
        currency="CHF", shares_at_ex_date=4, expected_gross_chf=4,
    )
    scan = ScreeningScan(status="completed", steps=[])
    db.add_all([txn, profile, pending, scan])
    await db.commit()
    o["txn"], o["profile"], o["pending_dividend"], o["scan"] = (
        str(txn.id), str(profile.id), str(pending.id), str(scan.id),
    )
    return o


async def _row_counts(db) -> dict[str, int]:
    """Zeilen je Tabelle, in der die Routen mit ID schreiben oder löschen."""
    from models.bucket import Bucket
    from models.import_bucket_rule import ImportBucketRule
    from models.import_profile import ImportProfile
    from models.pending_dividend import PendingDividend
    from models.pending_order import PendingOrder
    from models.position import Position
    from models.precious_metal_expense import PreciousMetalExpense
    from models.precious_metal_item import PreciousMetalItem
    from models.price_alert import PriceAlert
    from models.private_equity import (
        PrivateEquityDividend, PrivateEquityHolding, PrivateEquityValuation,
    )
    from models.property import Mortgage, Property, PropertyExpense, PropertyIncome
    from models.transaction import Transaction
    from models.watchlist import WatchlistItem
    from models.watchlist_tag import watchlist_item_tags

    counts = {}
    for model in (
        Position, Transaction, PendingOrder, WatchlistItem, PriceAlert, Property,
        Mortgage, PropertyExpense, PropertyIncome, PrivateEquityHolding, PrivateEquityValuation,
        PrivateEquityDividend, PreciousMetalItem, PreciousMetalExpense, ImportBucketRule,
        ImportProfile, PendingDividend,
    ):
        counts[model.__tablename__] = await db.scalar(select(func.count()).select_from(model))
    counts["watchlist_item_tags"] = await db.scalar(select(func.count()).select_from(watchlist_item_tags))
    counts["buckets_active"] = await db.scalar(
        select(func.count()).select_from(Bucket).where(Bucket.deleted_at.is_(None))
    )
    counts["pending_dividends_open"] = await db.scalar(
        select(func.count()).select_from(PendingDividend).where(PendingDividend.status == "pending")
    )
    counts["orders_open"] = await db.scalar(
        select(func.count()).select_from(PendingOrder).where(PendingOrder.status == "open")
    )
    return counts


def _foreign_bodies(own_bucket_id: str) -> dict[tuple[str, str], dict]:
    """Gültige Bodies für die Routen mit Pflichtfeldern. Ohne gültigen Body
    antwortet FastAPI mit 422, bevor der Handler das Eigentum prüft."""
    today = date.today().isoformat()
    return {
        ("POST", "/pending-orders/{order_id}/fill"): {"price_per_share": 10.0, "fill_date": today},
        ("POST", "/immobilien/{property_id}/hypotheken"): {
            "name": "x", "type": "fixed", "amount": 1000, "interest_rate": 1.0},
        ("POST", "/immobilien/{property_id}/ausgaben"): {"date": today, "category": "tax", "amount": 1},
        ("POST", "/immobilien/{property_id}/einnahmen"): {"date": today, "amount": 1},
        ("POST", "/private-equity/{holding_id}/valuations"): {
            "valuation_date": today, "gross_value_per_share": 1.0},
        ("POST", "/private-equity/{holding_id}/dividends"): {
            "payment_date": today, "dividend_per_share": 1.0, "fiscal_year": 2025},
        ("POST", "/dividends/{pending_id}/confirm"): {"date": today, "total_chf": 1.0},
        ("POST", "/watchlist/{item_id}/tags"): {"name": "x"},
        # Ziel ist ein eigener Bucket: scheitern darf der Aufruf nur an der fremden Position.
        ("POST", "/positions/by-id/{position_id}/split-to-bucket"): {
            "target_bucket_id": own_bucket_id, "split_pct": 0.5},
        ("POST", "/positions/by-id/{position_id}/move-to-bucket"): {"target_bucket_id": own_bucket_id},
        ("PATCH", "/positions/by-id/{position_id}/stop-loss"): {"stop_loss_price": 1.0},
        ("PATCH", "/buckets/{bucket_id}"): {"name": "umbenannt"},
        ("PATCH", "/alerts/{alert_id}"): {"target_value": 2.0},
        ("PATCH", "/pending-orders/{order_id}"): {"notes": "geändert"},
        ("PUT", "/positions/by-id/{position_id}"): {"name": "umbenannt"},
        ("PUT", "/transactions/{txn_id}"): {"notes": "geändert"},
        ("PUT", "/immobilien/{property_id}"): {"name": "umbenannt"},
        ("PUT", "/immobilien/hypotheken/{mortgage_id}"): {"name": "umbenannt"},
        ("PUT", "/immobilien/ausgaben/{expense_id}"): {"amount": 2},
        ("PUT", "/immobilien/einnahmen/{income_id}"): {"amount": 2},
        ("PUT", "/private-equity/{holding_id}"): {"company_name": "umbenannt"},
        ("PUT", "/private-equity/{holding_id}/valuations/{valuation_id}"): {"discount_pct": 1.0},
        ("PUT", "/private-equity/{holding_id}/dividends/{dividend_id}"): {"dividend_per_share": 9.0},
        ("PUT", "/precious-metals/{item_id}"): {"notes": "geändert"},
        ("PUT", "/precious-metals/expenses/{expense_id}"): {"amount": 2},
    }


# Routen, die bei einer fremden ID bewusst nicht mit 404 antworten. Jede Zeile
# nennt den erwarteten Status und den Grund. Der Test prüft zusätzlich für alle
# Routen, dass keine fremden Daten in der Antwort stehen und keine Zeile sich ändert.
_FOREIGN_ID_EXPECTED = {
    ("GET", "/screening/scan/{scan_id}/progress"): (200, "Scans sind global, nicht je Nutzer"),
    # Der Service filtert auf user_id und liefert für einen fremden Bucket eine leere Reihe.
    ("GET", "/buckets/{bucket_id}/history"): (200, "leere Historie, keine fremden Daten"),
    ("GET", "/buckets/{bucket_id}/monthly-returns"): (200, "leere Monatsliste, keine fremden Daten"),
    # bucket_service meldet «nicht gefunden» als BucketError; die Route macht daraus 400.
    ("PATCH", "/buckets/{bucket_id}"): (400, "BucketError «Bucket nicht gefunden»"),
    ("DELETE", "/buckets/{bucket_id}"): (400, "BucketError «Bucket nicht gefunden»"),
    ("POST", "/positions/by-id/{position_id}/split-to-bucket"): (400, "BucketError «Position nicht gefunden»"),
    ("POST", "/positions/by-id/{position_id}/move-to-bucket"): (400, "BucketError «Position nicht gefunden»"),
}


class TestForeignIds:
    async def test_foreign_ids_are_not_reachable(self, client, db):
        """Nutzer A ruft jede Route mit ``*_id`` mit den IDs von Nutzer B auf.

        Erwartet ist 404, ohne Unterschied zu einer ID, die es nicht gibt.
        Antworten enthalten keine Daten von B, und in B's Tabellen ändert sich
        keine Zeile.
        """
        attacker, _ = await rw_tokens(client, "par-idor-a@example.com")
        victim, _ = await rw_tokens(client, "par-idor-b@example.com")
        objects = await _seed_foreign_objects(client, db, victim, "par-idor-b@example.com")
        own_bucket = await client.post(f"{EXT}/buckets", json={"name": "Eigener"}, headers=api_auth(attacker))
        assert own_bucket.status_code == 201, own_bucket.text
        bodies = _foreign_bodies(own_bucket.json()["id"])
        before = await _row_counts(db)

        failures = []
        checked = 0
        for route in _external_routes():
            ids = _foreign_ids(route.path, objects)
            if not ids:
                continue
            short = route.path.removeprefix(EXT)
            for method in _methods(route):
                checked += 1
                kwargs = {"headers": api_auth(attacker)}
                if method in ("POST", "PUT", "PATCH"):
                    kwargs["json"] = bodies.get((method, short), {})
                res = await client.request(method, _fill_path(route.path, ids), **kwargs)
                expected, _reason = _FOREIGN_ID_EXPECTED.get((method, short), (404, ""))
                if res.status_code != expected:
                    failures.append(f"{method} {short} -> {res.status_code} (erwartet {expected}): {res.text[:160]}")
                if SECRET in res.text:
                    failures.append(f"{method} {short} liefert Daten des fremden Nutzers")
        assert not failures, "Fremde IDs erreichbar:\n" + "\n".join(failures)
        assert checked >= 55  # kein leerer Durchlauf
        assert await _row_counts(db) == before
