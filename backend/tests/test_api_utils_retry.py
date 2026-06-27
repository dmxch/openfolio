"""Test: _is_retryable_error wiederholt nur transiente Fehler.

4xx-Client-Errors (402/403/404) erholen sich nicht durch Retry -> fail-fast;
5xx + 429 (Rate-Limit) + Netzwerkfehler bleiben retrybar.
"""
import httpx

from services.api_utils import _is_retryable_error


def _http_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://example.test")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"HTTP {code}", request=req, response=resp)


def test_4xx_client_errors_not_retried():
    for code in (400, 402, 403, 404):
        assert _is_retryable_error(_http_error(code)) is False


def test_429_and_5xx_retried():
    for code in (429, 500, 502, 503):
        assert _is_retryable_error(_http_error(code)) is True


def test_network_errors_retried():
    assert _is_retryable_error(httpx.ConnectError("boom")) is True
    assert _is_retryable_error(httpx.TimeoutException("slow")) is True
    assert _is_retryable_error(TimeoutError()) is True


def test_unrelated_exception_not_retried():
    assert _is_retryable_error(ValueError("nope")) is False
