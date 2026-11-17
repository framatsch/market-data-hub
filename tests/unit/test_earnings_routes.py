"""HTTP routes of the earnings endpoints with a real service and a fake provider."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import cache as response_cache
from app import response_meta
from app.api import routes_companies, routes_earnings
from app.dependencies import get_earnings_service
from app.main import app_error_handler
from app.models.earnings import EarningsEvent
from app.providers.base import BaseEarningsProvider
from app.providers.registry import ProviderRegistry
from app.services import earnings_service as module
from app.services.earnings_service import EarningsService
from app.utils.errors import AppError, DataNotFoundError, ProviderConnectionError

TODAY = date(2026, 11, 17)


class FakeProvider(BaseEarningsProvider):
    name = "alphavantage"

    def __init__(self, calendar=(), history=None, upcoming=True):
        self.calendar = list(calendar)
        self.history = history or {}
        self.earnings_upcoming = upcoming
        self.calendar_calls = 0
        self.history_calls = []
        self.error = None

    async def get_upcoming_earnings(self, start, end, roots):
        self.calendar_calls += 1
        if self.error:
            raise self.error
        return list(self.calendar)

    async def get_earnings_history(self, root):
        self.history_calls.append(root)
        if root not in self.history:
            raise DataNotFoundError("Earnings", root)
        return list(self.history[root])

    async def test_connection(self):
        return {"success": True}


def ev(symbol, day, **kwargs):
    return EarningsEvent(symbol=symbol, report_date=day, provider="alphavantage", **kwargs)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(routes_earnings, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(routes_companies, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(response_cache, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "budget_redis", lambda: None)


def make_client(provider, service=None, default="alphavantage"):
    registry = ProviderRegistry.__new__(ProviderRegistry)
    registry._providers = {"alphavantage": provider}
    registry.default_earnings_provider = default
    registry._provider_locks, registry._provider_inflight, registry._provider_drained = {}, {}, {}
    app = FastAPI()
    app.add_middleware(response_cache.CacheControlMiddleware)
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(routes_earnings.router)
    app.include_router(routes_companies.router)
    app.dependency_overrides[get_earnings_service] = lambda: service or EarningsService(registry)
    return TestClient(app)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(response_cache.registry, "default_earnings_provider", "alphavantage")
    return FakeProvider(
        [ev("MSFT", date(2027, 1, 27), report_time="amc"), ev("AAPL", date(2027, 1, 28), report_time="amc")],
        {"AAPL": [ev("AAPL", date(2026, 10, 29), eps_actual="1.85", fiscal_period_end=date(2026, 9, 30))]},
    )


@pytest.fixture
def client(cache_redis, provider):
    return make_client(provider)


def test_validation_errors_call_no_provider(client, provider):
    assert client.get("/earnings/calendar").status_code == 422
    assert client.get("/earnings/next").status_code == 422
    too_many = ",".join(f"S{i}" for i in range(51))
    for url in (f"/earnings/calendar?symbols={too_many}", f"/earnings/next?symbols={too_many}"):
        assert client.get(url).status_code == 422
    index = client.get("/earnings/next?symbols=I:SPX,AAPL")
    assert index.status_code == 422 and "I:SPX" in index.json()["error"]["message"]
    assert client.get("/earnings/calendar?symbols=AAPL&format=xml").status_code == 422
    assert client.get("/earnings/calendar?symbols=AAPL&from=2026-12-01&to=2026-11-01").status_code == 422
    assert client.get("/earnings/calendar?symbols=AAPL&from=2024-01-01&to=2027-12-31").status_code == 422
    assert provider.calendar_calls == 0 and provider.history_calls == []


def test_calendar_envelope_statuses_and_defaults(client, provider):
    response = client.get("/earnings/calendar?symbols=AAPL,MSFT,SPY&from=2026-10-01&to=2027-02-28")
    assert response.status_code == 200
    body = response.json()
    assert [(e["report_date"], e["symbol"]) for e in body["data"]] == [
        ("2026-10-29", "AAPL"), ("2027-01-27", "MSFT"), ("2027-01-28", "AAPL"),
    ]
    assert body["data"][0]["eps_actual"] == "1.85" and body["data"][1]["date_status"] == "unknown"
    assert body["meta"]["provider"] == "alphavantage" and body["meta"]["stale"] is False
    assert body["meta"]["data_as_of"]
    statuses = {s["symbol"]: s for s in body["meta"]["symbols"]}
    assert statuses["SPY"]["status"] == "not_applicable"
    assert statuses["AAPL"]["history"] == "complete" and statuses["MSFT"]["status"] == "ok"
    assert provider.calendar_calls == 1
    default = client.get("/earnings/calendar?symbols=AAPL").json()["data"]  # today-30 .. today+90
    assert [e["report_date"] for e in default] == ["2026-10-29", "2027-01-28"]


def test_next_cache_hit_restores_request_order_and_ttl(client, provider, cache_redis):
    first = client.get("/earnings/next?symbols=MSFT,AAPL,SPY")
    second = client.get("/earnings/next?symbols=SPY,AAPL,MSFT")
    third = client.get("/earnings/next?symbols=aapl,msft,spy")
    assert [r["symbol"] for r in first.json()["data"]] == ["MSFT", "AAPL", "SPY"]
    assert second.headers["x-fastapi-cache"] == "HIT" and third.headers["x-fastapi-cache"] == "HIT"
    assert [r["symbol"] for r in second.json()["data"]] == ["SPY", "AAPL", "MSFT"]
    assert [r["symbol"] for r in third.json()["data"]] == ["AAPL", "MSFT", "SPY"]
    assert provider.calendar_calls == 1 and provider.history_calls == []
    row = {r["symbol"]: r for r in first.json()["data"]}
    assert row["AAPL"]["days_until"] == 72 and row["SPY"]["status"] == "not_applicable"
    assert 0 < next(iter(cache_redis.ttls.values())) <= 21600
    key = next(iter(cache_redis.entries))
    assert key.startswith("mdh:earnings:next::") and "symbols=AAPL%2CMSFT%2CSPY" in key
    assert "asof=2026-11-17" in key and "provider=alphavantage" in key


def test_calendar_cache_hit_and_zero_ttl_disables(client, provider, cache_redis):
    url = "/earnings/calendar?symbols=MSFT,AAPL&from=2026-11-01&to=2027-03-01"
    first, second = client.get(url), client.get(url.replace("MSFT,AAPL", "AAPL,MSFT"))
    assert first.headers["x-fastapi-cache"] == "MISS" and second.headers["x-fastapi-cache"] == "HIT"
    assert first.json() == second.json()
    assert provider.calendar_calls == 1
    cache_redis.entries.clear()
    response_cache.policy.values.earnings_seconds = 0
    assert client.get(url).headers["cache-control"] == "no-store"
    assert cache_redis.entries == {}


def test_stale_responses_are_not_cached(cache_redis):
    calls = []

    async def stale_next(symbols, provider_name=None):
        calls.append(1)
        response_meta.current().mark_stale("PROVIDER_QUOTA_EXHAUSTED")
        return SimpleNamespace(provider="alphavantage", rows=[])

    client = make_client(None, SimpleNamespace(next=stale_next))
    first = client.get("/earnings/next?symbols=AAPL")
    client.get("/earnings/next?symbols=AAPL")
    assert first.json()["meta"]["stale"] is True
    assert first.json()["meta"]["stale_reason"] == "PROVIDER_QUOTA_EXHAUSTED"
    assert first.headers["cache-control"] == "no-store" and len(calls) == 2
    assert cache_redis.entries == {}


def test_all_failed_returns_provider_error_and_is_not_cached(client, provider, cache_redis):
    provider.error = ProviderConnectionError("upstream down")
    for url in ("/earnings/next?symbols=AAPL", "/earnings/calendar?symbols=AAPL&from=2026-11-17&to=2027-01-01"):
        response = client.get(url)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "PROVIDER_CONNECTION_ERROR"
    assert cache_redis.entries == {}


def test_csv_export_headers(client):
    response = client.get("/earnings/calendar?symbols=AAPL&from=2026-10-01&to=2027-03-01&format=csv")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert response.headers["x-mdh-data-as-of"]
    assert "attachment; filename=" in response.headers["content-disposition"]
    lines = response.text.splitlines()
    assert lines[0].startswith("symbol,report_date,report_time,date_status") and len(lines) == 3
    cached = client.get("/earnings/calendar?symbols=AAPL&from=2026-10-01&to=2027-03-01&format=csv")
    assert cached.headers["x-fastapi-cache"] == "HIT" and cached.text == response.text


def test_provider_resolution_errors(cache_redis, provider):
    assert make_client(provider).get("/earnings/next?symbols=AAPL&provider=schwab").json()["error"]["code"] == "INVALID_PROVIDER"
    missing = make_client(provider, default=None).get("/earnings/next?symbols=AAPL")
    assert missing.status_code == 503
    assert missing.json()["error"]["message"] == "No earnings provider configured — enable a provider in the admin UI"
    history_only = FakeProvider(upcoming=False)
    response = make_client(history_only).get("/earnings/next?symbols=AAPL")
    assert response.status_code == 501 and history_only.calendar_calls == 0


def test_company_earnings_route(client, provider, cache_redis):
    response = client.get("/companies/AAPL/earnings")
    assert response.status_code == 200
    assert [e["report_date"] for e in response.json()["data"]] == ["2026-10-29", "2027-01-28"]
    assert response.json()["meta"]["symbols"][0]["status"] == "ok"
    again = client.get("/companies/AAPL/earnings")
    assert again.headers["x-fastapi-cache"] == "HIT" and provider.history_calls == ["AAPL"]
    assert next(iter(cache_redis.entries)).startswith("mdh:companies:earnings:AAPL:")
    csv = client.get("/companies/AAPL/earnings?format=csv")
    assert csv.headers["content-type"].startswith("text/csv")
    etf = client.get("/companies/SPY/earnings")
    assert etf.status_code == 422 and etf.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"
    assert client.get("/companies/ZZZZ/earnings").status_code == 404
    assert client.get("/companies/AAPL/earnings?from=2026-12-01&to=2026-11-01").status_code == 422
    # The profile route is untouched by the earnings sub-route.
    assert client.get("/companies/AAPL/earnings").json()["data"] != []


def test_openapi_documents_earnings_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/earnings/calendar", "/earnings/next", "/companies/{symbol}/earnings"):
        operation = paths[path]["get"]
        assert len(operation["description"]) > 100
        assert operation["responses"]["200"]
    parameters = {p["name"]: p for p in paths["/earnings/next"]["get"]["parameters"]}
    assert parameters["symbols"]["required"] is True and parameters["symbols"]["schema"]
    calendar = {p["name"] for p in paths["/earnings/calendar"]["get"]["parameters"]}
    assert {"symbols", "from", "to", "provider", "format"} <= calendar
