"""Regressionstests fuer Review-Fix-Batch F (Code-Review 2026-07-02).

Abgedeckt:
- H8:  GET /buckets/import-rules nicht mehr von /buckets/{bucket_id} geshadowt
- H7:  /market/macro-indicators laeuft ueber to_thread (Endpoint funktional)
- M3:  Double-Fill liefert 409 (intern + externer Twin), genau 1 Transaktion
- M15: Broken-Scores (price=None) werden nicht 24h gecacht (per-Ticker + Batch)
- M28: Report-Listen ohne body, Sortierung/Pagination unveraendert
- M29: Metrics-Label = route.path_format, Fallback-Normalisierung bounded
- LOW-analysis-ciphertext: PATCH watchlist gibt Klartext-Notiz zurueck
- LOW-auth-timing: forgot-password verschickt Mail im Background-Task
- LOW-auth-refresh-grace: Two-Tab-Replay im Grace-Window ohne Global-Revoke
- LOW-external-pagination: /screening/latest limit/offset additiv
- LOW-fee-summary-dup: nur noch EIN /performance/fee-summary-Handler
- LOW-raw-yf-info: ticker_info-Redis-Cache statt rohem yf.Ticker().info
"""

import asyncio
import uuid
from datetime import date

from httpx import AsyncClient

# pytest.ini: asyncio_mode = auto — Coroutine-Tests brauchen keinen Marker,
# und die synchronen Tests (Metrics-Normalisierung, Routen-Zaehlung) laufen
# als normale Funktionen.

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def api_auth(api_key: str) -> dict:
    return {"X-API-Key": api_key}


async def create_api_token(client, jwt, name="t", write=False) -> str:
    res = await client.post(
        "/api/settings/api-tokens",
        json={"name": name, "write_access": write},
        headers=auth(jwt),
    )
    assert res.status_code == 201, res.text
    return res.json()["token"]


def _patch_ticker_info(monkeypatch, calls: list | None = None):
    """yf_patch.yf_ticker_attr faken — kein Netz in Tests."""
    import yf_patch

    def _fake(ticker, attr):
        if calls is not None:
            calls.append(ticker)
        return {"shortName": "Test Corp", "longName": "Test Corporation", "currency": "USD"}

    monkeypatch.setattr(yf_patch, "yf_ticker_attr", _fake)


# --- H8: Route-Shadowing /buckets/import-rules ---


class TestImportRulesRouteOrder:
    async def test_import_rules_list_not_shadowed(self, client):
        jwt = (await register_and_login(client, "h8@test.local"))["access_token"]
        res = await client.get("/api/portfolio/buckets/import-rules", headers=auth(jwt))
        # Vor dem Fix: 422 uuid_parsing (input "import-rules")
        assert res.status_code == 200, res.text
        assert res.json() == {"rules": []}

    async def test_bucket_detail_still_matches_uuid(self, client):
        jwt = (await register_and_login(client, "h8b@test.local"))["access_token"]
        res = await client.get(f"/api/portfolio/buckets/{uuid.uuid4()}", headers=auth(jwt))
        assert res.status_code == 404


# --- H7: /market/macro-indicators via to_thread ---


class TestMacroIndicatorsOffLoop:
    async def test_endpoint_returns_gate(self, client, monkeypatch):
        jwt = (await register_and_login(client, "h7@test.local"))["access_token"]

        from services import macro_indicators_service, macro_gate_service

        async def _fake_indicators():
            return {"indicators": []}

        def _fake_gate(*a, **kw):
            return {"passed": True, "score": 9, "max_score": 9}

        monkeypatch.setattr(macro_indicators_service, "fetch_all_indicators", _fake_indicators)
        monkeypatch.setattr(macro_gate_service, "calculate_macro_gate", _fake_gate)

        res = await client.get("/api/market/macro-indicators", headers=auth(jwt))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["gate_passed"] is True
        assert body["gate"]["score"] == 9


# --- M3: Double-Fill -> 409 ---


def _order_payload(**overrides):
    base = {
        "ticker": "AAPL",
        "side": "buy",
        "shares": 10,
        "limit_price": 150.0,
        "currency": "USD",
        "expiry_type": "gtc",
    }
    base.update(overrides)
    return base


def _fill_payload():
    return {
        "price_per_share": 149.5,
        "fill_date": date.today().isoformat(),
        "fees_chf": 5.0,
        "fx_rate_to_chf": 0.88,
    }


