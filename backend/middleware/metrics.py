"""Prometheus metrics middleware for FastAPI."""

import time

from fastapi import Request
from fastapi.responses import Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# --- Metrics ---

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

CACHE_OPS = Counter(
    "cache_operations_total",
    "Cache operations",
    ["operation", "backend"],
)

EXTERNAL_API_CALLS = Counter(
    "external_api_calls_total",
    "External API calls",
    ["service", "status"],
)

ACTIVE_REQUESTS = Gauge(
    "http_active_requests",
    "Currently active HTTP requests",
)


def _normalize_path(path: str) -> str:
    """Collapse dynamic path segments to reduce cardinality."""
    parts = path.strip("/").split("/")
    normalized = []
    for i, part in enumerate(parts):
        # Replace UUIDs and ticker-like segments after known prefixes
        if i > 0 and parts[i - 1] in ("stock", "stocks"):
            normalized.append("{ticker}")
        elif len(part) == 36 and part.count("-") == 4:
            normalized.append("{id}")
        else:
            normalized.append(part)
    return "/" + "/".join(normalized)


async def metrics_middleware(request: Request, call_next):
    """Record request count, latency, and active requests."""
    path = request.url.path

    # Skip metrics endpoint itself
    if path == "/metrics":
        return await call_next(request)

    # Skip health checks from counter noise
    if path == "/api/health":
        return await call_next(request)

    endpoint = _normalize_path(path)
    method = request.method

    ACTIVE_REQUESTS.inc()
    start = time.monotonic()
    try:
        response = await call_next(request)
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=response.status_code).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(time.monotonic() - start)
        return response
    except Exception as e:
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=500).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(time.monotonic() - start)
        raise
    finally:
        ACTIVE_REQUESTS.dec()


async def metrics_endpoint(request: Request) -> Response:
    """Expose Prometheus metrics at /metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
