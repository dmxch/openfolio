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
        json={"name": name, "write_access": write},
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
