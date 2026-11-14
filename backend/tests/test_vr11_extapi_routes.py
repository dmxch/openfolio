"""Vollreview 11/2026, externe API: Routen und Token-Service.

K099 (Limit je IP statt je Token), K062 (teure Aktionen), K112 (500 bei
ungültigem Body), K111 (500 aus dem internen Schema), K139 (Krypto-Metriken),
K158 (geteiltes Cache-Objekt), K159 und K160 (fehlendes Audit-Log), K122, K028
und K134 (Report-Vault), K006 und K023 (Datum und Ticker an der Route), K100
(FX-Codes), K137 (Cache-Schlüssel der Branchen-Route), K128 (last_used_at).
"""

import asyncio
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from limits import parse as parse_limit
from pydantic import BaseModel, Field
from sqlalchemy import event, func, select
from sqlalchemy.exc import DBAPIError
from starlette.requests import Request as StarletteRequest

import api.external_v1 as ext
from api.auth import limiter
from constants.limits import RL_HEAVY, RL_READ, RL_REFRESH
from dateutils import utcnow
from db import engine as test_engine
from models.api_token import ApiToken
from models.api_write_log import ApiWriteLog
from models.report import Report
from models.user import User
from services import api_token_service, cache
from tests.test_external_ui_parity import api_auth, rw_tokens

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/external"
TODAY = date.today().isoformat()


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


def _external_routes() -> list[APIRoute]:
    return [r for r in ext.router.routes if isinstance(r, APIRoute)]


def _limits_of(func_name: str) -> list:
    return [lim.limit for lim in limiter._route_limits.get(func_name, [])]


async def _log_actions(db, email: str) -> list[str]:
    user_id = (await db.execute(select(User.id).where(User.email == email))).scalar_one()
    rows = await db.execute(
        select(ApiWriteLog.action).where(ApiWriteLog.user_id == user_id).order_by(ApiWriteLog.created_at)
    )
    return [r[0] for r in rows]


# --- K099: Limit je Nutzer des API-Tokens (R-extapi-2: nicht je Token) ---


class TestRateLimitKey:
    async def test_key_is_the_user_of_the_token_not_the_client_ip(self):
        token = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4())
        a = _request({"X-Forwarded-For": "203.0.113.9"}, api_token=token)
        b = _request({"X-Forwarded-For": "2001:db8::1"}, api_token=token)
        assert ext._token_rate_limit_key(a) == ext._token_rate_limit_key(b) == f"user:{token.user_id}"

    async def test_tokens_of_two_users_from_one_ip_have_separate_keys(self):
        a = _request({"X-Forwarded-For": "203.0.113.9"}, api_token=SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4()))
        b = _request({"X-Forwarded-For": "203.0.113.9"}, api_token=SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4()))
        assert ext._token_rate_limit_key(a) != ext._token_rate_limit_key(b)

    async def test_without_token_the_client_counts_like_everywhere_else(self):
        assert ext._token_rate_limit_key(_request({"X-Forwarded-For": "203.0.113.9"})) == "203.0.113.9"

    async def test_every_authenticated_route_counts_per_token(self):
        """Iteriert den Router: eine neue Route mit @limiter.limit statt @ext_limit fällt auf."""
        missing, wrong_key = [], []
        for route in _external_routes():
            if route.path.endswith("/health"):
                continue
            name = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
            registered = limiter._route_limits.get(name)
            if not registered:
                missing.append(route.path)
            elif any(lim.key_func is not ext._token_rate_limit_key for lim in registered):
                wrong_key.append(route.path)
        assert not missing, f"Routen ohne eigenes Limit: {missing}"
        assert not wrong_key, f"Routen, die nicht je Token zählen: {wrong_key}"

    async def test_budget_follows_the_token_across_source_addresses(self, client, monkeypatch):
        """Vor dem Fix zählte der Limiter je IP: ein Token hatte mit jeder Quelladresse ein neues Budget."""
        w, _ = await rw_tokens(client, "vr11-rl@example.com")
        other, _ = await rw_tokens(client, "vr11-rl-other@example.com")
        monkeypatch.setattr(
            "services.dividend_forecast_service.compute_dividend_forecast",
            AsyncMock(return_value={"ok": True}),
        )
        url = f"{BASE}/analysis/dividend-forecast/refresh"  # RL_REFRESH: 2 je Minute
        limiter.enabled = True
        try:
            codes = []
            for ip in ("198.51.100.1", "198.51.100.2", "198.51.100.3"):
                res = await client.post(url, headers={**api_auth(w), "X-Forwarded-For": ip})
                codes.append(res.status_code)
            assert codes == [200, 200, 429]
            # Der Token eines anderen Nutzers hat ein eigenes Budget, auch von derselben Adresse.
            res = await client.post(url, headers={**api_auth(other), "X-Forwarded-For": "198.51.100.3"})
            assert res.status_code == 200
        finally:
            limiter.enabled = False


# --- K099 und K062: Limit-Werte ---


_TICKER_READ_ROUTES = [
    "get_position", "analysis_score", "analysis_heartbeat", "analysis_breakouts",
    "analysis_mrs", "analysis_levels", "analysis_reversal", "stock_profile_external",
    "etf_sectors_external", "screening_ticker_external", "market_sector_holdings_external",
]

