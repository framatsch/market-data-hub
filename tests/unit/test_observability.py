import json
import re
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_price_service
from app.main import app
from app.models.price import PriceQuote
from app.observability.metrics import metrics_response, record_request
from app.observability.middleware import ObservabilityMiddleware


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
