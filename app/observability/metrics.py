from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

REGISTRY = CollectorRegistry()

PROVIDERS = frozenset({"ibkr", "lseg", "finnhub", "polygon", "prixe", "schwab", "none"})
ENDPOINTS = frozenset(
    {
        "prices",
        "options",
        "news",
        "companies",
        "health",
        "admin",
        "mcp",
        "metrics",
        "other",
    }
)
STATUS_CLASSES = frozenset({"2xx", "4xx", "5xx"})

REQUEST_COUNT = Counter(
    "mdh_http_requests_total",
    "Total HTTP requests handled by Market Data Hub.",
    ("provider", "endpoint", "status_class"),
    registry=REGISTRY,
)

REQUEST_DURATION = Histogram(
    "mdh_http_request_duration_seconds",
    "HTTP request duration in seconds for Market Data Hub.",
    ("provider", "endpoint", "status_class"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)


def _label_value(value: str | None, allowed: frozenset[str], default: str) -> str:
    if value in allowed:
        return value
    return default


def status_class(status_code: int) -> str:
    if 400 <= status_code < 500:
        return "4xx"
    if status_code >= 500:
        return "5xx"
    return "2xx"


def record_request(
    provider: str | None,
    endpoint: str,
    response_status_class: str,
    duration_seconds: float,
) -> None:
    provider_label = _label_value(provider, PROVIDERS, "none")
    endpoint_label = _label_value(endpoint, ENDPOINTS, "other")
    status_label = _label_value(response_status_class, STATUS_CLASSES, "5xx")

    REQUEST_COUNT.labels(provider_label, endpoint_label, status_label).inc()
    REQUEST_DURATION.labels(provider_label, endpoint_label, status_label).observe(
        duration_seconds
    )


def metrics_response() -> bytes:
    return generate_latest(REGISTRY)
