import json
import logging
import re
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from fastapi.testclient import TestClient

from app.dependencies import get_price_service
from app.logging_config import JsonRequestFormatter, RequestContextFilter
from app.main import app
from app.models.price import PriceQuote
from app.observability.metrics import metrics_response, record_request
from app.observability.middleware import ObservabilityMiddleware
from app.observability.telemetry import DATA_ROUTES


@pytest.fixture
def client():
    mock_price_service = MagicMock()
    mock_price_service.get_latest_price = AsyncMock(
        return_value=PriceQuote(
            symbol="AAPL",
            price=Decimal("150.00"),
            currency="USD",
            timestamp=datetime.now(),
            provider="test",
        )
    )
    app.dependency_overrides[get_price_service] = lambda: mock_price_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def audit_lines(output: str) -> list[dict]:
    lines = []
    for line in output.splitlines():
        if "request_completed" not in line:
            continue
        lines.append(json.loads(line))
    return lines


def test_classify_endpoint_uses_fixed_labels():
    assert ObservabilityMiddleware._classify_endpoint("/prices/AAPL/last") == "prices"
    assert ObservabilityMiddleware._classify_endpoint("/options/AAPL/chain") == "options"
    assert ObservabilityMiddleware._classify_endpoint("/companies/AAPL") == "companies"
    assert ObservabilityMiddleware._classify_endpoint("/companies/AAPL/news") == "news"
    assert ObservabilityMiddleware._classify_endpoint("/health") == "health"
    assert ObservabilityMiddleware._classify_endpoint("/admin/providers") == "admin"
    assert ObservabilityMiddleware._classify_endpoint("/api/admin/providers") == "admin"
    assert ObservabilityMiddleware._classify_endpoint("/mcp/sse") == "mcp"
    assert ObservabilityMiddleware._classify_endpoint("/metrics") == "metrics"
    assert ObservabilityMiddleware._classify_endpoint("/unexpected/AAPL") == "other"


def test_metrics_label_values_are_sanitized():
    record_request("AAPL", "trading-bot-7", "3xx", 0.01)

    body = metrics_response().decode()

    assert 'provider="AAPL"' not in body
    assert 'endpoint="trading-bot-7"' not in body
    assert 'status_class="3xx"' not in body
    assert 'provider="none"' in body
    assert 'endpoint="other"' in body
    assert 'status_class="5xx"' in body


def test_request_updates_metrics_without_high_cardinality_labels(client):
    response = client.get("/prices/AAPL/last?provider=lseg", headers={"X-Client-ID": "trading-bot-7"})
    assert response.status_code == 200

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain; version=0.0.4")

    body = metrics.text
    assert "mdh_http_requests_total" in body
    assert 'provider="lseg"' in body
    assert 'endpoint="prices"' in body
    assert 'status_class="2xx"' in body
    assert "AAPL" not in body
    assert "trading-bot-7" not in body


def test_audit_log_has_required_fields(client, capfd):
    capfd.readouterr()
    response = client.get("/prices/AAPL/last?provider=lseg", headers={"X-Client-ID": "trading-bot-7"})
    assert response.status_code == 200

    logs = audit_lines(capfd.readouterr().out)
    assert len(logs) == 1

    entry = logs[0]
    assert entry["event"] == "request_completed"
    assert entry["request_id"] == response.headers["X-Request-ID"]
    assert entry["level"] == "info"
    assert re.match(r"\d{4}-\d{2}-\d{2}T.*Z", entry["timestamp"])
    assert entry["client_id"] == "trading-bot-7"
    assert entry["method"] == "GET"
    assert entry["path"] == "/prices/{symbol}/last"
    assert entry["provider"] == "lseg"
    assert entry["params"] == {"provider": "lseg"}
    assert entry["status_code"] == 200
    assert isinstance(entry["duration_ms"], float)
    assert "150.00" not in json.dumps(entry)


def test_health_and_metrics_are_not_audit_logged(client, capfd):
    capfd.readouterr()

    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200

    assert audit_lines(capfd.readouterr().out) == []


@pytest.mark.parametrize("path", ["/prices/AAPL/last", "/health", "/not-a-route"])
def test_valid_request_id_is_echoed(client, path):
    response = client.get(path, headers={"X-Request-ID": "vt_7.f:3-a"})
    assert response.headers["X-Request-ID"] == "vt_7.f:3-a"


@pytest.mark.parametrize("inbound", [None, "", "x" * 129, "with space", "with\nnewline"])
def test_missing_or_invalid_request_id_is_replaced(client, inbound):
    headers = {} if inbound is None else {"X-Request-ID": inbound}
    response = client.get("/health", headers=headers)
    assert re.fullmatch(r"[a-f0-9]{32}", response.headers["X-Request-ID"])


def test_unhandled_error_keeps_request_id(monkeypatch):
    def fail():
        raise RuntimeError("unexpected test exception")

    monkeypatch.setitem(app.dependency_overrides, get_price_service, fail)
    response = TestClient(app, raise_server_exceptions=False).get(
        "/prices/AAPL/last", headers={"X-Request-ID": "vt-error"}
    )
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "vt-error"
    assert re.fullmatch(r"total;dur=\d+\.\d", response.headers["Server-Timing"])
    assert "X-Data-Source" not in response.headers


@pytest.mark.parametrize("path", DATA_ROUTES)
def test_openapi_documents_data_headers(client, path):
    schema = client.get("/openapi.json").json()
    method = schema["paths"][path]["get"]
    headers = method["responses"]["200"]["headers"]
    assert set(headers) >= {
        "Server-Timing", "X-Data-Source", "X-Data-Provider", "X-FastAPI-Cache",
        "X-Request-ID", "Cache-Control",
    }
    if any(param["name"] == "format" for param in method.get("parameters", [])):
        assert "X-MDH-Data-As-Of" in headers
    assert set(headers["X-Data-Source"]["schema"]["enum"]) == {
        "redis", "postgres", "provider", "postgres+provider",
    }


def test_cors_exposes_observability_headers_for_allowed_origin(client):
    response = client.get("/prices/AAPL/last", headers={"Origin": "http://localhost:5173"})
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert {name.strip() for name in response.headers["Access-Control-Expose-Headers"].split(",")} == {
        "Server-Timing", "X-FastAPI-Cache", "X-Data-Source", "X-Data-Provider",
        "X-Request-ID", "X-MDH-Data-As-Of",
    }


def test_stdlib_request_context_filter_and_formatter():
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "test", (), None)
    formatter = JsonRequestFormatter()
    context_filter = RequestContextFilter()
    with structlog.contextvars.bound_contextvars(request_id="vt-42"):
        assert context_filter.filter(record)
        assert json.loads(formatter.format(record))["request_id"] == "vt-42"
    assert context_filter.filter(record)
    assert "request_id" not in json.loads(formatter.format(record))


def test_redact_params_hides_secret_like_query_keys():
    redacted = ObservabilityMiddleware._redact_params(
        {
            "provider": "lseg",
            "api_key": "abc123",
            "token_json": "secret",
            "value": "v",
            "password": "pw",
        }
    )

    assert redacted["provider"] == "lseg"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["token_json"] == "[REDACTED]"
    assert redacted["value"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
