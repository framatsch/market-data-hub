## Context

The Market Data Hub is a FastAPI service that aggregates financial data from multiple providers (IBKR, LSEG, Finnhub, etc.) but currently uses only basic Python logging with no telemetry. As the service scales and serves more clients, we need visibility into request patterns, performance bottlenecks, and audit trails for compliance. The existing plain-text logs to stdout provide no structured data for querying or metrics for monitoring.

Key constraints:
- Must maintain low cardinality for Prometheus metrics (no ticker symbols or client IDs in labels)
- Audit logs must capture full request context but never include response payloads (market data)
- Solution must work in containerized environments with stdout logging
- Cannot break existing log parsers until migration complete

## Goals / Non-Goals

**Goals:**
- Enable monitoring of request rates, latencies, and errors per provider and endpoint via Prometheus
- Create queryable audit trail showing who requested what data from which provider
- Keep metrics cardinality bounded to avoid Prometheus performance issues
- Maintain async performance with non-blocking logging
- Support standard Prometheus/Grafana and Loki/Promtail stacks

**Non-Goals:**
- Custom metrics dashboards or alerting rules (left to operators)
- Log aggregation infrastructure (assumes external Loki/ELK)
- Application performance monitoring (APM) or distributed tracing
- Business metrics (revenue, usage quotas) - only technical metrics
- Changing existing Python `logging` usage (only adding structured audit logs)

## Decisions

### 1. Separate Metrics and Logging Concerns

**Decision**: Use Prometheus for metrics (aggregates) and structlog for audit logs (individual events).

**Alternatives considered:**
- OpenTelemetry (OTLP): More complex, requires collectors, overkill for current needs
- Single structured log with metrics extracted: Higher log volume, slower queries
- StatsD + Graphite: Extra infrastructure, Prometheus is industry standard

**Rationale**: Prometheus is the de facto standard for Kubernetes monitoring. Structlog provides async-safe JSON logging without blocking the event loop.

### 2. Single Middleware for Both Concerns

**Decision**: Implement one `ObservabilityMiddleware` that handles both metrics and audit logging in a single request/response cycle.

**Alternatives considered:**
- Separate middleware instances: Double overhead, timing skew between metrics and logs
- Decorator pattern on routes: Requires modifying every endpoint, easy to miss
- FastAPI dependencies: Cannot capture response status/timing accurately

**Rationale**: Middleware sees the complete request/response cycle with accurate timing. Single pass minimizes overhead.

### 3. Context Variables for Provider Injection

**Decision**: Use structlog's `contextvars` integration to pass provider name from service layer to middleware.

**Alternatives considered:**
- Response headers: Visible to clients, modifies API contract
- Request state: Requires request object threading through all layers
- Thread locals: Not async-safe

**Rationale**: Context variables are async-safe and automatically propagate through the call stack without polluting function signatures.

### 4. Fixed Label Taxonomy

**Decision**: Limit metric labels to: `provider` (7 values), `endpoint` (8 values), `status_class` (3 values) = 168 max series.

**Alternatives considered:**
- Include ticker symbols: Unbounded cardinality (thousands of series)
- Include client IDs: Hundreds of series per endpoint
- More granular endpoints: Harder to aggregate in dashboards

**Rationale**: This keeps cardinality well below Prometheus limits while providing enough granularity for debugging. Ticker and client details remain in audit logs for drill-down.

### 5. Stdout JSON for Logs

**Decision**: Configure structlog to emit JSON lines to stdout (not files).

**Alternatives considered:**
- Log files with rotation: Complex in containers, requires persistent volumes
- Direct to Loki API: Adds HTTP overhead, fails if Loki is down
- Syslog protocol: Additional parsing complexity

**Rationale**: Container stdout is automatically collected by Kubernetes/Docker logging drivers. JSON format works with all log aggregators.

## Risks / Trade-offs

**[Cardinality explosion if labels change]** → Strict code review on label modifications. Document the 168-series budget prominently.

**[Performance overhead from middleware]** → Minimal: ~1ms per request for metrics + logging. Use time.perf_counter() for accuracy.

**[Breaking existing log parsers]** → Keep existing Python logs unchanged. Only add new audit log entries with distinct `"event": "request_completed"` field.

**[Async logging blocking the event loop]** → Structlog's PrintLoggerFactory is non-blocking for line-buffered stdout. Avoid file I/O.

**[Missing provider context in some code paths]** → Middleware defaults to `provider="none"` if context not set. Add tests to verify all service methods set context.

**[Audit logs consuming excessive storage]** → Exclude response bodies and implement log retention policies in Loki (not in application).

**[Metrics endpoint authentication]** → Currently open. Document that `/metrics` should be restricted at ingress/firewall level if needed.