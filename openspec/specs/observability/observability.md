# OpenSpec: Observability — Metrics & Audit Logging

## Status
- **Type**: Feature / Infrastructure
- **Status**: Proposed
- **Author**: Claude
- **Date**: 2026-06-15

## Context & Problem

The Market Data Hub currently uses basic Python `logging` (plain text to stdout) with no request-level telemetry, no structured fields, and no metrics instrumentation. There is no way to:
- Monitor request rates, latencies, or error rates per provider/endpoint.
- Query structured audit logs to answer "who requested what, from which provider, and when?"
- Feed data into Prometheus/VictoriaMetrics for alerting or into Loki for log aggregation.

This spec adds two orthogonal observability layers:

1. **Prometheus Metrics** — a `/metrics` endpoint exposing request count and duration histograms with low-cardinality labels.
2. **Structured Audit Logging** — one JSON log line per request to stdout, suitable for Loki ingestion via Promtail/Alloy.

## Proposed Change

### Requirements

#### Metrics (Prometheus / VictoriaMetrics)
1. Expose `GET /metrics` returning Prometheus text exposition format.
2. Instrument all API routes: request duration (histogram) and request count (counter).
3. Labels — **low cardinality only**:
   - `provider`: `ibkr | lseg | finnhub | polygon | prixe | none`
   - `endpoint`: `prices | options | news | companies | health | admin | mcp | other`
   - `status_class`: `2xx | 4xx | 5xx`
4. **Never** include ticker symbols, client IDs, query params, or any other high-cardinality value in labels.

#### Audit Logging (Loki)
1. Use `structlog` for structured JSON output to stdout (async-safe, non-blocking).
2. Emit exactly **one** JSON log entry per completed request.
3. Required fields per log entry:
   - `timestamp` (ISO 8601)
   - `client_id` (from `X-Client-ID` header or auth token; `"anonymous"` if absent)
   - `method` (HTTP verb)
   - `path` (matched route pattern, e.g. `/prices/{symbol}/last`)
   - `provider` (resolved provider name or `null`)
   - `params` (full query string / body as dict — ticker, expiry, interval, etc.)
   - `status_code` (integer HTTP status)
   - `duration_ms` (float, wall-clock milliseconds)
   - `level` (`info` for 2xx/3xx, `warning` for 4xx, `error` for 5xx)
4. **Never** include response payloads (market data, option chains, etc.) in the log.

## Technical Design

### 1. New Dependencies (`pyproject.toml`)

```toml
dependencies = [
    # ... existing ...
    "prometheus-client>=0.21.0",
    "structlog>=24.4.0",
]
```

### 2. Metrics Module (`app/observability/metrics.py`)

A thin wrapper around `prometheus_client` exposing two instruments and a response generator.

```python
from prometheus_client import (
    CollectorRegistry, Counter, Histogram,
    generate_latest, CONTENT_TYPE_LATEST,
)

registry = CollectorRegistry()

REQUEST_COUNT = Counter(
    "mdh_http_requests_total",
    "Total HTTP requests",
    ["provider", "endpoint", "status_class"],
    registry=registry,
)

REQUEST_DURATION = Histogram(
    "mdh_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["provider", "endpoint", "status_class"],
    registry=registry,
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
```

**Design notes:**
- A dedicated `CollectorRegistry` avoids polluting the default registry with Python process metrics. If process/GC metrics are desired later, merge `PROCESS_COLLECTOR` in.
- Histogram buckets are tuned for typical API latencies (10ms–10s).

### 3. Structured Logger (`app/observability/audit.py`)

Configure `structlog` to produce JSON lines on stdout.

```python
import structlog
import logging
import sys


def setup_structlog():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


audit_log = structlog.get_logger("mdh.audit")
```