class TestDoubleFill:
    async def test_second_internal_fill_conflicts(self, client, monkeypatch):
        _patch_ticker_info(monkeypatch)
        jwt = (await register_and_login(client, "m3a@test.local"))["access_token"]
        order = (await client.post(
            "/api/orders/pending", json=_order_payload(), headers=auth(jwt),
        )).json()

        first = await client.post(
            f"/api/orders/pending/{order['id']}/fill", json=_fill_payload(), headers=auth(jwt),
        )
        assert first.status_code == 200, first.text

        second = await client.post(
            f"/api/orders/pending/{order['id']}/fill", json=_fill_payload(), headers=auth(jwt),
        )
        assert second.status_code == 409

        # Genau EINE Transaktion gebucht
        txns = (await client.get("/api/transactions", headers=auth(jwt))).json()["items"]
        assert len([t for t in txns if t["ticker"] == "AAPL"]) == 1

    async def test_external_twin_conflicts_after_internal_fill(self, client, monkeypatch):
        _patch_ticker_info(monkeypatch)
        login = await register_and_login(client, "m3b@test.local")
        jwt = login["access_token"]
        key = await create_api_token(client, jwt, write=True)

        order = (await client.post(
            "/api/orders/pending", json=_order_payload(), headers=auth(jwt),
        )).json()

        first = await client.post(
            f"/api/v1/external/pending-orders/{order['id']}/fill",
            json=_fill_payload(),
            headers=api_auth(key),
        )
        assert first.status_code == 200, first.text

        second = await client.post(
            f"/api/v1/external/pending-orders/{order['id']}/fill",
            json=_fill_payload(),
            headers=api_auth(key),
        )
        assert second.status_code == 409

    async def test_external_fill_scoped_to_owner(self, client, monkeypatch):
        """Nach dem select()-Refactor bleibt das user_id-Scoping erhalten."""
        _patch_ticker_info(monkeypatch)
        jwt_a = (await register_and_login(client, "m3c-a@test.local"))["access_token"]
        jwt_b = (await register_and_login(client, "m3c-b@test.local"))["access_token"]
        key_b = await create_api_token(client, jwt_b, write=True)

        order = (await client.post(
            "/api/orders/pending", json=_order_payload(), headers=auth(jwt_a),
        )).json()

        res = await client.post(
            f"/api/v1/external/pending-orders/{order['id']}/fill",
            json=_fill_payload(),
            headers=api_auth(key_b),
        )
        assert res.status_code == 404


# --- M15: Broken-Scores nicht 24h pinnen ---


class TestSectorScoresBrokenCaching:
    async def _run(self, client, monkeypatch, etf: str, assess_fn):
        from services import cache
        from services.sector_analyzer import SECTOR_ETF_HOLDINGS
        from services import scoring_service

        holdings = [("TSTA", "Test A", 1.0), ("TSTB", "Test B", 1.0)]
        monkeypatch.setitem(SECTOR_ETF_HOLDINGS, etf, holdings)
        monkeypatch.setattr(scoring_service, "assess_ticker", assess_fn)

        # Saubere Ausgangslage (In-Memory-Cache ueberlebt Tests im Prozess)
        cache.delete(f"sector_scores:{etf}")
        for t, _, _ in holdings:
            cache.delete(f"setup_score:{t}")

        set_calls: list[tuple[str, int]] = []
        orig_set = cache.set

        def _recording_set(key, value, ttl=300):
            set_calls.append((key, ttl))
            return orig_set(key, value, ttl=ttl)

        monkeypatch.setattr(cache, "set", _recording_set)

        jwt = (await register_and_login(client, f"m15-{etf.lower()}@test.local"))["access_token"]
        res = await client.get(f"/api/market/sectors/{etf}/scores", headers=auth(jwt))
        assert res.status_code == 200, res.text
        return res.json(), dict(set_calls)

    async def test_broken_score_not_pinned(self, client, monkeypatch):
        def _broken(ticker, sector=None, **kw):
            return {"score": 2, "max_score": 18, "rating": "", "price": None}

        body, ttls = await self._run(client, monkeypatch, "XLTA", _broken)
        assert set(body.keys()) == {"TSTA", "TSTB"}
        # Broken: kein per-Ticker-Cache, Batch nur 60s
        assert "setup_score:TSTA" not in ttls
        assert "setup_score:TSTB" not in ttls
        assert ttls["sector_scores:XLTA"] == 60

    async def test_good_score_still_cached_24h(self, client, monkeypatch):
        def _good(ticker, sector=None, **kw):
            return {
                "score": 12, "max_score": 18, "rating": "gut", "price": 101.5,
                "mansfield_rs": 0.4, "signal": "SETUP", "gate_blocked": False,
            }

        body, ttls = await self._run(client, monkeypatch, "XLTB", _good)
        assert body["TSTA"]["score"] == 12
        assert ttls["setup_score:TSTA"] == 86400
        assert ttls["sector_scores:XLTB"] == 86400


