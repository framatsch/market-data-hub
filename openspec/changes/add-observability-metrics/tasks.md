## 1. Dependencies and Module Setup

- [x] 1.1 Add prometheus-client>=0.21.0 to dependencies in pyproject.toml
- [x] 1.2 Add structlog>=24.4.0 to dependencies in pyproject.toml
- [x] 1.3 Run uv sync to install new dependencies
- [x] 1.4 Create app/observability/ directory with __init__.py

## 2. Metrics Module

- [x] 2.1 Create app/observability/metrics.py with CollectorRegistry setup
- [x] 2.2 Implement REQUEST_COUNT Counter with provider, endpoint, status_class labels
- [x] 2.3 Implement REQUEST_DURATION Histogram with appropriate buckets (0.01 to 10.0)
- [x] 2.4 Add metrics_response() function returning Prometheus text format

## 3. Audit Logging Module

- [x] 3.1 Create app/observability/audit.py with structlog configuration
- [x] 3.2 Implement setup_structlog() with JSON renderer and ISO timestamp
- [x] 3.3 Configure contextvars processor for async-safe provider injection
- [x] 3.4 Create audit_log logger instance for request logging

## 4. Observability Middleware

- [x] 4.1 Create app/observability/middleware.py with ObservabilityMiddleware class
- [x] 4.2 Implement _classify_endpoint() mapping paths to fixed endpoint labels
- [x] 4.3 Implement _route_pattern() to extract FastAPI route templates
- [x] 4.4 Add timing measurement using time.perf_counter()
- [x] 4.5 Integrate metrics collection (count and duration) in dispatch()
- [x] 4.6 Add audit logging with all required fields (timestamp, client_id, etc.)
- [x] 4.7 Implement skip logic for health, metrics, docs endpoints

## 5. Provider Context Integration

- [x] 5.1 Add name attribute to base provider classes in app/providers/base.py
- [x] 5.2 Update ProviderRegistry._initialize_providers to set provider.name
- [x] 5.3 Modify PriceService.get_latest_price to call structlog.contextvars.bind_contextvars()
- [x] 5.4 Update OptionService methods to inject provider context
- [x] 5.5 Update CompanyService methods to inject provider context
- [x] 5.6 Update NewsService methods to inject provider context

## 6. API Route Integration

- [x] 6.1 Add /metrics endpoint to app/api/routes_meta.py
- [x] 6.2 Configure proper response class and OpenAPI documentation
- [x] 6.3 Import and wire metrics_response function

## 7. Application Startup

- [x] 7.1 Call setup_structlog() in app/main.py before app creation
- [x] 7.2 Add ObservabilityMiddleware to app after CORSMiddleware
- [x] 7.3 Verify middleware ordering (LIFO stack)

## 8. Testing

- [x] 8.1 Write unit tests for endpoint classification logic
- [x] 8.2 Write unit tests for metrics label value validation
- [x] 8.3 Create integration test hitting endpoint and checking /metrics
- [x] 8.4 Test audit log format and required fields
- [x] 8.5 Verify no high-cardinality data in metrics
- [x] 8.6 Test that health/metrics endpoints are not audit logged

## 9. Documentation and Validation

- [x] 9.1 Update OpenAPI schema with /metrics endpoint example
- [x] 9.2 Add Prometheus scrape config example to documentation
- [x] 9.3 Run manual test: curl localhost:8000/metrics | promtool check metrics
- [x] 9.4 Verify JSON logs on stdout with correct structure
- [x] 9.5 Update README with observability setup instructions