**Design notes:**
- `contextvars` integration lets the middleware bind `provider` once; downstream code that resolves the provider calls `structlog.contextvars.bind_contextvars(provider=name)`, and the middleware's final log line picks it up automatically.
- `PrintLoggerFactory(file=sys.stdout)` keeps output synchronous with the event loop (structlog's print is non-blocking for line-buffered stdout). For truly async I/O to a file or socket, wrap with `asyncio.to_thread` or use a `QueueHandler`; stdout in a container is fine as-is.

### 4. Observability Middleware (`app/observability/middleware.py`)

A single Starlette `BaseHTTPMiddleware` that handles both metrics and audit logging.

```python
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import structlog

from app.observability.metrics import REQUEST_COUNT, REQUEST_DURATION
from app.observability.audit import audit_log

_ENDPOINT_MAP = {
    "/prices":     "prices",
    "/options":    "options",
    "/companies":  "companies",
    "/news":       "news",      # /companies/{sym}/news is also "news"
    "/health":     "health",
    "/api/admin":  "admin",
    "/mcp":        "mcp",
    "/metrics":    "metrics",
}

_SKIP_AUDIT = {"/health", "/metrics", "/docs", "/redoc", "/openapi.json"}


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        structlog.contextvars.clear_contextvars()

        response: Response = await call_next(request)

        duration = time.perf_counter() - start
        path = request.url.path
        status = response.status_code
        status_class = f"{status // 100}xx"

        provider = structlog.contextvars.get_contextvars().get("provider", "none")
        endpoint = self._classify_endpoint(path)

        REQUEST_COUNT.labels(
            provider=provider, endpoint=endpoint, status_class=status_class,
        ).inc()
        REQUEST_DURATION.labels(
            provider=provider, endpoint=endpoint, status_class=status_class,
        ).observe(duration)

        if path not in _SKIP_AUDIT and not path.startswith("/admin"):
            level = "info" if status < 400 else ("warning" if status < 500 else "error")
            audit_log.log(
                level,
                "request_completed",
                client_id=request.headers.get("x-client-id", "anonymous"),
                method=request.method,
                path=self._route_pattern(request),
                provider=provider if provider != "none" else None,
                params=dict(request.query_params),
                status_code=status,
                duration_ms=round(duration * 1000, 2),
            )

        return response

    @staticmethod
    def _classify_endpoint(path: str) -> str:
        if "/news" in path:
            return "news"
        for prefix, name in _ENDPOINT_MAP.items():
            if path.startswith(prefix):
                return name
        return "other"

    @staticmethod
    def _route_pattern(request: Request) -> str:
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            return route.path
        return request.url.path
```

**Design notes:**
- `_classify_endpoint` maps URL prefixes to a fixed set of label values (7 + `other`), keeping cardinality bounded.
- `/companies/{sym}/news` is classified as `"news"` via the `"/news" in path` check before the prefix loop.
- `_route_pattern` returns the FastAPI route template (e.g. `/prices/{symbol}/last`) for the audit log, not the resolved path — this keeps the log searchable by route pattern while the `params` field captures the actual values.
- `/health`, `/metrics`, `/docs`, and static admin assets are excluded from audit logging to reduce noise, but they are still counted in metrics.

### 5. Provider Context Injection

The provider name must be available to the middleware *after* the route handler runs. The approach:

**In service layer** (e.g. `PriceService.get_latest_price`):
```python
import structlog

class PriceService:
    async def get_latest_price(self, symbol, provider_name=None, ...):
        provider = self.registry.get_price_provider(provider_name)
        structlog.contextvars.bind_contextvars(provider=provider.name)
        return await provider.get_last_price(symbol, ...)
```

Each service method calls `bind_contextvars(provider=...)` once the provider is resolved. The middleware reads it via `get_contextvars()` after `call_next` returns.

**Provider `.name` property**: Each provider class must expose a `name` attribute. The base classes already have this implicitly via the registry key, but if not, add:

```python
class BasePriceProvider(ABC):
    name: str  # set by registry during initialization
```

And in `ProviderRegistry._initialize_providers`:
```python
instance = cls()
instance.name = name  # "ibkr", "lseg", etc.
self._providers[name] = instance
```

### 6. Metrics Endpoint (`app/api/routes_meta.py`)

Add the `/metrics` route alongside the existing `/health` endpoint:

```python
from fastapi import Response as FastAPIResponse
from app.observability.metrics import metrics_response

@router.get(
    "/metrics",
    tags=["Meta"],
    summary="Prometheus metrics",
    response_class=FastAPIResponse,
    responses={
        200: {
            "description": "Prometheus text exposition format",
            "content": {"text/plain": {"schema": {"type": "string"}}},
        }
    },
)
async def get_metrics():
    body, content_type = metrics_response()
    return FastAPIResponse(content=body, media_type=content_type)
```

### 7. App Integration (`app/main.py`)

```python
from app.observability.audit import setup_structlog
from app.observability.middleware import ObservabilityMiddleware

setup_structlog()

# Add AFTER CORSMiddleware (Starlette middleware stack is LIFO —
# ObservabilityMiddleware wraps the inner app, CORS wraps that)
app.add_middleware(ObservabilityMiddleware)
```

### 8. OpenAPI Schema for `/metrics`

The `/metrics` endpoint is auto-documented by FastAPI via the `responses` dict above. The generated OpenAPI fragment:

```yaml
paths:
  /metrics:
    get:
      tags:
        - Meta
      summary: Prometheus metrics
      operationId: get_metrics
      responses:
        "200":
          description: Prometheus text exposition format
          content:
            text/plain:
              schema:
                type: string
              example: |
                # HELP mdh_http_requests_total Total HTTP requests
                # TYPE mdh_http_requests_total counter
                mdh_http_requests_total{provider="lseg",endpoint="prices",status_class="2xx"} 142
                # HELP mdh_http_request_duration_seconds HTTP request duration in seconds
                # TYPE mdh_http_request_duration_seconds histogram
                mdh_http_request_duration_seconds_bucket{provider="lseg",endpoint="prices",status_class="2xx",le="0.1"} 130
                mdh_http_request_duration_seconds_bucket{provider="lseg",endpoint="prices",status_class="2xx",le="0.25"} 140
                mdh_http_request_duration_seconds_bucket{provider="lseg",endpoint="prices",status_class="2xx",le="+Inf"} 142
                mdh_http_request_duration_seconds_sum{provider="lseg",endpoint="prices",status_class="2xx"} 12.34
                mdh_http_request_duration_seconds_count{provider="lseg",endpoint="prices",status_class="2xx"} 142
```

### 9. File Layout

```
app/
├── observability/
│   ├── __init__.py
│   ├── metrics.py       # Prometheus instruments + registry
│   ├── audit.py          # structlog configuration + audit logger
│   └── middleware.py     # ObservabilityMiddleware (metrics + audit in one pass)
```

## Example Audit Log Output

A single request to `GET /prices/AAPL/last?provider=lseg` produces:

```json
{
  "timestamp": "2026-06-15T14:32:01.123456Z",
  "level": "info",
  "event": "request_completed",
  "client_id": "trading-bot-7",
  "method": "GET",
  "path": "/prices/{symbol}/last",
  "provider": "lseg",
  "params": {"provider": "lseg"},
  "status_code": 200,
  "duration_ms": 87.42
}
```

Note: the ticker `AAPL` appears in the URL path but the audit log uses the **route template** (`/prices/{symbol}/last`), not the resolved path. The ticker is available via the `params` dict if it was a query parameter, or can be extracted from `path_params` if needed — see "Open Questions" below.

## Cardinality Budget

| Label | Values | Source |
|-------|--------|--------|
| `provider` | 7 | `ibkr, lseg, finnhub, polygon, prixe, schwab, none` |
| `endpoint` | 8 | `prices, options, news, companies, health, admin, mcp, other` |
| `status_class` | 3 | `2xx, 4xx, 5xx` |
| **Total series** | **168** | 7 × 8 × 3 (upper bound; most cells stay empty) |

This is well within safe Prometheus cardinality limits.

## Docker / Scraping

Add the Prometheus scrape target in any external `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: market-data-hub
    static_configs:
      - targets: ["market-data-hub:9000"]
    metrics_path: /metrics
    scrape_interval: 15s
```

No changes to `docker-compose.yml` are required — the `/metrics` endpoint is served by the existing FastAPI process on the same port.

## Open Questions

1. **Path params in audit log**: The current design logs the route template (`/prices/{symbol}/last`) but not the resolved path params (`symbol=AAPL`). Should we add a `path_params` field to the audit log for full traceability? This would add the ticker to the log but NOT to metric labels (cardinality is only a concern for metrics).
2. **Admin routes**: Currently excluded from audit logging (`/admin`, `/api/admin`). Should admin actions (credential changes, provider config updates) be audit-logged separately with elevated detail?
3. **Request body logging**: POST endpoints (e.g. MCP `/mcp/messages`) send JSON bodies. Should the audit log include `request_body` for non-GET methods, or only query params?
4. **Health check metrics**: `/health` is currently counted in metrics but excluded from audit logs. Should it also be excluded from metrics to avoid noise from readiness probes?

## Verification Plan

1. **Unit Tests**: Mock middleware, verify label values for various route/provider/status combinations.
2. **Integration Test**: Start app, hit `/prices/AAPL/last?provider=lseg`, then scrape `/metrics` and assert `mdh_http_requests_total{provider="lseg",endpoint="prices",status_class="2xx"} 1`.
3. **Audit Log Test**: Capture stdout, parse JSON, verify all required fields present and response payload absent.
4. **Cardinality Test**: Assert no metric series contain ticker symbols or client IDs by scraping `/metrics` and checking label names.
5. **Manual**: `curl localhost:9000/metrics | promtool check metrics` to validate Prometheus format.
