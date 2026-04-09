"""Retry logic with exponential backoff for external API calls."""
import asyncio
import logging
import time

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
    """Get or create a shared async httpx client.

    Redirect-Follow ist aktiviert, weil httpx seit 0.22 standardmaessig nicht
    mehr folgt. Ohne das lieferten Scraper gegen Sites mit www→apex oder
    http→https 302 Responses mit leerem Body zurueck (z.B. dataroma.com
    http→https auf der Homepage). Scraper die bewusst keine Redirects wollen
    koennen explizit `follow_redirects=False` am Call-Site setzen.
    """
    global _async_client
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(timeout=15, follow_redirects=True)
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


class _RateLimiter:
    """Simple sliding-window rate limiter for external API calls."""

    def __init__(self, max_calls: int, period_seconds: float) -> None:
        self._max_calls = max_calls
        self._period = period_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # Remove timestamps outside the window
            self._timestamps = [t for t in self._timestamps if now - t < self._period]
            if len(self._timestamps) >= self._max_calls:
                wait = self._period - (now - self._timestamps[0])
                if wait > 0:
                    await asyncio.sleep(wait)
            self._timestamps.append(time.monotonic())


# CoinGecko Free Tier: 30 calls/minute — use 25 with safety margin
coingecko_limiter = _RateLimiter(max_calls=25, period_seconds=60.0)


async def fetch_json_coingecko(url: str, params: dict | None = None, timeout: int = 15) -> dict:
    """Fetch JSON from CoinGecko with rate limiting and retry."""
    await coingecko_limiter.acquire()
    return await fetch_json(url, params=params, timeout=timeout)
