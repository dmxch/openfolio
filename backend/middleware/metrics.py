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


# Fallback normalization (only used when no matched route is available, e.g.
# 404s): dynamic segments AFTER these known literal prefixes are collapsed to
# a placeholder — ticker/slug/currency paths must not create one time series
# per value (Review 2026-07-02, M29).
_SEGMENT_PLACEHOLDERS = {
    "stock": "{ticker}",
    "stocks": "{ticker}",
    "score": "{ticker}",
    "levels": "{ticker}",
    "mrs": "{ticker}",
    "mrs-history": "{ticker}",
    "resistance": "{ticker}",
    "reversal": "{ticker}",
    "breakouts": "{ticker}",
    "heartbeat": "{ticker}",
    "etf-sectors": "{ticker}",
    "ticker": "{ticker}",
    "watchlist": "{ticker}",
    "positions": "{ticker}",
    "fx": "{currency}",
    "industries": "{slug}",
    "sectors": "{etf_ticker}",
}

# Literal sub-resources that directly follow one of the prefixes above and
# must NOT be collapsed (e.g. /positions/by-id/..., /stock/search).
_LITERAL_SEGMENTS = {
    "by-id",
    "search",
    "batch",
    "pending",
    "templates",
    "allocations",
    "import-rules",
    "from-template",
    "migration-rollback",
    "backfill-snapshots",
    "onboarding-dismiss",
}


def _normalize_path(path: str) -> str:
    """Collapse dynamic path segments to reduce label cardinality."""
    parts = path.strip("/").split("/")
    normalized = []
    for i, part in enumerate(parts):
        prev = parts[i - 1] if i > 0 else ""
        # UUIDs anywhere in the path
        if len(part) == 36 and part.count("-") == 4:
            normalized.append("{id}")
        # Ticker-/slug-like segments after known prefixes
        elif prev in _SEGMENT_PLACEHOLDERS and part not in _LITERAL_SEGMENTS:
            normalized.append(_SEGMENT_PLACEHOLDERS[prev])
        else:
            normalized.append(part)
    return "/" + "/".join(normalized)


def _endpoint_label(request: Request) -> str:
    """Bounded endpoint label for Prometheus.

    Prefers the matched route's ``path_format`` (e.g.
    ``/api/analysis/score/{ticker}``) — FastAPI stores the route in
    ``request.scope["route"]`` during routing, which has happened by the time
    ``call_next`` returns. Falls back to heuristic normalization for
    unmatched paths (404s).
    """
    route = request.scope.get("route")
    path_format = getattr(route, "path_format", None)
    if path_format:
        return path_format
    return _normalize_path(request.url.path)


async def metrics_middleware(request: Request, call_next):
    """Record request count, latency, and active requests."""
    path = request.url.path

    # Skip metrics endpoint itself
    if path == "/metrics":
        return await call_next(request)

    # Skip health checks from counter noise
    if path == "/api/health":
        return await call_next(request)

    method = request.method

    ACTIVE_REQUESTS.inc()
    start = time.monotonic()
    status = 500  # default when call_next raises
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        # Label AFTER call_next: only then is the matched route in scope.
        endpoint = _endpoint_label(request)
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(time.monotonic() - start)
        ACTIVE_REQUESTS.dec()


async def metrics_endpoint(request: Request) -> Response:
    """Expose Prometheus metrics at /metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
