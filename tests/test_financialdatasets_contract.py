import json
from datetime import date

import httpx
import pytest
from financialdatasets_contract import (
    FIXTURES,
    OPENAPI,
    validate_request,
    validate_response,
)

from app.providers import request_budget
from app.providers.financialdatasets import FinancialDatasetsProvider


@pytest.mark.parametrize("name,path,status", [
    ("earnings", "/earnings", 200),
    ("earnings_page_2", "/earnings", 200),
    ("prices_day", "/prices", 200),
    ("prices_week", "/prices", 200),
    ("prices_page_2", "/prices", 200),
    ("snapshot", "/prices/snapshot", 200),
    ("company_facts", "/company/facts", 200),
    ("news", "/news", 200),
    ("news_empty", "/news", 200),
    ("error_401", "/earnings", 401),
    ("error_402", "/earnings", 402),
    ("error_404", "/earnings", 404),
])
def test_response_fixture_contract(name, path, status):
    validate_response(path, status, json.loads((FIXTURES / f"{name}.json").read_text()))


def test_filing_window_enum_drift():
    values = OPENAPI["components"]["schemas"]["EarningsRecord"]["properties"]["filing_window"]
    assert set(values["enum"]) == {
        "PRE_MARKET", "DURING_MARKET", "AFTER_HOURS", "WEEKEND",
    }, "Financial Datasets filing_window enum changed; update the provider mapping"
    assert values["nullable"] is True


@pytest.mark.parametrize("path,params", [
    ("/earnings", {"ticker": "AAPL", "limit": 40}),
    ("/earnings", {"cursor": "earnings-page-2"}),
    ("/prices", {"ticker": "AAPL", "interval": "day", "start_date": "2025-01-01", "end_date": "2026-11-17"}),
    ("/prices", {"ticker": "AAPL", "interval": "week", "start_date": "2025-01-01", "end_date": "2026-11-17"}),
    ("/prices", {"cursor": "prices-page-2"}),
    ("/prices/snapshot", {"ticker": "AAPL"}),
    ("/company/facts", {"ticker": "AAPL"}),
])
def test_upstream_request_contract(path, params):
    validate_request(httpx.Request(
        "GET", f"https://api.financialdatasets.ai{path}",
        params=params, headers={"X-API-KEY": "fixture-key"},
    ))


async def test_built_news_request_contract(monkeypatch):
    monkeypatch.setattr(request_budget, "_local", {})
    monkeypatch.setattr(request_budget, "budget_redis", lambda: None)
    monkeypatch.setattr("app.providers.metered.get_provider_credential_sync", lambda *_: "fixture-key")
    requests = []

    def send(request):
        requests.append(request)
        validate_request(request)
        assert request.url.path == "/news"
        assert dict(request.url.params) == {"ticker": "AAPL", "limit": "10"}
        assert request.headers["X-API-KEY"] == "fixture-key"
        return httpx.Response(200, content=(FIXTURES / "news_empty.json").read_bytes())

    provider = FinancialDatasetsProvider()
    async with httpx.AsyncClient(base_url=provider.base_url, transport=httpx.MockTransport(send)) as client:
        provider._client = client
        # The caller may ask for more than the upstream limit.
        await provider.get_company_news("aapl", date(2026, 11, 1), date(2026, 11, 20), limit=20)
    assert len(requests) == 1