# Externe Route -> interner Zwilling. Die externe Route darf nie mehr erlauben.
_INTERNAL_TWINS = {
    "performance_recalculate_external": "api.performance.recalculate_portfolio",
    "performance_fix_total_chf_external": "api.performance.fix_total_chf",
    "performance_regenerate_snapshots_external": "api.performance.regenerate_snapshots_endpoint",
    "performance_earnings_refresh_external": "api.performance.refresh_earnings",
    "recalculate_positions_external": "api.positions.recalculate_all",
    "recalculate_position_external": "api.positions.recalculate_single",
    "position_dividends_external": "api.positions.position_dividends",
    "market_sector_scores_external": "api.market.sector_holding_scores",
    "analysis_dividend_forecast_refresh": "api.analysis.dividend_forecast_refresh_endpoint",
    "bucket_backfill_snapshots_external": "api.buckets.trigger_bucket_snapshot_backfill",
    "bucket_migration_rollback_external": "api.buckets.migration_rollback_endpoint",
    "import_parse_external": "api.imports.parse_file",
    "import_analyze_external": "api.imports.analyze_csv",
    "import_parse_with_mapping_external": "api.imports.parse_with_mapping",
    "import_confirm_external": "api.imports.confirm",
    "screening_scan_external": "api.screening.start_scan",
}


def _per_second(item) -> float:
    return item.amount / item.get_expiry()


class TestLimitValues:
    @pytest.mark.parametrize("func", _TICKER_READ_ROUTES)
    async def test_ticker_read_routes_get_120_per_minute(self, func):
        """Der Limiter zählt je Route: alle Ticker teilen sich jetzt ein Budget."""
        assert _limits_of(f"api.external_v1.{func}") == [parse_limit(RL_READ)]

    async def test_every_get_route_with_a_ticker_in_the_path_is_covered(self):
        expected = {f"api.external_v1.{f}" for f in _TICKER_READ_ROUTES}
        expected.add("api.external_v1.market_sector_scores_external")  # teuer: RL_HEAVY
        found = {
            f"{r.endpoint.__module__}.{r.endpoint.__name__}"
            for r in _external_routes()
            if "GET" in r.methods and ("{ticker}" in r.path or "{etf_ticker}" in r.path)
        }
        assert found == expected

    @pytest.mark.parametrize("func, expected", [
        ("performance_recalculate_external", RL_HEAVY),
        ("performance_fix_total_chf_external", RL_HEAVY),
        ("performance_regenerate_snapshots_external", RL_HEAVY),
        ("performance_earnings_refresh_external", RL_HEAVY),
        ("recalculate_positions_external", RL_HEAVY),
        ("recalculate_position_external", RL_HEAVY),
        ("position_dividends_external", RL_HEAVY),
        ("market_sector_scores_external", RL_HEAVY),
        ("bucket_backfill_snapshots_external", RL_HEAVY),
        ("analysis_dividend_forecast_refresh", RL_REFRESH),
        ("bucket_migration_rollback_external", RL_REFRESH),
        ("import_parse_external", "10/minute"),
        ("import_analyze_external", "10/minute"),
        ("import_parse_with_mapping_external", "10/minute"),
        ("import_confirm_external", "3/minute"),
        ("screening_scan_external", "1/day"),
        ("portfolio_summary", "30/minute"),
    ])
    async def test_expensive_routes_have_the_internal_values(self, func, expected):
        assert _limits_of(f"api.external_v1.{func}") == [parse_limit(expected)]

    @pytest.mark.parametrize("func, twin", sorted(_INTERNAL_TWINS.items()))
    async def test_external_route_never_allows_more_than_its_internal_twin(self, func, twin):
        """K062: extern galten pauschal 30 je Minute, intern 2 bis 10."""
        import main  # noqa: F401 — lädt alle Router, damit die internen Limits registriert sind

        internal = _limits_of(twin)
        assert internal, f"interner Zwilling {twin} hat kein Limit (umbenannt?)"
        external = _limits_of(f"api.external_v1.{func}")
        assert external, func
        assert max(map(_per_second, external)) <= min(map(_per_second, internal)), (
            f"{func}: extern {external}, intern {internal}"
        )


class TestSnapshotRegenGuard:
    async def test_running_regen_answers_409_and_writes_no_log(self, client, db, monkeypatch):
        w, _ = await rw_tokens(client, "vr11-regen-busy@example.com")
        monkeypatch.setattr("services.snapshot_trigger.run_snapshot_regen", AsyncMock(return_value=None))
        res = await client.post(f"{BASE}/performance/regenerate-snapshots", headers=api_auth(w))
        assert res.status_code == 409
        assert "performance_regen_snapshots" not in await _log_actions(db, "vr11-regen-busy@example.com")

    async def test_regen_runs_through_the_guarded_helper(self, client, db, monkeypatch):
        """Der direkte Aufruf von regenerate_snapshots umging den Schutz gegen parallele Läufe."""
        w, _ = await rw_tokens(client, "vr11-regen@example.com")
        guarded = AsyncMock(return_value={"snapshots_created": 3})
        direct = AsyncMock(side_effect=AssertionError("regenerate_snapshots direkt aufgerufen"))
        monkeypatch.setattr("services.snapshot_trigger.run_snapshot_regen", guarded)
        monkeypatch.setattr("services.snapshot_service.regenerate_snapshots", direct)
        res = await client.post(f"{BASE}/performance/regenerate-snapshots", headers=api_auth(w))
        assert res.status_code == 200, res.text
        assert res.json() == {"snapshots_created": 3}
        assert guarded.await_count == 1
        assert "performance_regen_snapshots" in await _log_actions(db, "vr11-regen@example.com")


# --- K112 und K111: 422 statt 500 ---


_RAW_BODY_ROUTES = [
    ("patch", "/settings"),
    ("put", "/settings/alert-preferences"),
    ("post", "/buckets"),
    ("patch", f"/buckets/{uuid.uuid4()}"),
    ("post", "/buckets/from-template"),
    ("post", f"/positions/by-id/{uuid.uuid4()}/split-to-bucket"),
    ("post", f"/positions/by-id/{uuid.uuid4()}/move-to-bucket"),
    ("post", "/buckets/import-rules"),
    ("post", "/import/parse-with-mapping"),
    ("post", "/import/confirm"),
    ("post", "/import/profiles"),
]


