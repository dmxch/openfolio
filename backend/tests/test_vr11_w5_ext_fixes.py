"""Vollreview 11/2026, Welle 5, externe API: Fehler aus den Fixes selbst.

R-extapi-1 (Summary-Cache bleibt nach Recalc und ETF-Sektor-Änderung alt),
R-extapi-2 (Limit je Token statt je Nutzer), R-extapi-3 (elf Schreibrouten
verlangten den Header Content-Type: application/json).
"""

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update
from starlette.requests import Request as StarletteRequest

import api.external_v1 as ext
import services.portfolio_service as ps
from api.auth import limiter
from models.position import Position
from models.transaction import Transaction, TransactionType
from models.user import User
from services import cache
from services.sector_mapping import FINVIZ_SECTORS
from tests.test_external_ui_parity import api_auth, jwt_auth, make_token, register_and_login

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/external"
TICKER = "ZZCACHE"


async def _tokens(client, email: str) -> tuple[str, str, str]:
    """(jwt, write_token, read_token) für einen frischen Nutzer."""
    jwt = await register_and_login(client, email)
    w = await make_token(client, jwt, name="w", write=True)
    r = await make_token(client, jwt, name="r", write=False)
    return jwt, w, r


# --- R-extapi-1: Schreibrouten leeren den Summary-Cache ---


@pytest.fixture
def summary_calls(monkeypatch):
    """Summary ohne Netz rechnen und die Berechnungen zählen."""
    monkeypatch.setattr(ps, "get_fx_rates_batch", lambda: {"CHF": 1.0})
    monkeypatch.setattr(ps, "prefetch_close_series", lambda tickers: None)
    monkeypatch.setattr(ps, "_get_ma_status", lambda t: {"ma_status": None, "ma_detail": None})
    monkeypatch.setattr(ps, "_get_mrs", lambda t: None)
    monkeypatch.setattr(ps, "get_stock_prices_bulk", lambda tickers: {})

    # Der echte Regen lädt Kurse. Für den Cache zählt nur, was er dort tut: er
    # wechselt die Versionsmarke und lässt den Schlüssel der Summary stehen.
    import services.snapshot_trigger as st

    async def _fake_regen(user_id):
        try:
            ps.bump_portfolio_cache_version(user_id)
        finally:
            st._finish_regen(user_id)

    monkeypatch.setattr(st, "_regen_safe", _fake_regen)

    calls = {"n": 0}
    real = ps.get_portfolio_summary

    async def counted(db, user_id=None):
        calls["n"] += 1
        return await real(db, user_id)

    monkeypatch.setattr(ps, "get_portfolio_summary", counted)
    return calls


async def _drifted_position(client, db, email: str) -> SimpleNamespace:
    """Nutzer mit einer Position, die 99 Stück trägt; das Ledger kennt 5."""
    jwt, w, r = await _tokens(client, email)
    res = await client.post(f"{BASE}/positions", json={
        "ticker": TICKER, "name": "Cache", "type": "stock", "currency": "CHF",
        "shares": 1, "cost_basis_chf": 0,
    }, headers=api_auth(w))
    assert res.status_code == 201, res.text
    pid = uuid.UUID(res.json()["id"])
    uid = (await db.execute(select(User.id).where(User.email == email))).scalar_one()
    db.add(Transaction(
        user_id=uid, position_id=pid, type=TransactionType.buy, date=date(2026, 11, 13),
        shares=5, price_per_share=100, currency="CHF", fx_rate_to_chf=1,
        fees_chf=0, taxes_chf=0, total_chf=500,
    ))
    await db.execute(update(Position).where(Position.id == pid).values(shares=99, cost_basis_chf=9900))
    await db.commit()
    key = f"portfolio_summary:{uid}"
    cache.delete(key)
    return SimpleNamespace(jwt=jwt, w=w, r=r, key=key)


async def _shares(client, read_token: str) -> float:
    res = await client.get(f"{BASE}/positions", headers=api_auth(read_token))
    assert res.status_code == 200, res.text
    return next(p["shares"] for p in res.json()["positions"] if p["ticker"] == TICKER)


