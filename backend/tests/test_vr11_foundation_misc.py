"""Vollreview 11/2026, Fundament: Konstanten, Config, DB-Engine, Logging, bcrypt.

K096/X39 (API-Keys im Log), K163/K154 (SQL-Parameter in Fehlertexten),
K140 (statement_timeout als Opt-in), K002 (bcrypt im Event-Loop).
"""

import asyncio
import importlib.util
import json
import logging
import sys
import threading
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


class TestLimitConstants:
    def test_resource_limits(self):
        from constants import limits

        assert limits.MAX_IMPORT_ROWS == 20_000
        assert limits.MAX_IMPORT_FX_CURRENCIES == 10
        assert limits.MAX_PRICE_ALERTS_PER_USER == 500
        assert limits.MAX_REPORT_TOTAL_BYTES_PER_USER == 50 * 1024 * 1024
        assert limits.MAX_REGEN_SPAN_DAYS == 25_000
        # Bestehende Konstanten bleiben.
        assert limits.MAX_POSITIONS_PER_USER == 500
        assert limits.MAX_BULK_DELETE_TRANSACTIONS == 500

    def test_rate_limit_strings_parse(self):
        from limits import parse_many

        from constants import limits

        expected = {
            "RL_DEFAULT": "240/minute",
            "RL_READ": "120/minute",
            "RL_TICKER_READ": "300/minute",
            "RL_WRITE": "30/minute",
            "RL_HEAVY": "5/minute",
            "RL_REFRESH": "2/minute",
            "RL_SEARCH": "60/minute",
        }
        for name, value in expected.items():
            assert getattr(limits, name) == value
            assert len(parse_many(value)) == 1


class TestSettings:
    def test_defaults_keep_current_behaviour(self):
        from config import Settings

        fields = Settings.model_fields
        assert fields["trusted_proxy_hops"].default == 1
        assert fields["db_statement_timeout_ms"].default == 0
        assert fields["fmp_system_api_key"].default == ""
        assert fields["fred_system_api_key"].default == ""
        assert fields["finnhub_system_api_key"].default == ""

    def test_values_come_from_the_environment(self, monkeypatch):
        from config import Settings

        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
        monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "15000")
        monkeypatch.setenv("FMP_SYSTEM_API_KEY", "fmp-key")
        monkeypatch.setenv("FRED_SYSTEM_API_KEY", "fred-key")
        s = Settings(_env_file=None)
        assert s.trusted_proxy_hops == 2
        assert s.db_statement_timeout_ms == 15000
        assert s.fmp_system_api_key == "fmp-key"
        assert s.fred_system_api_key == "fred-key"


def _load_real_db_module(monkeypatch, timeout_ms: int = 0):
    """Die echte db.py laden — conftest ersetzt das Modul ``db`` durch SQLite.

    create_engine verbindet nicht; die URL muss nur zum Treiber passen.
    """
    import config

    monkeypatch.setattr(config.settings, "database_url", "postgresql+asyncpg://u:p@127.0.0.1:1/x")
    monkeypatch.setattr(config.settings, "db_statement_timeout_ms", timeout_ms)
    spec = importlib.util.spec_from_file_location("vr11_real_db", BACKEND_DIR / "db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDbEngines:
    def test_both_engines_hide_parameters(self, monkeypatch):
        real_db = _load_real_db_module(monkeypatch)
        assert real_db.engine.sync_engine.hide_parameters is True
        assert real_db.sync_engine.hide_parameters is True

    def test_error_text_carries_no_bound_values(self, monkeypatch):
        """K163/K154: SQLAlchemy hängt sonst die Parameter an jede DB-Fehlermeldung."""
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import DBAPIError

        def error_text(**engine_kwargs) -> str:
            eng = create_engine("sqlite://", **engine_kwargs)
            with eng.connect() as conn, pytest.raises(DBAPIError) as exc:
                conn.execute(text("SELECT * FROM missing WHERE secret = :s"), {"s": "geheim-4711"})
            return str(exc.value)

        assert "geheim-4711" in error_text()
        assert "geheim-4711" not in error_text(hide_parameters=True)

    def test_statement_timeout_is_opt_in(self, monkeypatch):
        real_db = _load_real_db_module(monkeypatch)
        url = "postgresql+asyncpg://u:p@db/x"
        assert real_db._async_connect_args(url, 0) == {}
        assert real_db._async_connect_args(url, -1) == {}
        assert real_db._async_connect_args(url, 15000) == {
            "server_settings": {"statement_timeout": "15000"}
        }

    def test_statement_timeout_only_for_asyncpg(self, monkeypatch):
        real_db = _load_real_db_module(monkeypatch)
        assert real_db._async_connect_args("sqlite+aiosqlite://", 15000) == {}

    def test_engine_builds_with_timeout_set(self, monkeypatch):
        real_db = _load_real_db_module(monkeypatch, timeout_ms=5000)
        assert real_db.engine.sync_engine.hide_parameters is True


def _format(msg: str, *, exc_info=None, extra: dict | None = None) -> dict:
    from logging_config import OpenFolioFormatter

    formatter = OpenFolioFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "message": "msg"},
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    record = logging.LogRecord("svc", logging.WARNING, __file__, 1, msg, None, exc_info)
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    line = formatter.format(record)
    parsed = json.loads(line)  # die Zeile bleibt gültiges JSON
    parsed["_line"] = line
    return parsed