class TestInvalidBody:
    @pytest.mark.parametrize("method, path", _RAW_BODY_ROUTES, ids=[f"{m} {p[:40]}" for m, p in _RAW_BODY_ROUTES])
    async def test_json_list_instead_of_object_is_422(self, client, method, path):
        """Die elf Routen lasen request.json() selbst: eine Liste endete als TypeError und 500."""
        w, _ = await rw_tokens(client, f"vr11-body-{abs(hash((method, path)))}@example.com")
        res = await getattr(client, method)(f"{BASE}{path}", json=[1, 2], headers=api_auth(w))
        assert res.status_code == 422, res.text

    @pytest.mark.parametrize("method, path", _RAW_BODY_ROUTES, ids=[f"{m} {p[:40]}" for m, p in _RAW_BODY_ROUTES])
    async def test_broken_json_is_422(self, client, method, path):
        w, _ = await rw_tokens(client, f"vr11-json-{abs(hash((method, path)))}@example.com")
        res = await getattr(client, method)(
            f"{BASE}{path}", content=b"{not json",
            headers={**api_auth(w), "Content-Type": "application/json"},
        )
        assert res.status_code == 422, res.text

    async def test_wrong_field_type_names_the_field(self, client):
        w, _ = await rw_tokens(client, "vr11-body-field@example.com")
        res = await client.patch(f"{BASE}/settings", json={"alert_vix": "x"}, headers=api_auth(w))
        assert res.status_code == 422
        assert res.json()["detail"][0]["loc"] == ["body", "alert_vix"]

    async def test_missing_required_field_is_422(self, client):
        w, _ = await rw_tokens(client, "vr11-body-req@example.com")
        res = await client.post(f"{BASE}/buckets", json={}, headers=api_auth(w))
        assert res.status_code == 422
        res = await client.post(f"{BASE}/import/profiles", json={"name": "x"}, headers=api_auth(w))
        assert res.status_code == 422

    async def test_valid_bodies_still_work(self, client):
        w, _ = await rw_tokens(client, "vr11-body-ok@example.com")
        res = await client.patch(f"{BASE}/settings", json={"alert_vix": False}, headers=api_auth(w))
        assert res.status_code == 200, res.text
        res = await client.post(f"{BASE}/buckets", json={"name": "Wachstum"}, headers=api_auth(w))
        assert res.status_code == 201, res.text

    async def test_to_internal_turns_a_validation_error_into_422(self):
        class Strict(BaseModel):
            code: str = Field(max_length=3)

        assert ext._to_internal(Strict, {"code": "abc"}).code == "abc"
        with pytest.raises(RequestValidationError) as exc:
            ext._to_internal(Strict, {"code": "abcdef"})
        assert exc.value.errors()[0]["loc"] == ("body", "code")

    @pytest.mark.parametrize("payload", [{"style": "foo"}, {"pricing_mode": None}, {"price_source": None}])
    async def test_position_create_with_invalid_enum_is_422(self, client, payload):
        w, _ = await rw_tokens(client, f"vr11-enum-{abs(hash(str(payload)))}@example.com")
        body = {"ticker": "TESTPOS", "name": "Test", "type": "stock", "cost_basis_chf": 0, **payload}
        res = await client.post(f"{BASE}/positions", json=body, headers=api_auth(w))
        assert res.status_code == 422, res.text

    async def test_position_update_with_invalid_enum_or_null_is_422(self, client):
        w, _ = await rw_tokens(client, "vr11-enum-upd@example.com")
        created = await client.post(
            f"{BASE}/positions", headers=api_auth(w),
            json={"ticker": "TESTPOS", "name": "Test", "type": "stock", "cost_basis_chf": 0},
        )
        assert created.status_code == 201, created.text
        url = f"{BASE}/positions/by-id/{created.json()['id']}"
        for payload in ({"style": "foo"}, {"pricing_mode": None}, {"name": None}):
            res = await client.put(url, json=payload, headers=api_auth(w))
            assert res.status_code == 422, (payload, res.text)
        ok = await client.put(url, json={"style": "core", "pricing_mode": "manual"}, headers=api_auth(w))
        assert ok.status_code == 200, ok.text
        assert ok.json()["style"] == "core"


# --- K006 und K023 an der Route ---


