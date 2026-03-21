"""Retry logic with exponential backoff for external API calls."""
import logging

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

# Shared async httpx client (reused across requests)
_async_client: httpx.AsyncClient | None = None


def get_async_client() -> httpx.AsyncClient:
    """Get or create a shared async httpx client."""
    global _async_client
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(timeout=15)
    return _async_client


# Retry decorator for external API calls
retry_external = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


@retry_external
async def fetch_json(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 15) -> dict:
    """Fetch JSON from URL with retry logic."""
    client = get_async_client()
    resp = await client.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


@retry_external
async def fetch_text(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 15) -> str:
    """Fetch text from URL with retry logic."""
    client = get_async_client()
    resp = await client.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text