class TestLogMasking:
    SECRET = "s3cr3tKEY0123456789"

    def test_httpx_error_message(self):
        msg = (
            "ETF holdings fetch failed: Client error '429 Too Many Requests' for url "
            f"'https://financialmodelingprep.com/api/v3/etf-holder/SPY?apikey={self.SECRET}'\n"
            "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429"
        )
        out = _format(msg)
        assert self.SECRET not in out["_line"]
        assert "etf-holder/SPY?apikey=***'" in out["msg"]
        assert "For more information check" in out["msg"]

    @pytest.mark.parametrize("param", ["apikey", "api_key", "token", "key", "APIKEY", "Api_Key", "TOKEN"])
    def test_parameter_names_case_insensitive(self, param):
        out = _format(f"GET https://api.example.com/v1/x?series=GDP&{param}={self.SECRET}&file_type=json failed")
        assert self.SECRET not in out["_line"]
        assert f"&{param}=***&file_type=json failed" in out["msg"]

    def test_traceback_is_masked(self):
        try:
            raise RuntimeError(f"for url 'https://finnhub.io/api/v1/quote?symbol=AAPL&token={self.SECRET}'")
        except RuntimeError:
            out = _format("request failed", exc_info=sys.exc_info())
        assert self.SECRET not in out["_line"]
        assert "token=***" in out["exc_info"]
        assert "RuntimeError" in out["exc_info"]

    def test_extra_fields_are_masked(self):
        out = _format("Frontend error", extra={"url": f"https://app/reset-password?token={self.SECRET}"})
        assert out["url"] == "https://app/reset-password?token=***"

    def test_json_escapes_after_the_value_survive(self):
        out = _format(f'url "https://x.test/?apikey={self.SECRET}" und\tTab')
        assert out["msg"] == 'url "https://x.test/?apikey=***" und\tTab'

    def test_other_text_is_untouched(self):
        msg = "Cache key=portfolio_summary:42 missing; monkey=1; https://x.test/?keyword=abc&q=token"
        assert _format(msg)["msg"] == msg

    def test_setup_logging_installs_the_masking_formatter(self):
        import logging_config

        root = logging.getLogger()
        saved_handlers, saved_level = root.handlers[:], root.level
        try:
            logging_config.setup_logging("test")
            assert isinstance(root.handlers[0].formatter, logging_config.OpenFolioFormatter)
        finally:
            root.handlers[:] = saved_handlers
            root.setLevel(saved_level)


class TestAsyncPasswordHelpers:
    async def test_round_trip(self):
        from services import auth_service

        hashed = await auth_service.hash_password_async("Correct-Horse-1!")
        assert hashed.startswith("$2")
        assert auth_service.verify_password("Correct-Horse-1!", hashed)
        assert await auth_service.verify_password_async("Correct-Horse-1!", hashed) is True
        assert await auth_service.verify_password_async("wrong", hashed) is False
        assert await auth_service.verify_password_safe_async("Correct-Horse-1!", hashed) is True
        assert await auth_service.verify_password_safe_async("Correct-Horse-1!", None) is False

    async def test_runs_off_the_event_loop_in_own_pool(self, monkeypatch):
        """K002: bcrypt rechnet rund 0.2 s; im Handler stand so lange der Event-Loop."""
        from services import auth_service

        threads = []

        def slow_hash(password):
            threads.append(threading.current_thread())
            time.sleep(0.2)
            return "hash:" + password

        def slow_verify(password, password_hash):
            threads.append(threading.current_thread())
            time.sleep(0.2)
            return password_hash == "hash:" + password

        monkeypatch.setattr(auth_service, "hash_password", slow_hash)
        monkeypatch.setattr(auth_service, "verify_password", slow_verify)

        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.create_task(ticker())
        try:
            assert await auth_service.hash_password_async("pw") == "hash:pw"
            assert await auth_service.verify_password_async("pw", "hash:pw") is True
            assert await auth_service.verify_password_safe_async("pw", "hash:pw") is True
        finally:
            task.cancel()

        assert ticks >= 10  # 0.6 s Arbeit, der Loop lief weiter
        assert all(t is not threading.main_thread() for t in threads)
        assert all(t.name.startswith("bcrypt") for t in threads)

    async def test_pool_caps_parallel_hashes_at_two(self, monkeypatch):
        from services import auth_service

        lock = threading.Lock()
        state = {"active": 0, "max": 0}

        def counting_hash(password):
            with lock:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
            time.sleep(0.05)
            with lock:
                state["active"] -= 1
            return "h"

        monkeypatch.setattr(auth_service, "hash_password", counting_hash)
        await asyncio.gather(*(auth_service.hash_password_async("pw") for _ in range(8)))
        assert state["max"] == 2

    def test_sync_functions_stay(self):
        from services import auth_service

        assert not asyncio.iscoroutinefunction(auth_service.hash_password)
        assert not asyncio.iscoroutinefunction(auth_service.verify_password)
        assert not asyncio.iscoroutinefunction(auth_service.verify_password_safe)