# --- M28: Report-Listen ohne Body, Shape unveraendert ---


class TestReportListQueries:
    async def _seed_reports(self, client, jwt):
        key = await create_api_token(client, jwt, write=True)
        for i, rd in enumerate(["2026-05-20", "2026-05-22", None]):
            payload = {
                "category": "daily_brief" if i < 2 else "trade",
                "title": f"R{i}",
                "body": f"# R{i}\n\ncontent {i}",
                "source": "claude-finance",
                "source_path": f"f{i}.md",
            }
            if rd:
                payload["report_date"] = rd
            res = await client.post(
                "/api/v1/external/reports", json=payload, headers=api_auth(key),
            )
            assert res.status_code in (200, 201), res.text
        return key

    async def test_internal_list_sorted_no_body(self, client):
        jwt = (await register_and_login(client, "m28a@test.local"))["access_token"]
        await self._seed_reports(client, jwt)

        res = await client.get("/api/reports", headers=auth(jwt))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == 3
        # report_date desc, NULLs zuletzt
        assert [r["title"] for r in body["results"]] == ["R1", "R0", "R2"]
        # Listen-Repraesentation bleibt body-frei
        assert all("body" not in r for r in body["results"])
        assert set(body.keys()) == {
            "total", "page", "per_page", "categories", "all_tags", "results",
        }

    async def test_internal_list_sql_pagination(self, client):
        jwt = (await register_and_login(client, "m28b@test.local"))["access_token"]
        await self._seed_reports(client, jwt)

        res = await client.get("/api/reports?per_page=2&page=2", headers=auth(jwt))
        body = res.json()
        assert body["total"] == 3
        assert len(body["results"]) == 1
        assert body["results"][0]["title"] == "R2"

    async def test_external_list_filter_and_pagination(self, client):
        jwt = (await register_and_login(client, "m28c@test.local"))["access_token"]
        await self._seed_reports(client, jwt)
        read_key = await create_api_token(client, jwt, write=False)

        res = await client.get(
            "/api/v1/external/reports?category=daily_brief&per_page=1&page=2",
            headers=api_auth(read_key),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == 2
        assert len(body["results"]) == 1
        assert body["results"][0]["title"] == "R0"
        assert "body" not in body["results"][0]

    async def test_q_filter_still_searches_body(self, client):
        jwt = (await register_and_login(client, "m28d@test.local"))["access_token"]
        await self._seed_reports(client, jwt)

        res = await client.get("/api/reports", params={"q": "content 1"}, headers=auth(jwt))
        body = res.json()
        assert body["total"] == 1
        assert body["results"][0]["title"] == "R1"


# --- M29: Metrics-Label-Kardinalitaet ---


class TestMetricsLabels:
    def test_normalize_path_collapses_known_prefixes(self):
        from middleware.metrics import _normalize_path

        assert _normalize_path("/api/analysis/score/AAPL") == "/api/analysis/score/{ticker}"
        assert _normalize_path("/api/analysis/levels/CAT") == "/api/analysis/levels/{ticker}"
        assert _normalize_path("/api/market/fx/USD") == "/api/market/fx/{currency}"
        assert _normalize_path("/api/analysis/etf-sectors/EIMI.L") == "/api/analysis/etf-sectors/{ticker}"
        assert (
            _normalize_path("/api/market/industries/semiconductors/members")
            == "/api/market/industries/{slug}/members"
        )
        assert _normalize_path("/api/analysis/heartbeat/NVDA") == "/api/analysis/heartbeat/{ticker}"
        assert _normalize_path("/api/analysis/breakouts/MSFT") == "/api/analysis/breakouts/{ticker}"

    def test_normalize_path_keeps_literals_and_uuids(self):
        from middleware.metrics import _normalize_path

        uid = str(uuid.uuid4())
        assert (
            _normalize_path(f"/api/v1/external/positions/by-id/{uid}")
            == "/api/v1/external/positions/by-id/{id}"
        )
        assert _normalize_path("/api/orders/pending") == "/api/orders/pending"
        assert (
            _normalize_path("/api/portfolio/buckets/import-rules")
            == "/api/portfolio/buckets/import-rules"
        )

    async def test_matched_route_uses_path_format(self, client):
        jwt = (await register_and_login(client, "m29@test.local"))["access_token"]
        report_id = uuid.uuid4()
        res = await client.get(f"/api/reports/{report_id}", headers=auth(jwt))
        assert res.status_code == 404

        from middleware.metrics import REQUEST_COUNT

        endpoints = {
            s.labels.get("endpoint")
            for metric in REQUEST_COUNT.collect()
            for s in metric.samples
        }
        assert "/api/reports/{report_id}" in endpoints
        # Kein Roh-Pfad mit konkreter UUID als Label
        assert f"/api/reports/{report_id}" not in endpoints


# --- LOW: PATCH watchlist gibt Klartext zurueck ---


class TestWatchlistNotesPlaintext:
    async def test_patch_returns_plaintext(self, client):
        jwt = (await register_and_login(client, "wl@test.local"))["access_token"]
        item = (await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "NVDA", "name": "NVIDIA"},
            headers=auth(jwt),
        )).json()

        res = await client.patch(
            f"/api/analysis/watchlist/{item['id']}",
            json={"notes": "Geheime Notiz äöü"},
            headers=auth(jwt),
        )
        assert res.status_code == 200, res.text
        # Vor dem Fix kam hier der Fernet-Ciphertext zurueck
        assert res.json()["notes"] == "Geheime Notiz äöü"

    async def test_patch_without_notes_returns_decrypted(self, client):
        jwt = (await register_and_login(client, "wl2@test.local"))["access_token"]
        item = (await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "AMD", "name": "AMD"},
            headers=auth(jwt),
        )).json()
        await client.patch(
            f"/api/analysis/watchlist/{item['id']}",
            json={"notes": "bestehende Notiz"},
            headers=auth(jwt),
        )

        res = await client.patch(
            f"/api/analysis/watchlist/{item['id']}", json={}, headers=auth(jwt),
        )
        assert res.status_code == 200
        assert res.json()["notes"] == "bestehende Notiz"