class TestDatesAndTickersAtTheRoute:
    async def test_transaction_date_in_year_2_is_422(self, client):
        w, _ = await rw_tokens(client, "vr11-date-txn@example.com")
        res = await client.post(
            f"{BASE}/transactions", headers=api_auth(w),
            json={"ticker": "AAPL", "type": "buy", "date": "0002-01-01", "shares": 1,
                  "price_per_share": 10, "total_chf": 10},
        )
        assert res.status_code == 422, res.text

    async def test_fill_date_in_year_2_is_422_and_order_stays_open(self, client, db):
        w, _ = await rw_tokens(client, "vr11-date-fill@example.com")
        order = await client.post(
            f"{BASE}/pending-orders", headers=api_auth(w),
            json={"ticker": "AAPL", "side": "buy", "shares": 1, "limit_price": 100},
        )
        assert order.status_code == 201, order.text
        res = await client.post(
            f"{BASE}/pending-orders/{order.json()['id']}/fill", headers=api_auth(w),
            json={"price_per_share": 100, "fill_date": "0002-01-01"},
        )
        assert res.status_code == 422, res.text
        from models.pending_order import PendingOrder
        assert (await db.execute(select(PendingOrder.status))).scalars().all() == ["open"]

    @pytest.mark.parametrize("path, target", [
        ("/analysis/score/{t}", "services.scoring_service.assess_ticker"),
        ("/analysis/heartbeat/{t}", "services.chart_service.get_heartbeat_pattern"),
        ("/analysis/breakouts/{t}", "services.chart_service.get_breakout_events"),
        ("/analysis/mrs/{t}", "services.chart_service.get_mrs_history"),
        ("/analysis/levels/{t}", "services.chart_service.get_support_resistance_levels"),
        ("/analysis/reversal/{t}", "services.chart_service.get_three_point_reversal"),
        ("/stock/{t}/profile", "services.stock_service.get_company_profile"),
    ])
    @pytest.mark.parametrize("ticker", ["AAPL,MSFT,GOOG", "AAPL%20MSFT", "A" * 31])
    async def test_multi_symbol_path_never_reaches_yahoo(self, client, monkeypatch, path, target, ticker):
        """yfinance zerlegt den Wert an Komma und Leerzeichen: ein Pfad mit 8 KB ergab 1500 Abrufe."""
        _, r = await rw_tokens(client, f"vr11-tick-{abs(hash((path, ticker)))}@example.com")
        service = MagicMock(return_value={})
        monkeypatch.setattr(target, service)
        res = await client.get(f"{BASE}{path.format(t=ticker)}", headers=api_auth(r))
        assert res.status_code == 422, res.text
        service.assert_not_called()

    async def test_single_symbol_still_works(self, client, monkeypatch):
        _, r = await rw_tokens(client, "vr11-tick-ok@example.com")
        monkeypatch.setattr("services.chart_service.get_breakout_events", MagicMock(return_value=[]))
        res = await client.get(f"{BASE}/analysis/breakouts/brk-b", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert res.json() == {"ticker": "BRK-B", "breakouts": []}

    async def test_etf_sector_ticker_longer_than_the_column_is_422(self, client):
        w, _ = await rw_tokens(client, "vr11-etf-len@example.com")
        body = {"sectors": [{"sector": "Technology", "weight_pct": 100.0}]}
        res = await client.put(f"{BASE}/etf-sectors/{'A' * 21}", json=body, headers=api_auth(w))
        assert res.status_code == 422, res.text
        ok = await client.put(f"{BASE}/etf-sectors/{'A' * 20}", json=body, headers=api_auth(w))
        assert ok.status_code == 200, ok.text

    async def test_watchlist_add_rejects_a_symbol_list(self, client):
        w, _ = await rw_tokens(client, "vr11-wl@example.com")
        res = await client.post(f"{BASE}/watchlist", json={"ticker": "AA,AB,AC", "name": "x"}, headers=api_auth(w))
        assert res.status_code == 422
        ok = await client.post(f"{BASE}/watchlist", json={"ticker": " nvda ", "name": "Nvidia"}, headers=api_auth(w))
        assert ok.status_code == 201, ok.text
        assert ok.json()["ticker"] == "NVDA"

    async def test_benchmark_returns_uses_the_shared_allowlist(self, client, monkeypatch):
        """Die Doku nennt sechs Benchmarks; die Route kannte nur vier."""
        _, r = await rw_tokens(client, "vr11-bench@example.com")
        service = MagicMock(return_value={"ticker": "URTH"})
        monkeypatch.setattr("services.benchmark_service.get_benchmark_monthly_returns", service)
        for ticker in ("URTH", "MTUM", "^GSPC"):
            res = await client.get(f"{BASE}/performance/benchmark-returns", params={"ticker": ticker}, headers=api_auth(r))
            assert res.status_code == 200, (ticker, res.text)
        res = await client.get(f"{BASE}/performance/benchmark-returns", params={"ticker": "AAPL,MSFT"}, headers=api_auth(r))
        assert res.status_code == 400
        assert service.call_count == 3


# --- K100: FX-Codes ---


class TestFxCodes:
    @pytest.mark.parametrize("url", [
        "/market/fx/QQQAA", "/market/fx/US", "/market/fx/U5D",
        "/market/fx/USD?to_currency=EURO", "/market/fx/USD?to_currency=E1",
    ])
    async def test_codes_must_have_exactly_three_letters(self, client, monkeypatch, url):
        """Fünf Buchstaben ergaben rund 12 Millionen mögliche Codes, je Code ein Yahoo-Abruf."""
        _, r = await rw_tokens(client, f"vr11-fx-{abs(hash(url))}@example.com")
        service = MagicMock(return_value=1.0)
        monkeypatch.setattr("services.utils.get_fx_rate", service)
        res = await client.get(f"{BASE}{url}", headers=api_auth(r))
        assert res.status_code == 422, res.text
        service.assert_not_called()

    async def test_valid_codes_are_upper_cased(self, client, monkeypatch):
        _, r = await rw_tokens(client, "vr11-fx-ok@example.com")
        service = MagicMock(return_value=0.91)
        monkeypatch.setattr("services.utils.get_fx_rate", service)
        res = await client.get(f"{BASE}/market/fx/usd?to_currency=eur", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert res.json() == {"from": "USD", "to": "EUR", "rate": 0.91}
        service.assert_called_once_with("USD", "EUR")
        res = await client.get(f"{BASE}/market/fx/USD", headers=api_auth(r))
        assert res.json()["to"] == "CHF"


# --- K137: Branchen-Route ohne Cache je Parameter ---


class TestIndustriesCache:
    async def test_free_float_parameter_creates_no_cache_entries(self, client, monkeypatch):
        _, r = await rw_tokens(client, "vr11-ind@example.com")
        service = AsyncMock(return_value={"scraped_at": None, "period": "ytd", "count": 0, "rows": []})
        monkeypatch.setattr(ext, "get_latest_industries", service)
        written: list[str] = []
        real_set = cache.set
        monkeypatch.setattr(cache, "set", lambda key, *a, **kw: (written.append(key), real_set(key, *a, **kw))[1])
        for mcap in ("1.000001", "1.000002", "1.000003"):
            res = await client.get(f"{BASE}/market/industries?min_mcap={mcap}&top=5", headers=api_auth(r))
            assert res.status_code == 200, res.text
        assert service.await_count == 3
        assert not [k for k in written if "industries" in k]


# --- K139: Krypto-Metriken ---


@pytest.fixture
def crypto_sources(monkeypatch):
    """Die drei Quellen als Mocks; der geteilte Cache-Eintrag ist vor und nach dem Test leer."""
    cache.delete("crypto_metrics")
    coingecko = AsyncMock()
    plain = AsyncMock(return_value={"data": [{"value": "61", "value_classification": "Greed"}]})

    async def _coingecko(url, params=None, timeout=15):
        await asyncio.sleep(0.01)  # der Leader hält die Sperre, während die anderen ankommen
        await coingecko(url)
        if url.endswith("/global"):
            return {"data": {"market_cap_percentage": {"btc": 56.44}}}
        return {"market_data": {"ath": {"chf": 100000.0}, "current_price": {"chf": 80000.0}}}

    monkeypatch.setattr("services.api_utils.fetch_json_coingecko", _coingecko)
    monkeypatch.setattr("services.api_utils.fetch_json", plain)
    monkeypatch.setattr(
        "services.price_service.get_stock_price",
        lambda ticker: {"price": 104.2, "change_pct": 0.3},
    )
    ttls: list[int] = []
    real_set = cache.set

    def _spy(key, value, ttl=cache.DEFAULT_TTL):
        if key == "crypto_metrics":
            ttls.append(ttl)
        return real_set(key, value, ttl)

    monkeypatch.setattr(cache, "set", _spy)
    monkeypatch.setattr(limiter, "enabled", False)
    yield SimpleNamespace(coingecko=coingecko, plain=plain, ttls=ttls)
    cache.delete("crypto_metrics")
    # Eine asyncio.Lock bindet sich bei Wartenden an den Event-Loop dieses Tests.
    cache._key_locks.pop("crypto_metrics", None)


class TestCryptoMetrics:
    async def test_cold_cache_fetches_once_for_parallel_requests(self, crypto_sources):
        """Vorher startete jeder gleichzeitige Request seine eigenen CoinGecko-Abrufe."""
        results = await asyncio.gather(*[
            ext.market_crypto_metrics_external(request=_request(), _user=None) for _ in range(8)
        ])
        assert crypto_sources.coingecko.await_count == 2  # /global und /coins/bitcoin, einmal
        assert crypto_sources.plain.await_count == 1
        assert all(r == results[0] for r in results)
        assert results[0]["tier1"]["btc_dominance"] == 56.4
        assert results[0]["tier1"]["fear_greed_value"] == 61
        assert results[0]["tier2"]["btc_ath_distance_pct"] == -20.0

    async def test_coingecko_goes_through_the_rate_limited_fetch(self, crypto_sources):
        await ext.market_crypto_metrics_external(request=_request(), _user=None)
        plain_urls = [call.args[0] for call in crypto_sources.plain.await_args_list]
        assert plain_urls == ["https://api.alternative.me/fng/?limit=1"]

    async def test_complete_result_is_cached_15_minutes(self, crypto_sources):
        await ext.market_crypto_metrics_external(request=_request(), _user=None)
        assert crypto_sources.ttls == [900]

    async def test_partial_result_is_cached_only_briefly(self, crypto_sources, monkeypatch):
        """Ein 429 von CoinGecko galt sonst 15 Minuten für alle Nutzer, auch im UI."""
        async def _failing(url, params=None, timeout=15):
            raise RuntimeError("429 Too Many Requests")

        monkeypatch.setattr("services.api_utils.fetch_json_coingecko", _failing)
        result = await ext.market_crypto_metrics_external(request=_request(), _user=None)
        assert crypto_sources.ttls == [60]
        assert "btc_dominance" not in result["tier1"]
        assert result["tier1"]["fear_greed_value"] == 61
        assert result["tier1"]["dxy_value"] == 104.2

    @pytest.mark.parametrize("fng_payload", [
        {"data": []}, {"data": None}, {}, [], {"data": [{}]}, {"data": [{"value": "n/a"}]}, {"data": ["x"]},
    ])
    async def test_unexpected_fear_and_greed_payload_is_no_error(self, crypto_sources, fng_payload):
        """fng_data.get("data", [{}])[0] warf bei leerer Liste IndexError."""
        crypto_sources.plain.return_value = fng_payload
        result = await ext.market_crypto_metrics_external(request=_request(), _user=None)
        assert "fear_greed_value" not in result["tier1"]
        assert result["tier1"]["btc_dominance"] == 56.4
        assert crypto_sources.ttls == [60]

    async def test_unexpected_coingecko_payload_is_no_error(self, crypto_sources, monkeypatch):
        async def _odd(url, params=None, timeout=15):
            return {"data": {"market_cap_percentage": None}, "market_data": {"ath": []}}

        monkeypatch.setattr("services.api_utils.fetch_json_coingecko", _odd)
        result = await ext.market_crypto_metrics_external(request=_request(), _user=None)
        assert result["tier2"] == {}
        assert "btc_dominance" not in result["tier1"]


# --- K158: geteiltes Cache-Objekt ---


class TestScoreDoesNotMutateSharedObject:
    async def test_user_data_is_not_written_into_the_cached_assessment(self, client, monkeypatch):
        """assess_ticker liefert das Objekt aus dem Prozess-Cache; der Handler hängte Nutzerdaten daran."""
        _, r = await rw_tokens(client, "vr11-score@example.com")
        shared = {"ticker": "AAPL", "score": 5, "max_score": 10, "price": 190.0}
        monkeypatch.setattr("services.scoring_service.assess_ticker", lambda *a, **kw: shared)
        # Der Handler holt Konzentration und Summary in einem Aufruf (K012).
        monkeypatch.setattr(
            "services.concentration_service.get_concentration_with_summary",
            AsyncMock(return_value=({"single_name": {"total_chf": 4242.0}}, {"total_market_value_chf": 99.0})),
        )
        res = await client.get(f"{BASE}/analysis/score/AAPL", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert res.json()["concentration"] == {"single_name": {"total_chf": 4242.0}}
        assert res.json()["liquid_portfolio_chf"] == 99.0
        assert shared == {"ticker": "AAPL", "score": 5, "max_score": 10, "price": 190.0}

    async def test_failed_concentration_does_not_leak_either(self, client, monkeypatch):
        _, r = await rw_tokens(client, "vr11-score-fail@example.com")
        shared = {"ticker": "AAPL", "score": 5, "max_score": 10, "price": 190.0}
        monkeypatch.setattr("services.scoring_service.assess_ticker", lambda *a, **kw: shared)
        monkeypatch.setattr(
            "services.concentration_service.get_concentration_with_summary",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        res = await client.get(f"{BASE}/analysis/score/AAPL", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert res.json()["liquid_portfolio_chf"] is None
        assert "concentration" not in shared and "liquid_portfolio_chf" not in shared


# --- K159 und K160: Audit-Log ---


class TestAuditLog:
    async def test_fire_assumptions_put_writes_a_log_entry(self, client, db):
        w, _ = await rw_tokens(client, "vr11-fire@example.com")
        res = await client.put(
            f"{BASE}/analysis/fire-assumptions", headers=api_auth(w),
            json={"capital_base": "liquid", "annual_return_pct": 4.0, "annual_savings_chf": 1000.0,
                  "withdrawal_rate_pct": 3.5, "target_annual_spending_chf": 60000.0},
        )
        assert res.status_code == 200, res.text
        assert await _log_actions(db, "vr11-fire@example.com") == ["settings_update"]

    async def test_report_vault_writes_leave_a_trace(self, client, db):
        """Upload, Update, Archive, Unarchive, Prune und Delete schrieben kein Audit-Log."""
        email = "vr11-report-log@example.com"
        w, _ = await rw_tokens(client, email)
        h = api_auth(w)
        upload = {"title": "Q3", "body": "erster Stand", "source": "sync", "source_path": "q3.md"}

        created = await client.post(f"{BASE}/reports", json=upload, headers=h)
        assert created.json()["status"] == "created"
        rid = created.json()["id"]
        assert await _log_actions(db, email) == ["report_upload"]

        unchanged = await client.post(f"{BASE}/reports", json=upload, headers=h)
        assert unchanged.json()["status"] == "unchanged"
        assert await _log_actions(db, email) == ["report_upload"]  # nichts geschrieben, kein Eintrag

        updated = await client.post(f"{BASE}/reports", json={**upload, "body": "zweiter Stand"}, headers=h)
        assert updated.json()["status"] == "updated"
        await client.patch(f"{BASE}/reports/{rid}", json={"title": "Q3 final"}, headers=h)
        await client.patch(f"{BASE}/reports/{rid}", json={}, headers=h)  # No-op
        await client.post(f"{BASE}/reports/{rid}/archive", headers=h)
        await client.post(f"{BASE}/reports/{rid}/archive", headers=h)  # idempotent
        await client.post(f"{BASE}/reports/{rid}/unarchive", headers=h)
        await client.post(f"{BASE}/reports/{rid}/unarchive", headers=h)  # idempotent
        assert await _log_actions(db, email) == [
            "report_upload", "report_upload", "report_update", "report_archive", "report_unarchive",
        ]

        noop = await client.post(f"{BASE}/reports/prune", json={"source": "sync", "source_paths": ["q3.md"]}, headers=h)
        assert noop.json()["archived"] == 0
        pruned = await client.post(f"{BASE}/reports/prune", json={"source": "sync", "source_paths": ["other.md"]}, headers=h)
        assert pruned.json()["archived"] == 1
        resurrected = await client.post(f"{BASE}/reports", json={**upload, "body": "zweiter Stand"}, headers=h)
        assert resurrected.json()["status"] == "unchanged"
        deleted = await client.delete(f"{BASE}/reports/{rid}", headers=h)
        assert deleted.status_code == 204
        assert (await _log_actions(db, email))[5:] == ["report_prune", "report_upload", "report_delete"]

        rows = (await db.execute(select(ApiWriteLog).where(ApiWriteLog.action.like("report_%")))).scalars().all()
        assert {r.target_id for r in rows if r.action != "report_prune"} == {uuid.UUID(rid)}
        assert all(r.token_id is not None for r in rows)

    async def test_report_actions_fit_the_action_column(self):
        for action in ("report_upload", "report_update", "report_delete",
                       "report_prune", "report_archive", "report_unarchive"):
            assert len(action) <= ApiWriteLog.__table__.c.action.type.length


# --- K122, K028, K134: Report-Vault ---


class _FakeDb:
    def __init__(self, dialect: str):
        self._dialect = dialect
        self.statements: list[str] = []

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name=self._dialect))

    async def execute(self, stmt):
        self.statements.append(str(stmt))


def _db_error(sqlstate: str | None) -> DBAPIError:
    orig = Exception("canceling statement due to statement timeout")
    orig.sqlstate = sqlstate
    return DBAPIError("SELECT 1", {}, orig)


class TestReportVault:
    async def test_date_filters_are_dates(self, client):
        """Als str deklariert verglich Postgres date mit varchar: jeder Aufruf mit Filter endete als 500."""
        w, r = await rw_tokens(client, "vr11-report-date@example.com")
        for title, day in (("alt", "2025-12-31"), ("mitte", "2026-03-15"), ("neu", "2026-09-01")):
            res = await client.post(
                f"{BASE}/reports", headers=api_auth(w),
                json={"title": title, "body": f"Text {title}", "report_date": day},
            )
            assert res.status_code == 201, res.text
        res = await client.get(f"{BASE}/reports?date_from=2026-01-01&date_to=2026-06-30", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert [x["title"] for x in res.json()["results"]] == ["mitte"]
        res = await client.get(f"{BASE}/reports?date_from=2026-03-15", headers=api_auth(r))
        assert {x["title"] for x in res.json()["results"]} == {"mitte", "neu"}
        for bad in ("date_from=gestern", "date_to=2026-13-01", "date_from=01.01.2026"):
            res = await client.get(f"{BASE}/reports?{bad}", headers=api_auth(r))
            assert res.status_code == 422, (bad, res.text)

    async def test_search_term_is_capped_at_64_characters(self, client):
        _, r = await rw_tokens(client, "vr11-report-q@example.com")
        assert (await client.get(f"{BASE}/reports", params={"q": "x" * 65}, headers=api_auth(r))).status_code == 422
        assert (await client.get(f"{BASE}/reports", params={"q": "x" * 64}, headers=api_auth(r))).status_code == 200

    async def test_statement_timeout_is_set_on_postgres_only(self, monkeypatch):
        monkeypatch.setattr(ext.app_settings, "db_statement_timeout_ms", 0)
        pg, sqlite = _FakeDb("postgresql"), _FakeDb("sqlite")
        await ext._set_local_statement_timeout(pg, ext._REPORT_QUERY_TIMEOUT_MS)
        await ext._set_local_statement_timeout(sqlite, ext._REPORT_QUERY_TIMEOUT_MS)
        assert pg.statements == ["SET LOCAL statement_timeout = 3000"]
        assert sqlite.statements == []

    async def test_stricter_operator_timeout_is_not_loosened(self, monkeypatch):
        pg = _FakeDb("postgresql")
        monkeypatch.setattr(ext.app_settings, "db_statement_timeout_ms", 1000)
        await ext._set_local_statement_timeout(pg, 3000)
        assert pg.statements == []
        monkeypatch.setattr(ext.app_settings, "db_statement_timeout_ms", 30000)
        await ext._set_local_statement_timeout(pg, 3000)
        assert pg.statements == ["SET LOCAL statement_timeout = 3000"]

    async def test_timeout_is_set_before_the_list_queries(self, client, monkeypatch):
        _, r = await rw_tokens(client, "vr11-report-order@example.com")
        calls: list[int] = []

        async def _spy(db, timeout_ms):
            calls.append(timeout_ms)

        monkeypatch.setattr(ext, "_set_local_statement_timeout", _spy)
        assert (await client.get(f"{BASE}/reports?q=abc", headers=api_auth(r))).status_code == 200
        assert (await client.get(f"{BASE}/reports?tag=x", headers=api_auth(r))).status_code == 200
        assert calls == [3000, 3000]

    async def test_query_canceled_is_recognised(self):
        assert ext._is_statement_timeout(_db_error("57014")) is True
        assert ext._is_statement_timeout(_db_error("23505")) is False
        assert ext._is_statement_timeout(_db_error(None)) is False

    async def test_canceled_search_answers_503(self, client, monkeypatch):
        _, r = await rw_tokens(client, "vr11-report-503@example.com")

        async def _canceled(db, timeout_ms):
            raise _db_error("57014")

        monkeypatch.setattr(ext, "_set_local_statement_timeout", _canceled)
        res = await client.get(f"{BASE}/reports?q=abc", headers=api_auth(r))
        assert res.status_code == 503
        assert "zu lange gedauert" in res.json()["detail"]

    async def test_other_database_errors_are_not_swallowed(self, client, monkeypatch):
        _, r = await rw_tokens(client, "vr11-report-500@example.com")

        async def _broken(db, timeout_ms):
            raise _db_error("08006")

        monkeypatch.setattr(ext, "_set_local_statement_timeout", _broken)
        # Je nach Transport kommt der Fehler als Exception oder als 500 an, nie als 503.
        try:
            res = await client.get(f"{BASE}/reports?q=abc", headers=api_auth(r))
        except DBAPIError:
            return
        assert res.status_code == 500

    async def test_total_body_size_per_user_is_limited(self, client, db, monkeypatch):
        """5000 Reports zu je 200'000 Zeichen ergaben 1 GB je Nutzer, die jede Suche las."""
        monkeypatch.setattr(ext, "MAX_REPORT_TOTAL_BYTES_PER_USER", 100)
        w, _ = await rw_tokens(client, "vr11-quota@example.com")
        other, _ = await rw_tokens(client, "vr11-quota-other@example.com")
        h = api_auth(w)

        first = await client.post(f"{BASE}/reports", json={"title": "a", "body": "x" * 60, "source_path": "a.md"}, headers=h)
        assert first.status_code == 201, first.text
        over = await client.post(f"{BASE}/reports", json={"title": "b", "body": "y" * 41, "source_path": "b.md"}, headers=h)
        assert over.status_code == 400
        assert "Speicherlimit" in over.json()["detail"]
        fits = await client.post(f"{BASE}/reports", json={"title": "b", "body": "y" * 40, "source_path": "b.md"}, headers=h)
        assert fits.status_code == 201, fits.text

        # Ersetzen zählt den alten Body nicht mit: 60 -> 55 passt, 60 -> 61 nicht.
        smaller = await client.post(f"{BASE}/reports", json={"title": "a", "body": "z" * 55, "source_path": "a.md"}, headers=h)
        assert smaller.json()["status"] == "updated"
        bigger = await client.post(f"{BASE}/reports", json={"title": "a", "body": "z" * 61, "source_path": "a.md"}, headers=h)
        assert bigger.status_code == 400

        # Derselbe Weg über PATCH.
        rid = first.json()["id"]
        assert (await client.patch(f"{BASE}/reports/{rid}", json={"body": "p" * 61}, headers=h)).status_code == 400
        assert (await client.patch(f"{BASE}/reports/{rid}", json={"body": "p" * 60}, headers=h)).status_code == 200

        # Das Kontingent gilt je Nutzer.
        res = await client.post(f"{BASE}/reports", json={"title": "c", "body": "c" * 90}, headers=api_auth(other))
        assert res.status_code == 201, res.text
        total = (await db.execute(select(func.sum(func.length(Report.body))))).scalar()
        assert total == 60 + 40 + 90

    async def test_archived_reports_count_towards_the_quota(self, client, monkeypatch):
        monkeypatch.setattr(ext, "MAX_REPORT_TOTAL_BYTES_PER_USER", 100)
        w, _ = await rw_tokens(client, "vr11-quota-arch@example.com")
        h = api_auth(w)
        first = await client.post(f"{BASE}/reports", json={"title": "a", "body": "x" * 80}, headers=h)
        await client.post(f"{BASE}/reports/{first.json()['id']}/archive", headers=h)
        res = await client.post(f"{BASE}/reports", json={"title": "b", "body": "y" * 30}, headers=h)
        assert res.status_code == 400


# --- K128: last_used_at ---


@pytest.fixture
def clean_touch_memory():
    api_token_service._last_touch.clear()
    yield
    api_token_service._last_touch.clear()


class TestLastUsedThrottle:
    async def test_should_touch_only_when_the_stored_value_is_older_than_the_interval(self, clean_touch_memory):
        now = utcnow()
        assert api_token_service._should_touch(uuid.uuid4(), now - timedelta(seconds=10), now) is False
        assert api_token_service._should_touch(uuid.uuid4(), now - timedelta(seconds=61), now) is True
        assert api_token_service._should_touch(uuid.uuid4(), None, now) is True

    async def test_parallel_requests_schedule_one_write(self, clean_touch_memory):
        """Gleichzeitige Requests sehen alle denselben alten DB-Wert."""
        token_id, now = uuid.uuid4(), utcnow()
        decisions = [api_token_service._should_touch(token_id, None, now) for _ in range(30)]
        assert decisions.count(True) == 1
        later = now + timedelta(seconds=61)
        assert api_token_service._should_touch(token_id, None, later) is True

    async def test_verify_token_writes_at_most_once_per_interval(self, db, monkeypatch, clean_touch_memory):
        """Vorher: je Request ein Task mit eigener Session, SELECT, UPDATE und COMMIT."""
        user = User(email="vr11-touch@example.com", password_hash="x")
        db.add(user)
        await db.commit()
        _, plaintext = await api_token_service.create_token(db, user.id, "t")
        touch = AsyncMock()
        monkeypatch.setattr(api_token_service, "_touch_last_used", touch)

        for _ in range(10):
            assert await api_token_service.verify_token(db, plaintext) is not None
        await asyncio.sleep(0)
        assert touch.call_count == 1

        # Ein frischer Wert in der DB unterdrückt das Schreiben auch in einem anderen Prozess.
        api_token_service._last_touch.clear()
        token = (await db.execute(select(ApiToken))).scalar_one()
        token.last_used_at = utcnow()
        await db.commit()
        assert await api_token_service.verify_token(db, plaintext) is not None
        await asyncio.sleep(0)
        assert touch.call_count == 1

        api_token_service._last_touch.clear()
        token.last_used_at = utcnow() - timedelta(minutes=5)
        await db.commit()
        assert await api_token_service.verify_token(db, plaintext) is not None
        await asyncio.sleep(0)
        assert touch.call_count == 2

    async def test_touch_is_a_single_update_without_select(self, db, clean_touch_memory):
        user = User(email="vr11-touch-sql@example.com", password_hash="x")
        db.add(user)
        await db.commit()
        token, _ = await api_token_service.create_token(db, user.id, "t")
        ts = utcnow().replace(microsecond=0)

        statements: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.split()[0].upper())

        event.listen(test_engine.sync_engine, "before_cursor_execute", _record)
        try:
            await api_token_service._touch_last_used(token.id, ts)
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", _record)
        assert statements == ["UPDATE"]

        await db.refresh(token)
        assert token.last_used_at == ts

    async def test_failed_write_may_be_retried_by_the_next_request(self, monkeypatch, clean_touch_memory):
        token_id, now = uuid.uuid4(), utcnow()
        assert api_token_service._should_touch(token_id, None, now) is True

        def _broken_session():
            raise RuntimeError("pool exhausted")

        monkeypatch.setattr(api_token_service, "async_session", _broken_session)
        await api_token_service._touch_last_used(token_id, now)  # darf nicht werfen
        assert api_token_service._should_touch(token_id, None, now) is True
