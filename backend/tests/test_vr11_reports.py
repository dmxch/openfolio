"""Vollreview 11/2026, Report-Vault: PDF-Export und Suche.

K027 (PDF-Rendering ohne Zeit-, Speicher- und Parallelitätsgrenze),
K031 (Fremdbilder mit beliebigem Format an Pillow),
K028 (Volltextsuche ohne Zeitgrenze), K122 (Datumsfilter als String),
X35 (LIKE-Platzhalter in der Suche).
"""

import asyncio
import base64
import io
import sys
import time
import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request as StarletteRequest

import api.reports as reports_api
import services.report_pdf_service as svc
from constants.limits import RL_HEAVY, RL_WRITE

TEST_PASSWORD = "TestPassw0rd!2026"

SAMPLE_MD = """# Weekly Check 2026-07-05

Portfolio bei **CHF 442'419** (Woche +1.1%).

| Ticker | Perf |
|--------|------|
| CHSPI  | +13.5% |
| PEP    | -12.6% |

```
[FINANCE TIME CONTEXT]
```
"""


def _nested_flex(depth: int) -> str:
    return '<div style="display:flex">' * depth + "x" + "</div>" * depth


def _table(n_chars: int) -> str:
    head = "| A | B | C |\n|---|---|---|\n"
    row = "| x1 | y2 | z3 |\n"
    return head + row * ((n_chars - len(head)) // len(row))


def _image_bytes(fmt: str) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


def _data_uri(payload: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


def _render_kwargs(body_md: str = SAMPLE_MD) -> dict:
    return {
        "title": "Weekly Check 2026-07-05",
        "category": "weekly_check",
        "report_date": date(2026, 7, 5),
        "source": "claude-finance",
        "body_md": body_md,
    }


async def _login(client: AsyncClient, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _write_key(client: AsyncClient, headers: dict) -> dict:
    res = await client.post(
        "/api/settings/api-tokens",
        json={"name": "t", "write_access": True, "current_password": TEST_PASSWORD},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return {"X-API-Key": res.json()["token"]}


async def _upload(client: AsyncClient, key: dict, **over) -> str:
    payload = {
        "category": "daily_brief",
        "title": "Daily Brief",
        "report_date": "2026-05-25",
        "body": "# Brief\n\nText.",
        "source": "claude-finance",
        "source_path": f"Output/{uuid.uuid4()}.md",
    }
    payload.update(over)
    res = await client.post("/api/v1/external/reports", json=payload, headers=key)
    assert res.status_code == 201, res.text
    return res.json()["id"]


# --- K027: rohes HTML und style-Attribute erreichen den Renderer nicht ---


class TestBodyIsNotHtml:
    def test_raw_html_is_escaped(self):
        html = svc._render_html(**_render_kwargs(
            _nested_flex(3) + "\n\nText <span style=\"display:flex\">inline</span>\n\n"
            "<style>p { display: flex }</style>\n\n<img src=\"data:image/x-xbitmap;base64,AAAA\">\n"
        ))
        body = html.split('<div class="body">', 1)[1]
        assert "<div style" not in body
        assert "<span" not in body
        assert "<style" not in body
        assert "<img" not in body
        assert "&lt;div style=" in body  # sichtbar als Text, wie im Viewer

    def test_attr_list_cannot_set_style(self):
        html = svc._render_html(**_render_kwargs(
            'Absatz\n{: style="display:flex" }\n\n## Titel {: style="display:flex" }\n'
        ))
        body = html.split('<div class="body">', 1)[1]
        assert "style=" not in body.split("</div>")[0].replace("{: style=", "")

    def test_markdown_features_survive(self):
        html = svc._render_html(**_render_kwargs(
            SAMPLE_MD + "\n<https://example.com/x>\n\nBegriff\n:   Erklärung\n\n> Zitat mit a < b\n"
        ))
        assert "<table>" in html
        assert "<pre><code>" in html
        assert '<a href="https://example.com/x">' in html
        assert "<dt>Begriff</dt>" in html
        assert "<blockquote>" in html


# --- K027: Rendering im Kindprozess mit Grenzen ---


class TestIsolatedRendering:
    async def test_normal_report_renders(self):
        pdf = await svc.render_report_pdf_isolated(user_id=uuid.uuid4(), **_render_kwargs())
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 2000

    async def test_nested_flex_body_is_harmless(self):
        """Tiefe 20 rechnete vor dem Fix hochgerechnet Stunden (Faktor 2,9 je Ebene)."""
        started = time.monotonic()
        pdf = await svc.render_report_pdf_isolated(
            user_id=uuid.uuid4(), **_render_kwargs(_nested_flex(20)), cpu_seconds=10,
        )
        assert pdf[:5] == b"%PDF-"
        assert time.monotonic() - started < 15

    async def test_flex_document_stops_at_cpu_limit(self, monkeypatch):
        """Die Grenze selbst, am Escaping vorbei: das Kind setzt dieselben Grenzen
        wie ``_child_main``, rendert aber fertiges Flex-HTML. Ohne RLIMIT_CPU
        rechnet Tiefe 14 rund eine halbe Stunde (0,8 s bei Tiefe 6, Faktor 2,9
        je Ebene); mit Grenze endet der Lauf als Fehler statt zu hängen."""
        code = (
            "import sys\n"
            "from services.report_pdf_service import _apply_child_limits, _html_to_pdf\n"
            "_apply_child_limits(int(sys.argv[1]), int(sys.argv[2]))\n"
            "sys.stdin.buffer.read()\n"
            f"sys.stdout.buffer.write(_html_to_pdf({'<html><body>' + _nested_flex(14) + '</body></html>'!r}))\n"
        )
        real_exec = asyncio.create_subprocess_exec
        spawned = []

        async def _flex_child(*args, **kwargs):
            # args: Interpreter, "-m", Modul, CPU-Grenze, Speichergrenze
            proc = await real_exec(sys.executable, "-c", code, *args[3:], **kwargs)
            spawned.append(proc)
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _flex_child)
        started = time.monotonic()
        with pytest.raises(svc.ReportPdfLimitError):
            await svc.render_report_pdf_isolated(
                user_id=uuid.uuid4(), **_render_kwargs(), cpu_seconds=2,
            )
        assert time.monotonic() - started < 20
        assert spawned[0].returncode < 0  # vom Kernel beendet, nicht von der Wanduhr

    async def test_cpu_limit_raises_limit_error(self):
        """Die Markdown-Tabelle in Maximalgrösse braucht ohne Grenze 71 s und 2,7 GB."""
        started = time.monotonic()
        with pytest.raises(svc.ReportPdfLimitError):
            await svc.render_report_pdf_isolated(
                user_id=uuid.uuid4(), **_render_kwargs(_table(200_000)), cpu_seconds=2,
            )
        assert time.monotonic() - started < 20

    async def test_memory_limit_raises_limit_error(self):
        with pytest.raises(svc.ReportPdfLimitError):
            await svc.render_report_pdf_isolated(
                user_id=uuid.uuid4(), **_render_kwargs(_table(50_000)),
                memory_bytes=230 * 1024 ** 2,
            )

    async def test_wall_clock_limit_kills_the_child(self, monkeypatch):
        """Ein Kind, das nicht rechnet, trifft die CPU-Grenze nie."""
        spawned = []
        real_exec = asyncio.create_subprocess_exec

        async def _sleeping_child(*_args, **kwargs):
            proc = await real_exec(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
            spawned.append(proc)
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _sleeping_child)
        with pytest.raises(svc.ReportPdfLimitError):
            await svc.render_report_pdf_isolated(
                user_id=uuid.uuid4(), **_render_kwargs(), wall_seconds=0.5,
            )
        assert spawned[0].returncode is not None  # beendet und abgeholt

    async def test_renderer_crash_is_a_plain_error(self, monkeypatch):
        real_exec = asyncio.create_subprocess_exec

        async def _failing_child(*_args, **kwargs):
            return await real_exec(
                sys.executable, "-c", "import sys; sys.exit('boom')", **kwargs,
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _failing_child)
        with pytest.raises(svc.ReportPdfError) as excinfo:
            await svc.render_report_pdf_isolated(user_id=uuid.uuid4(), **_render_kwargs())
        assert not isinstance(excinfo.value, svc.ReportPdfLimitError)
        assert "boom" in str(excinfo.value)

    def test_child_gets_no_secrets(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "s" * 40)
        monkeypatch.setenv("ENCRYPTION_KEY", "k" * 40)
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:geheim@db/x")
        monkeypatch.setenv("REDIS_URL", "redis://:geheim@redis:6379/0")
        monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/.cache")
        env = svc._child_env()
        assert env["XDG_CACHE_HOME"] == "/tmp/.cache"  # Fontconfig braucht den Cache
        assert not {"JWT_SECRET", "ENCRYPTION_KEY", "DATABASE_URL", "REDIS_URL"} & set(env)


class TestParallelism:
    @pytest.fixture
    def blocked_renderer(self, monkeypatch):
        """Ersetzt den Kindprozess durch eine Coroutine, die auf ein Signal wartet."""
        release = asyncio.Event()
        started = asyncio.Event()

        async def _fake(payload, **_limits):
            started.set()
            await release.wait()
            return b"%PDF-fake"

        monkeypatch.setattr(svc, "_render_in_subprocess", _fake)
        return started, release

    async def test_one_render_per_user(self, blocked_renderer):
        started, release = blocked_renderer
        user = uuid.uuid4()
        first = asyncio.create_task(svc.render_report_pdf_isolated(user_id=user, **_render_kwargs()))
        await started.wait()

        with pytest.raises(svc.ReportPdfBusyError) as excinfo:
            await svc.render_report_pdf_isolated(user_id=user, **_render_kwargs())
        assert excinfo.value.per_user is True

        release.set()
        assert await first == b"%PDF-fake"
        # Lock und Platz sind wieder frei.
        assert await svc.render_report_pdf_isolated(user_id=user, **_render_kwargs()) == b"%PDF-fake"
        assert svc._active_renders == 0

    async def test_other_user_waits_then_gets_busy(self, blocked_renderer):
        started, release = blocked_renderer
        first = asyncio.create_task(
            svc.render_report_pdf_isolated(user_id=uuid.uuid4(), **_render_kwargs())
        )
        await started.wait()
        assert svc._active_renders == svc.MAX_PARALLEL_RENDERS

        other = uuid.uuid4()
        with pytest.raises(svc.ReportPdfBusyError) as excinfo:
            await svc.render_report_pdf_isolated(
                user_id=other, **_render_kwargs(), slot_wait_seconds=0.3,
            )
        assert excinfo.value.per_user is False

        # Wird der Platz innert der Wartezeit frei, rendert der zweite Nutzer.
        waiting = asyncio.create_task(
            svc.render_report_pdf_isolated(user_id=other, **_render_kwargs(), slot_wait_seconds=5)
        )
        await asyncio.sleep(0.2)
        assert not waiting.done()
        release.set()
        assert await first == b"%PDF-fake"
        assert await waiting == b"%PDF-fake"
        assert svc._active_renders == 0

    async def test_failure_releases_lock_and_slot(self, monkeypatch):
        async def _boom(payload, **_limits):
            raise svc.ReportPdfLimitError("cpu")

        user = uuid.uuid4()
        monkeypatch.setattr(svc, "_render_in_subprocess", _boom)
        for _ in range(2):  # der zweite Lauf scheitert gleich, nicht am Lock
            with pytest.raises(svc.ReportPdfLimitError):
                await svc.render_report_pdf_isolated(user_id=user, **_render_kwargs())
        assert svc._active_renders == 0


# --- K027: Route ---


class TestExportRoute:
    async def test_pdf_export_end_to_end(self, client):
        headers = await _login(client, "pdf1@test.local")
        rid = await _upload(client, await _write_key(client, headers), body=SAMPLE_MD)

        res = await client.get(f"/api/reports/{rid}/export?format=pdf", headers=headers)
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "application/pdf"
        assert res.headers["content-disposition"].endswith('.pdf"')
        assert res.content[:5] == b"%PDF-"

    async def test_render_runs_under_the_requesting_user(self, client, monkeypatch):
        seen = {}

        async def _fake(**kwargs):
            seen.update(kwargs)
            return b"%PDF-fake"

        monkeypatch.setattr(svc, "render_report_pdf_isolated", _fake)
        headers = await _login(client, "pdf2@test.local")
        rid = await _upload(client, await _write_key(client, headers), body="Inhalt")
        me = (await client.get("/api/auth/me", headers=headers)).json()

        res = await client.get(f"/api/reports/{rid}/export?format=pdf", headers=headers)
        assert res.status_code == 200
        assert str(seen["user_id"]) == me["id"]
        assert seen["body_md"] == "Inhalt"

        # Fremder Report: 404, bevor irgendetwas rendert.
        seen.clear()
        other = await _login(client, "pdf3@test.local")
        res = await client.get(f"/api/reports/{rid}/export?format=pdf", headers=other)
        assert res.status_code == 404
        assert seen == {}

    @pytest.mark.parametrize(
        ("error", "status", "fragment"),
        [
            (svc.ReportPdfLimitError("cpu"), 422, "zu gross oder zu komplex für den PDF-Export"),
            (svc.ReportPdfBusyError(per_user=True), 429, "Es läuft bereits ein PDF-Export"),
            (svc.ReportPdfBusyError(per_user=False), 503, "gerade ausgelastet"),
            (svc.ReportPdfError("exit code 1"), 500, "PDF-Erzeugung fehlgeschlagen"),
        ],
    )
    async def test_renderer_errors_map_to_status(self, client, monkeypatch, error, status, fragment):
        async def _fail(**_kwargs):
            raise error

        monkeypatch.setattr(svc, "render_report_pdf_isolated", _fail)
        headers = await _login(client, "pdf4@test.local")
        rid = await _upload(client, await _write_key(client, headers))

        res = await client.get(f"/api/reports/{rid}/export?format=pdf", headers=headers)
        assert res.status_code == status
        assert fragment in res.json()["detail"]
        if status == 503:
            assert res.headers["retry-after"] == "10"
        # Der Markdown-Download hängt nicht am Renderer.
        md = await client.get(f"/api/reports/{rid}/export", headers=headers)
        assert md.status_code == 200


def _query_request(query: str) -> StarletteRequest:
    return StarletteRequest({
        "type": "http", "method": "GET", "path": "/api/reports/x/export",
        "query_string": query.encode(), "headers": [], "client": ("10.0.0.9", 1234),
    })


class TestExportRateLimit:
    def test_pdf_carries_heavy_limit_markdown_does_not(self):
        from limits import parse

        from api.auth import limiter

        route_limits = limiter._route_limits["api.reports.export_report"]
        heavy = [lim for lim in route_limits if lim.limit == parse(RL_HEAVY)]
        general = [lim for lim in route_limits if lim.limit == parse(RL_WRITE)]
        assert len(heavy) == 1 and len(general) == 1
        assert heavy[0].is_exempt(_query_request("format=pdf")) is False
        assert heavy[0].is_exempt(_query_request("format=md")) is True
        assert heavy[0].is_exempt(_query_request("")) is True
        assert general[0].is_exempt(_query_request("format=pdf")) is False

    async def test_sixth_pdf_export_is_limited(self, client, monkeypatch):
        """Die echte App mit eingeschaltetem Limiter, Zähler im Speicher."""
        from limits import parse
        from limits.storage import MemoryStorage
        from limits.strategies import FixedWindowRateLimiter

        from api.auth import limiter

        async def _fake(**_kwargs):
            return b"%PDF-fake"

        monkeypatch.setattr(svc, "render_report_pdf_isolated", _fake)
        headers = await _login(client, "pdf5@test.local")
        rid = await _upload(client, await _write_key(client, headers))

        storage = MemoryStorage()
        monkeypatch.setattr(limiter, "_storage", storage)
        monkeypatch.setattr(limiter, "_limiter", FixedWindowRateLimiter(storage))
        monkeypatch.setattr(limiter, "_storage_dead", False)
        monkeypatch.setattr(limiter, "enabled", True)

        # Der Limiter zählt je Kalenderminute: nicht über die Grenze hinweg zählen.
        if time.time() % 60 > 57:
            await asyncio.sleep(3.5)
        amount = parse(RL_HEAVY).amount
        codes = [
            (await client.get(f"/api/reports/{rid}/export?format=pdf", headers=headers)).status_code
            for _ in range(amount + 1)
        ]
        assert codes == [200] * amount + [429]
        md = await client.get(f"/api/reports/{rid}/export", headers=headers)
        assert md.status_code == 200


# --- K031: nur eingebettete PNG- und JPEG-Bilder ---


class TestInlineImageFetcher:
    @pytest.mark.parametrize(("fmt", "mime"), [("PNG", "image/png"), ("JPEG", "image/jpeg")])
    def test_png_and_jpeg_pass(self, fmt, mime):
        payload = _image_bytes(fmt)
        # Der deklarierte Typ kommt aus dem Report-Body und zählt nicht.
        response = svc._inline_image_fetcher().fetch(_data_uri(payload, "image/svg+xml"))
        assert response.read() == payload
        assert response.content_type == mime

    @pytest.mark.parametrize("fmt", ["GIF", "TIFF", "BMP", "PPM"])
    def test_other_raster_formats_are_rejected(self, fmt):
        with pytest.raises(ValueError):
            svc._inline_image_fetcher().fetch(_data_uri(_image_bytes(fmt)))

    @pytest.mark.parametrize(
        "payload",
        [
            b"#define im_width 8\n#define im_height 1\nstatic char im_bits[] = { 0x00 };",  # XBM
            b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>',
            b"\x00\x00\x00\x0cjP  \r\n\x87\n",  # JPEG 2000
            b"",
        ],
    )
    def test_non_image_payloads_are_rejected(self, payload):
        with pytest.raises(ValueError):
            svc._inline_image_fetcher().fetch(_data_uri(payload))

    @pytest.mark.parametrize("url", ["http://127.0.0.1:1/x.png", "file:///etc/hostname"])
    def test_other_protocols_stay_blocked(self, url):
        with pytest.raises(ValueError):
            svc._inline_image_fetcher().fetch(url)

    def test_only_png_and_jpeg_reach_pillow(self, monkeypatch):
        """Durch den ganzen Renderer: WeasyPrint öffnet jedes geholte Bild mit
        ``Image.open`` ohne Formatliste. Gezählt wird, was dort ankommt."""
        import PIL.Image

        opened = []
        real_open = PIL.Image.open

        def _spy(fp, *args, **kwargs):
            image = real_open(fp, *args, **kwargs)
            opened.append(image.format)
            return image

        monkeypatch.setattr(PIL.Image, "open", _spy)
        body = "\n\n".join(
            f"![bild]({_data_uri(_image_bytes(fmt))})" for fmt in ("PNG", "GIF", "TIFF", "JPEG", "BMP")
        )
        pdf = svc.render_report_pdf(**_render_kwargs(body))
        assert pdf[:5] == b"%PDF-"  # ein geblocktes Bild killt den Export nicht
        assert set(opened) == {"JPEG", "PNG"}  # PNG öffnet WeasyPrint zweimal


# --- X35: LIKE-Platzhalter ---


class TestSearch:
    async def _seed(self, client) -> dict:
        headers = await _login(client, "such@test.local")
        key = await _write_key(client, headers)
        await _upload(client, key, title="Prozent", body="Rendite 100% sicher")
        await _upload(client, key, title="Punkte", body="Rendite 100 Punkte")
        await _upload(client, key, title="Regel", body="der stop_loss greift")
        await _upload(client, key, title="Tippfehler", body="der stopXloss greift")
        await _upload(client, key, title="Pfad C:\\temp", body="ohne Sonderzeichen")
        return headers

    async def _titles(self, client, headers, q: str) -> set[str]:
        res = await client.get("/api/reports", params={"q": q}, headers=headers)
        assert res.status_code == 200, res.text
        return {r["title"] for r in res.json()["results"]}

    async def test_percent_and_underscore_are_literal(self, client):
        headers = await self._seed(client)
        assert await self._titles(client, headers, "100%") == {"Prozent"}
        assert await self._titles(client, headers, "stop_loss") == {"Regel"}
        assert await self._titles(client, headers, "_") == {"Regel"}
        assert await self._titles(client, headers, "%") == {"Prozent"}
        assert await self._titles(client, headers, "C:\\temp") == {"Pfad C:\\temp"}
        # Gross- und Kleinschreibung bleibt egal, Teilwort bleibt Teilwort.
        assert await self._titles(client, headers, "RENDITE") == {"Prozent", "Punkte"}

    # --- K028: Länge und Zeitgrenze ---

    async def test_query_is_capped_at_64_chars(self, client):
        headers = await self._seed(client)
        ok = await client.get("/api/reports", params={"q": "a" * 64}, headers=headers)
        assert ok.status_code == 200
        too_long = await client.get("/api/reports", params={"q": "a" * 65}, headers=headers)
        assert too_long.status_code == 422

    async def test_time_limit_is_set_before_the_list_queries(self, client, monkeypatch):
        """Beide Zweige (mit und ohne Tag-Filter) laufen unter der Zeitgrenze."""
        calls = []

        async def _spy(db):
            calls.append(db)

        monkeypatch.setattr(reports_api, "_limit_search_time", _spy)
        headers = await self._seed(client)
        assert (await client.get("/api/reports?q=Rendite", headers=headers)).status_code == 200
        assert len(calls) == 1
        assert (await client.get("/api/reports?q=Rendite&tag=x", headers=headers)).status_code == 200
        assert len(calls) == 2

    async def test_statement_timeout_becomes_503(self, client, monkeypatch):
        headers = await self._seed(client)
        real_scalar = AsyncSession.scalar

        async def _canceled(self, statement, *args, **kwargs):
            if "count(" in str(statement).lower() and "reports" in str(statement).lower():
                orig = Exception("canceling statement due to statement timeout")
                orig.sqlstate = "57014"
                raise DBAPIError("SELECT count(*) FROM reports", {}, orig)
            return await real_scalar(self, statement, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "scalar", _canceled)
        res = await client.get("/api/reports", params={"q": "Rendite"}, headers=headers)
        assert res.status_code == 503
        assert "Die Abfrage hat zu lange gedauert" in res.json()["detail"]

        monkeypatch.setattr(AsyncSession, "scalar", real_scalar)
        res = await client.get("/api/reports", params={"q": "Rendite"}, headers=headers)
        assert res.status_code == 200 and res.json()["total"] == 2


class _FakeBind:
    def __init__(self, dialect: str) -> None:
        self.dialect = type("D", (), {"name": dialect})()


class _FakeSession:
    def __init__(self, dialect: str) -> None:
        self._bind = _FakeBind(dialect)
        self.statements: list[str] = []

    def get_bind(self):
        return self._bind

    async def execute(self, statement):
        self.statements.append(str(statement))


class TestSearchTimeLimit:
    async def test_sqlite_gets_no_set_local(self):
        db = _FakeSession("sqlite")
        await reports_api._limit_search_time(db)
        assert db.statements == []

    @pytest.mark.parametrize(
        ("global_ms", "expected_ms"),
        [(0, 3000), (15000, 3000), (1000, 1000)],
    )
    async def test_postgres_gets_set_local(self, monkeypatch, global_ms, expected_ms):
        """Ein strengeres DB_STATEMENT_TIMEOUT_MS des Betreibers bleibt bestehen."""
        monkeypatch.setattr(reports_api.settings, "db_statement_timeout_ms", global_ms)
        db = _FakeSession("postgresql")
        await reports_api._limit_search_time(db)
        assert db.statements == [f"SET LOCAL statement_timeout = {expected_ms}"]

    def test_only_sqlstate_57014_counts_as_timeout(self):
        canceled = Exception("canceling statement due to statement timeout")
        canceled.sqlstate = "57014"
        other = Exception("operator does not exist")
        other.sqlstate = "42883"
        assert reports_api._is_statement_timeout(DBAPIError("s", {}, canceled)) is True
        assert reports_api._is_statement_timeout(DBAPIError("s", {}, other)) is False
        assert reports_api._is_statement_timeout(DBAPIError("s", {}, Exception("x"))) is False


# --- K122: Datumsfilter ---


class TestDateFilter:
    async def test_date_from_and_date_to(self, client):
        headers = await _login(client, "datum@test.local")
        key = await _write_key(client, headers)
        for day in range(20, 25):
            await _upload(client, key, title=f"R{day}", report_date=f"2026-05-{day}")

        async def titles(**params) -> set[str]:
            res = await client.get("/api/reports", params=params, headers=headers)
            assert res.status_code == 200, res.text
            return {r["title"] for r in res.json()["results"]}

        assert await titles(date_from="2026-05-23") == {"R23", "R24"}
        assert await titles(date_to="2026-05-21") == {"R20", "R21"}
        assert await titles(date_from="2026-05-21", date_to="2026-05-22") == {"R21", "R22"}

    async def test_bound_values_are_dates(self, client, monkeypatch):
        """Postgres kennt kein ``date >= varchar``; SQLite vergleicht beides.
        Geprüft wird deshalb der gebundene Wert selbst."""
        bound = []
        real_scalar = AsyncSession.scalar

        async def _spy(self, statement, *args, **kwargs):
            bound.extend(statement.compile().params.values())
            return await real_scalar(self, statement, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "scalar", _spy)
        headers = await _login(client, "datum2@test.local")
        res = await client.get(
            "/api/reports", params={"date_from": "2026-01-01", "date_to": "2026-12-31"}, headers=headers,
        )
        assert res.status_code == 200
        assert date(2026, 1, 1) in bound and date(2026, 12, 31) in bound
        assert "2026-01-01" not in bound

    @pytest.mark.parametrize("value", ["gestern", "2026-13-01", "01.05.2026", "2026-05-01' OR 1=1"])
    async def test_invalid_date_is_rejected(self, client, value):
        headers = await _login(client, "datum3@test.local")
        for name in ("date_from", "date_to"):
            res = await client.get("/api/reports", params={name: value}, headers=headers)
            assert res.status_code == 422, (name, value)
