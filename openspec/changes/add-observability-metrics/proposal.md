## Why

The Market Data Hub currently lacks request-level telemetry and structured logging, making it impossible to monitor request rates, latencies, error rates per provider/endpoint, or answer audit questions like "who requested what, from which provider, and when?"

## What Changes

- Add Prometheus metrics endpoint (`GET /metrics`) exposing request count and duration histograms with low-cardinality labels
- Implement structured JSON audit logging to stdout using structlog, with one log entry per completed request
- Create observability middleware that captures metrics and logs for all API requests
- Inject provider context into logs via structlog contextvars
- Add new dependencies: `prometheus-client` and `structlog`
- Configure metrics with labels: provider, endpoint, status_class (keeping cardinality under control)
- Exclude high-cardinality data (ticker symbols, client IDs) from metric labels

## Capabilities

### New Capabilities
- `observability-metrics`: Prometheus metrics collection and exposition for monitoring request rates, latencies, and errors
- `audit-logging`: Structured JSON logging for compliance and debugging with full request context

### Modified Capabilities
<!-- No existing capabilities have requirement changes -->

## Impact

- **New module**: `app/observability/` with metrics, audit logging, and middleware components
- **API changes**: New `/metrics` endpoint added to routes_meta.py
- **Dependencies**: Two new production dependencies in pyproject.toml
- **Middleware**: New observability middleware added to FastAPI app stack
- **Service layer**: All service methods must inject provider context via structlog
- **Providers**: Base provider classes need explicit `name` attribute
- **Docker/K8s**: Prometheus scrape targets can now monitor the service
- **Logging**: Stdout format changes from plain text to structured JSON lines