class TestSummaryCacheAfterRecalc:
    @pytest.mark.parametrize("path", ["/positions/recalculate", "/performance/recalculate"])
    async def test_external_recalc_is_visible_in_the_next_read(self, client, db, summary_calls, path):
        """Vor dem Fix zeigte GET /positions bis 60 s die Stückzahl von vor dem Recalc."""
        u = await _drifted_position(client, db, f"w5-recalc-{path.split('/')[1]}@example.com")
        assert await _shares(client, u.r) == 99
        assert cache.get(u.key) is not None

        res = await client.post(f"{BASE}{path}", headers=api_auth(u.w))
        assert res.status_code == 200, res.text

        assert cache.get(u.key) is None
        assert await _shares(client, u.r) == 5

    @pytest.mark.parametrize("body", [None, {"tickers": [TICKER]}], ids=["all", "tickers"])
    async def test_internal_recalc_is_visible_in_the_next_read(self, client, db, summary_calls, body):
        u = await _drifted_position(client, db, f"w5-recalc-int-{'t' if body else 'a'}@example.com")
        assert await _shares(client, u.r) == 99
        assert cache.get(u.key) is not None

        res = await client.post("/api/portfolio/recalculate", json=body, headers=jwt_auth(u.jwt))
        assert res.status_code == 200, res.text

        assert cache.get(u.key) is None
        assert await _shares(client, u.r) == 5


class TestSummaryCacheAfterEtfSectors:
    _WEIGHTS = {"sectors": [{"sector": list(FINVIZ_SECTORS)[0], "weight_pct": 100}]}

    async def _write(self, client, u, internal: bool, method: str):
        url = f"/api/etf-sectors/{TICKER}" if internal else f"{BASE}/etf-sectors/{TICKER}"
        headers = jwt_auth(u.jwt) if internal else api_auth(u.w)
        if method == "put":
            return await client.put(url, json=self._WEIGHTS, headers=headers)
        return await client.delete(url, headers=headers)

    @pytest.mark.parametrize("internal", [False, True], ids=["external", "internal"])
    @pytest.mark.parametrize("method", ["put", "delete"])
    async def test_sector_write_makes_the_next_read_recompute(self, client, db, summary_calls, internal, method):
        """Vor dem Fix blieb die Sektor-Allokation der Summary bis 60 s alt."""
        u = await _drifted_position(client, db, f"w5-etf-{method}-{int(internal)}@example.com")
        res = await client.get(f"{BASE}/portfolio/summary", headers=api_auth(u.r))
        assert res.status_code == 200, res.text
        await client.get(f"{BASE}/portfolio/summary", headers=api_auth(u.r))
        assert summary_calls["n"] == 1, "der zweite Lesezugriff kommt aus dem Cache"

        res = await self._write(client, u, internal, method)
        assert res.status_code == 200, res.text

        assert cache.get(u.key) is None
        await client.get(f"{BASE}/portfolio/summary", headers=api_auth(u.r))
        assert summary_calls["n"] == 2


# --- R-extapi-2: Limit je Nutzer des Tokens ---


def _request(headers: dict | None = None, api_token=None) -> StarletteRequest:
    scope = {
        "type": "http", "method": "GET", "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("10.0.0.9", 1234),
    }
    request = StarletteRequest(scope)
    if api_token is not None:
        request.state.api_token = api_token
    return request