# --- LOW: forgot-password im Background-Task ---


class TestForgotPasswordBackground:
    async def test_email_sent_in_background(self, client, monkeypatch):
        await register_and_login(client, "fp@test.local")

        from services import email_service

        sent = asyncio.Event()
        recipients: list[str] = []

        async def _fake_send(to, subject, html, smtp_cfg=None):
            recipients.append(to)
            sent.set()
            return True

        monkeypatch.setattr(email_service, "has_smtp_configured", lambda: True)
        monkeypatch.setattr(email_service, "send_email", _fake_send)

        res = await client.post("/api/auth/forgot-password", json={"email": "fp@test.local"})
        assert res.status_code == 200
        msg_known = res.json()["message"]

        # Mail kommt asynchron aus dem Background-Task
        await asyncio.wait_for(sent.wait(), timeout=2)
        assert recipients == ["fp@test.local"]

        # Unbekannte E-Mail: identische Response (Enumeration-Schutz)
        res2 = await client.post(
            "/api/auth/forgot-password", json={"email": "unknown@test.local"},
        )
        assert res2.status_code == 200
        assert res2.json()["message"] == msg_known


# --- LOW: Refresh-Grace-Window (Two-Tab-Race) ---


class TestRefreshGraceWindow:
    async def test_replay_within_grace_no_global_revoke(self, client):
        login = await register_and_login(client, "grace@test.local")
        rt0 = login["refresh_token"]

        rotated = await client.post("/api/auth/refresh", json={"refresh_token": rt0})
        assert rotated.status_code == 200
        rt1 = rotated.json()["refresh_token"]

        # Zweiter Tab spielt rt0 direkt nochmal ein: 401, aber KEIN Global-Revoke
        replay = await client.post("/api/auth/refresh", json={"refresh_token": rt0})
        assert replay.status_code == 401

        still_valid = await client.post("/api/auth/refresh", json={"refresh_token": rt1})
        assert still_valid.status_code == 200, still_valid.text

    async def test_replay_after_grace_revokes_all(self, client):
        from services import cache
        from services.auth_service import hash_refresh_token

        login = await register_and_login(client, "grace2@test.local")
        rt0 = login["refresh_token"]

        rotated = await client.post("/api/auth/refresh", json={"refresh_token": rt0})
        assert rotated.status_code == 200
        rt1 = rotated.json()["refresh_token"]

        # Grace-Marker abgelaufen simulieren
        cache.delete(f"refresh_rotation_grace:{hash_refresh_token(rt0)}")

        replay = await client.post("/api/auth/refresh", json={"refresh_token": rt0})
        assert replay.status_code == 401
        assert "kompromittiert" in replay.json()["detail"]

        # Global-Revoke: auch der rotierte Token ist tot
        revoked = await client.post("/api/auth/refresh", json={"refresh_token": rt1})
        assert revoked.status_code == 401


