from collections import Counter as KeyCounter
from threading import Lock

import httpx
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.observability.telemetry import (
    DATA_ROUTES,
    PROVIDER_OPERATIONS,
    Layer,
    RequestTelemetry,
)
from app.utils.errors import DataNotFoundError, ProviderTimeoutError

REGISTRY = CollectorRegistry()

PROVIDERS = frozenset(
    {
        "ibkr",
        "ibkrweb",
        "lseg",
        "finnhub",
        "polygon",
        "prixe",
        "schwab",
        "none",
        "alphavantage",
        "financialdatasets",
        "earningsapi",
    }
)
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

UPSTREAM_REQUESTS = Counter(
    "mdh_provider_upstream_requests_total",
    "Actual upstream attempts sent to metered providers, across all capabilities.",
    ("provider",),
    registry=REGISTRY,
)
PROVIDER_SESSION_STATE = Gauge(
    "mdh_provider_session_state",
    "Current gateway session state (1 for active state, 0 otherwise).",
    ("provider", "state"),
    registry=REGISTRY,
)
PROVIDER_RATE_LIMITS = Counter(
    "mdh_provider_rate_limits_total",
    "HTTP 429 responses received from an upstream provider.",
    ("provider",),
    registry=REGISTRY,
)


HISTORY_STORE_RESULTS = frozenset(
    {
        "store",
        "tail_sync",
        "backfill",
        "full_load",
        "reload",
        "stale",
        "fallback_provider",
        "bypass",
    }
)

HISTORY_STORE_READS = Counter(
    "mdh_history_store_reads_total",
    "History requests by dataset and how the history store served them.",
    ("dataset", "result"),
    registry=REGISTRY,
)

DATA_BUCKETS = (
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)
DATA_PROVIDERS = PROVIDERS | {"multiple"}
DATA_ENDPOINTS = frozenset(DATA_ROUTES.values()) | {"other"}
DATA_SOURCES = frozenset({"redis", "postgres", "provider", "postgres+provider"})
CACHE_STATUSES = frozenset({"hit", "miss", "bypass"})
DATA_CHANNELS = frozenset({"http", "mcp"})
LAYER_OPERATIONS = frozenset({"read", "write"})
PROVIDER_METRIC_OPERATIONS = PROVIDER_OPERATIONS | {"other"}
_DATA_LABELS = ("channel", "endpoint", "source", "provider")
_LAYER_LABELS = ("endpoint", "operation", "status")

DATA_REQUESTS = Counter(
    "mdh_data_requests_total",
    "Successful market data requests by answer provenance.",
    (*_DATA_LABELS, "cache_status"),
    registry=REGISTRY,
)
DATA_DURATION = Histogram(
    "mdh_data_request_duration_seconds",
    "Market data duration to response start.",
    _DATA_LABELS,
    buckets=DATA_BUCKETS,
    registry=REGISTRY,
)
CACHE_DURATION = Histogram(
    "mdh_cache_operation_duration_seconds",
    "Redis cache operation duration.",
    _LAYER_LABELS,
    buckets=DATA_BUCKETS,
    registry=REGISTRY,
)
DB_DURATION = Histogram(
    "mdh_db_operation_duration_seconds",
    "History store transaction duration.",
    _LAYER_LABELS,
    buckets=DATA_BUCKETS,
    registry=REGISTRY,
)
PROVIDER_DURATION = Histogram(
    "mdh_provider_request_duration_seconds",
    "Outermost provider interface call duration.",
    ("provider", "operation", "status"),
    buckets=DATA_BUCKETS,
    registry=REGISTRY,
)
CONCURRENT_MISSES = Counter(
    "mdh_cache_concurrent_miss_total",
    "Cache misses overlapping another miss for the same key.",
    ("endpoint",),
    registry=REGISTRY,
)
_inflight_misses: KeyCounter[str] = KeyCounter()
_miss_lock = Lock()


def record_data_request(telemetry: RequestTelemetry, elapsed: float) -> None:
    provider = telemetry.data_provider
    if provider and "+" in provider:
        provider = (
            "multiple"
            if all(name in PROVIDERS for name in provider.split("+"))
            else "none"
        )
    labels = (
        _label_value(telemetry.channel, DATA_CHANNELS, "http"),
        _label_value(telemetry.endpoint_key(), DATA_ENDPOINTS, "other"),
        _label_value(telemetry.source(), DATA_SOURCES, "provider"),
        _label_value(provider, DATA_PROVIDERS, "none"),
    )
    DATA_REQUESTS.labels(
        *labels, _label_value(telemetry.cache_status, CACHE_STATUSES, "bypass")
    ).inc()
    DATA_DURATION.labels(*labels).observe(elapsed)


def record_operation(
    layer: Layer,
    endpoint: str,
    operation: str,
    provider: str | None,
    elapsed: float,
    error: BaseException | None,
) -> None:
    if layer == "provider":
        if error is None:
            status = "success"
        elif isinstance(error, DataNotFoundError):
            status = "not_found"
        elif isinstance(
            error, (ProviderTimeoutError, TimeoutError, httpx.TimeoutException)
        ):
            status = "timeout"
        else:
            status = "error"
        PROVIDER_DURATION.labels(
            _label_value(provider, PROVIDERS, "none"),
            _label_value(operation, PROVIDER_METRIC_OPERATIONS, "other"),
            status,
        ).observe(elapsed)
        return
    histogram = DB_DURATION if layer == "db" else CACHE_DURATION
    histogram.labels(
        _label_value(endpoint, DATA_ENDPOINTS, "other"),
        _label_value(operation, LAYER_OPERATIONS, "read"),
        "ok" if error is None else "error",
    ).observe(elapsed)


def register_cache_miss(telemetry: RequestTelemetry, key: str) -> None:
    with _miss_lock:
        if telemetry.closed or key in telemetry.miss_keys:
            return
        concurrent = _inflight_misses[key] > 0
        _inflight_misses[key] += 1
        telemetry.miss_keys.add(key)
    if concurrent:
        endpoint = _label_value(telemetry.endpoint_key(), DATA_ENDPOINTS, "other")
        CONCURRENT_MISSES.labels(endpoint).inc()


def release_cache_misses(telemetry: RequestTelemetry) -> None:
    with _miss_lock:
        for key in telemetry.miss_keys:
            _inflight_misses[key] -= 1
            if not _inflight_misses[key]:
                del _inflight_misses[key]
        telemetry.miss_keys.clear()
        telemetry.closed = True


def record_history_store_read(dataset: str, result: str) -> None:
    HISTORY_STORE_READS.labels(
        _label_value(dataset, frozenset({"prices", "iv"}), "prices"),
        _label_value(result, HISTORY_STORE_RESULTS, "bypass"),
    ).inc()


def _label_value(value: str | None, allowed: frozenset[str], default: str) -> str:
    if value is not None and value in allowed:
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