class TestRateLimitPerUser:
    async def test_two_tokens_of_one_user_share_a_key(self):
        user_id = uuid.uuid4()
        a = _request({"X-Forwarded-For": "203.0.113.9"}, SimpleNamespace(id=uuid.uuid4(), user_id=user_id))
        b = _request({"X-Forwarded-For": "2001:db8::1"}, SimpleNamespace(id=uuid.uuid4(), user_id=user_id))
        assert ext._token_rate_limit_key(a) == ext._token_rate_limit_key(b) == f"user:{user_id}"

    async def test_tokens_of_two_users_have_separate_keys(self):
        a = _request(api_token=SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4()))
        b = _request(api_token=SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4()))
        assert ext._token_rate_limit_key(a) != ext._token_rate_limit_key(b)

    async def test_more_tokens_do_not_multiply_the_budget(self, client, monkeypatch):
        """Vor dem Fix: drei Tokens eines Nutzers, je [200, 200, 429], also sechs Erfolge."""
        jwt = await register_and_login(client, "w5-rl@example.com")
        tokens = [await make_token(client, jwt, name=f"t{i}", write=True) for i in range(3)]
        other_jwt = await register_and_login(client, "w5-rl-other@example.com")
        other = await make_token(client, other_jwt, name="o", write=True)
        monkeypatch.setattr(
            "services.dividend_forecast_service.compute_dividend_forecast",
            AsyncMock(return_value={"ok": True}),
        )
        url = f"{BASE}/analysis/dividend-forecast/refresh"  # RL_REFRESH: 2 je Minute
        ip = {"X-Forwarded-For": "198.51.100.77"}
        limiter.enabled = True
        try:
            codes = []
            for token in tokens:
                for _ in range(2):
                    res = await client.post(url, headers={**api_auth(token), **ip})
                    codes.append(res.status_code)
            assert codes == [200, 200, 429, 429, 429, 429]
            # Ein anderer Nutzer hat ein eigenes Budget, auch von derselben Adresse.
            res = await client.post(url, headers={**api_auth(other), **ip})
            assert res.status_code == 200
        finally:
            limiter.enabled = False


# --- R-extapi-3: JSON ohne den Header Content-Type: application/json ---


def _lenient_routes(i: int) -> list[tuple[str, str, dict, int]]:
    """(Methode, Pfad, gültiger Body, erwarteter Status) der elf Routen.

    Der Status ist der mit application/json: 400 und 404 kommen aus der
    Fachlogik (unbekannte ID oder Vorlage), also nach dem Lesen des Bodys.
    """
    rnd = str(uuid.uuid4())
    return [
        ("patch", "/settings", {"number_format": "ch"}, 200),
        ("put", "/settings/alert-preferences", {"category": "price_alert", "is_enabled": False}, 200),
        ("post", "/buckets", {"name": f"Wachstum {i}"}, 201),
        ("patch", f"/buckets/{rnd}", {"name": "Neu"}, 400),
        ("post", "/buckets/from-template", {"template_key": "gibt-es-nicht"}, 400),
        ("post", f"/positions/by-id/{rnd}/split-to-bucket", {"target_bucket_id": rnd, "split_pct": 0.5}, 400),
        ("post", f"/positions/by-id/{rnd}/move-to-bucket", {"target_bucket_id": rnd}, 400),
        ("post", "/buckets/import-rules", {"bucket_id": rnd}, 400),
        ("post", "/import/parse-with-mapping", {"upload_id": rnd, "column_mapping": {}, "type_mapping": {}}, 404),
        ("post", "/import/confirm", {"transactions": []}, 201),
        ("post", "/import/profiles", {"name": f"Profil {i}", "column_mapping": {}, "type_mapping": {}}, 201),
    ]


_CONTENT_TYPES = [None, "application/x-www-form-urlencoded", "text/plain", "application/json"]
_ROUTE_IDS = [
    "settings", "alert-preferences", "bucket-create", "bucket-update", "from-template", "split-to-bucket",
    "move-to-bucket", "import-rules", "parse-with-mapping", "import-confirm", "import-profiles",
]


async def _send(client, method: str, path: str, raw: bytes, token: str | None, content_type: str | None):
    headers = api_auth(token) if token else {}
    if content_type:
        headers["Content-Type"] = content_type
    req = client.build_request(method.upper(), f"{BASE}{path}", content=raw, headers=headers)
    assert req.headers.get("content-type") == content_type
    return await client.send(req)