# --- LOW: /screening/latest optionale Pagination ---


class TestScreeningLatestPagination:
    async def _seed(self, db):
        from models.screening import ScreeningResult, ScreeningScan

        scan = ScreeningScan(status="completed", steps=[], result_count=3)
        db.add(scan)
        await db.flush()
        for ticker, score in (("AAA", 5), ("BBB", 3), ("CCC", 2)):
            db.add(ScreeningResult(
                scan_id=scan.id, ticker=ticker, name=ticker, score=score,
                score_display=score, signals={},
            ))
        await db.commit()

    async def test_default_returns_all(self, client, db):
        jwt = (await register_and_login(client, "scr1@test.local"))["access_token"]
        key = await create_api_token(client, jwt)
        await self._seed(db)

        res = await client.get("/api/v1/external/screening/latest", headers=api_auth(key))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == 3
        assert [r["ticker"] for r in body["results"]] == ["AAA", "BBB", "CCC"]

    async def test_limit_offset_slice_total_stays_full(self, client, db):
        jwt = (await register_and_login(client, "scr2@test.local"))["access_token"]
        key = await create_api_token(client, jwt)
        await self._seed(db)

        res = await client.get(
            "/api/v1/external/screening/latest?limit=2&offset=1", headers=api_auth(key),
        )
        body = res.json()
        assert body["total"] == 3
        assert [r["ticker"] for r in body["results"]] == ["BBB", "CCC"]


# --- LOW: fee-summary nur einmal registriert ---


class TestFeeSummarySingleRoute:
    def test_only_one_handler_registered(self):
        from main import app

        paths = [
            getattr(r, "path", None)
            for r in app.routes
            if getattr(r, "path", None) == "/api/v1/external/performance/fee-summary"
        ]
        assert len(paths) == 1

    async def test_endpoint_still_works(self, client):
        jwt = (await register_and_login(client, "fee@test.local"))["access_token"]
        key = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/performance/fee-summary", headers=api_auth(key),
        )
        assert res.status_code == 200, res.text


# --- LOW: ticker_info-Cache statt rohem yf.Ticker().info ---


class TestTickerInfoCache:
    async def test_second_lookup_served_from_cache(self, client, monkeypatch):
        from api.transactions import get_ticker_info_cached
        from services import cache

        cache.delete("ticker_info:TSTCACHE")
        calls: list[str] = []
        _patch_ticker_info(monkeypatch, calls)

        info1 = await get_ticker_info_cached("TSTCACHE")
        info2 = await get_ticker_info_cached("TSTCACHE")
        assert info1["shortName"] == "Test Corp"
        assert info1["currency"] == "USD"
        assert info2 == info1
        assert calls == ["TSTCACHE"]  # zweiter Aufruf aus dem Cache

    async def test_empty_lookup_not_cached(self, client, monkeypatch):
        from api.transactions import get_ticker_info_cached
        from services import cache
        import yf_patch

        cache.delete("ticker_info:TSTEMPTY")
        calls: list[str] = []

        def _empty(ticker, attr):
            calls.append(ticker)
            return {}

        monkeypatch.setattr(yf_patch, "yf_ticker_attr", _empty)

        await get_ticker_info_cached("TSTEMPTY")
        await get_ticker_info_cached("TSTEMPTY")
        assert calls == ["TSTEMPTY", "TSTEMPTY"]  # leere Lookups nicht gepinnt