class TestJsonBodyWithAnyContentType:
    @pytest.mark.parametrize("index", range(11), ids=_ROUTE_IDS)
    async def test_valid_json_is_read_with_every_content_type(self, client, index):
        """Vor dem Fix: 422 ohne Header, mit x-www-form-urlencoded (curl -d) und mit text/plain."""
        import json

        _, w, _ = await _tokens(client, f"w5-ct-{index}@example.com")
        codes = {}
        for i, content_type in enumerate(_CONTENT_TYPES):
            method, path, body, expected = _lenient_routes(i)[index]
            res = await _send(client, method, path, json.dumps(body).encode(), w, content_type)
            codes[content_type] = res.status_code
        assert codes == {ct: expected for ct in _CONTENT_TYPES}

    async def test_curl_default_changes_the_setting(self, client):
        """curl -X PATCH "$B/settings" -H "X-API-Key: …" -d '{"number_format":"ch"}'"""
        _, w, r = await _tokens(client, "w5-ct-curl@example.com")
        res = await _send(
            client, "patch", "/settings", b'{"number_format":"de"}', w, "application/x-www-form-urlencoded",
        )
        assert res.status_code == 200, res.text
        res = await client.get(f"{BASE}/settings", headers=api_auth(r))
        assert res.json()["number_format"] == "de"

    @pytest.mark.parametrize("index", range(11), ids=_ROUTE_IDS)
    async def test_invalid_bodies_stay_422(self, client, index):
        _, w, _ = await _tokens(client, f"w5-ct-bad-{index}@example.com")
        method, path, _, _ = _lenient_routes(0)[index]
        for raw in (b"{not json", b"", b"[1, 2]", b"null", b"\xff\xfe"):
            for content_type in (None, "application/x-www-form-urlencoded"):
                res = await _send(client, method, path, raw, w, content_type)
                assert res.status_code == 422, (raw, content_type, res.text)
                assert res.json()["detail"][0]["loc"][0] == "body"

    async def test_field_error_names_the_field(self, client):
        _, w, _ = await _tokens(client, "w5-ct-field@example.com")
        res = await _send(client, "patch", "/settings", b'{"alert_vix": "x"}', w, None)
        assert res.status_code == 422
        assert res.json()["detail"][0]["loc"] == ["body", "alert_vix"]
        res = await _send(client, "post", "/buckets", b"{}", w, "text/plain")
        assert res.status_code == 422
        assert res.json()["detail"][0]["loc"] == ["body", "name"]

    async def test_validator_error_is_422_with_the_field_path(self, client):
        """Ein Datum ausserhalb der Grenze kommt aus einem Validator: 422, kein 500."""
        _, w, _ = await _tokens(client, "w5-ct-validator@example.com")
        raw = b'{"transactions": [{"type": "buy", "date": "0002-01-01"}]}'
        res = await _send(client, "post", "/import/confirm", raw, w, "application/x-www-form-urlencoded")
        assert res.status_code == 422, res.text
        assert res.json()["detail"][0]["loc"] == ["body", "transactions", 0, "date"]

    @pytest.mark.parametrize("index", range(11), ids=_ROUTE_IDS)
    async def test_without_api_key_the_answer_is_401_not_422(self, client, index):
        """Der Body wird erst nach der Anmeldung gelesen."""
        method, path, _, _ = _lenient_routes(0)[index]
        res = await _send(client, method, path, b"{not json", None, None)
        assert res.status_code == 401, res.text

    async def test_read_token_is_rejected(self, client):
        _, _, r = await _tokens(client, "w5-ct-scope@example.com")
        res = await _send(client, "patch", "/settings", b'{"number_format":"ch"}', r, None)
        assert res.status_code == 403

    async def test_other_write_routes_still_require_the_json_header(self, client):
        """docs/EXTERNAL_API.md: nur die elf Routen lesen JSON mit jedem Content-Type."""
        _, w, _ = await _tokens(client, "w5-ct-typed@example.com")
        raw = b'{"ticker": "ZZTYPED", "name": "T", "type": "stock", "currency": "CHF", "shares": 1, "cost_basis_chf": 0}'
        res = await _send(client, "post", "/positions", raw, w, "text/plain")
        assert res.status_code == 422
        res = await _send(client, "post", "/positions", raw, w, "application/json")
        assert res.status_code == 201, res.text
