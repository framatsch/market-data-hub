"""MCP earnings tools: same service, statuses and cache policy as HTTP."""

import json
from datetime import date
from types import SimpleNamespace

import pytest

from app import cache as response_cache
from app import response_meta
from app.api import mcp
from app.models.earnings import EarningsEvent
from app.providers.base import BaseEarningsProvider
from app.providers.registry import ProviderRegistry
from app.services import earnings_service as module
from app.services.earnings_service import EarningsService
from app.utils.errors import DataNotFoundError

TODAY = date(2026, 11, 17)


class FakeProvider(BaseEarningsProvider):
    name = "alphavantage"

    def __init__(self):
        self.calendar_calls = 0
        self.history_calls = []

    async def get_upcoming_earnings(self, start, end, roots):
        self.calendar_calls += 1
        return [
            EarningsEvent(symbol="AAPL", report_date=date(2027, 1, 28), provider=self.name, report_time="amc"),
            EarningsEvent(symbol="MSFT", report_date=date(2027, 1, 27), provider=self.name),
        ]

    async def get_earnings_history(self, root):
        self.history_calls.append(root)
        if root != "AAPL":
            raise DataNotFoundError("Earnings", root)
        return [EarningsEvent(symbol="AAPL", report_date=date(2026, 10, 29), provider=self.name, eps_actual="1.85")]

    async def test_connection(self):
        return {"success": True}


@pytest.fixture
def provider(monkeypatch, cache_redis):
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(mcp, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(response_cache, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "budget_redis", lambda: None)
    monkeypatch.setattr(response_cache.registry, "default_earnings_provider", "alphavantage")
    registry = ProviderRegistry.__new__(ProviderRegistry)
    value = FakeProvider()
    registry._providers = {"alphavantage": value}
    registry.default_earnings_provider = "alphavantage"
    registry._provider_locks, registry._provider_inflight, registry._provider_drained = {}, {}, {}
    monkeypatch.setattr(mcp, "_earnings_service", lambda: EarningsService(registry))
    return value


async def call(name, **arguments):
    response = await mcp._handle_json_rpc("tools/call", {"name": name, "arguments": arguments}, 1)
    if "error" in response:
        return response["error"]
    return json.loads(response["result"]["content"][0]["text"])


def test_tools_are_registered_with_schemas():
    tools = {tool["name"]: tool for tool in mcp.TOOL_REGISTRY}
    for name in ("get_earnings_calendar", "get_next_earnings"):
        assert name in mcp.TOOL_HANDLERS
        assert tools[name]["inputSchema"]["required"] == ["symbols"]
        assert tools[name]["inputSchema"]["properties"]["symbols"]["maxItems"] == 50
    assert {"from_date", "to_date", "provider"} <= set(tools["get_earnings_calendar"]["inputSchema"]["properties"])
    assert "from_date" not in tools["get_next_earnings"]["inputSchema"]["properties"]


async def test_next_returns_http_shape_statuses_and_request_order(provider, cache_redis):
    first = await call("get_next_earnings", symbols=["MSFT", "SPY", "AAPL", "ZZZ"])
    assert [row["symbol"] for row in first["data"]] == ["MSFT", "SPY", "AAPL", "ZZZ"]
    assert [row["status"] for row in first["data"]] == ["ok", "not_applicable", "ok", "none_scheduled"]
    assert first["data"][2]["days_until"] == 72 and first["data"][2]["event"]["report_time"] == "amc"
    assert first["meta"]["provider"] == "alphavantage" and first["meta"]["stale"] is False
    second = await call("get_next_earnings", symbols=["ZZZ", "aapl", "spy", "msft"])
    assert [row["symbol"] for row in second["data"]] == ["ZZZ", "AAPL", "SPY", "MSFT"]
    assert provider.calendar_calls == 1 and provider.history_calls == []
    key = next(iter(cache_redis.entries))
    assert key.startswith("mdh:earnings:next::") and "channel=mcp" in key and "asof=2026-11-17" in key
    assert 0 < next(iter(cache_redis.ttls.values())) <= 21600


async def test_calendar_matches_http_service_and_caches(provider, cache_redis):
    result = await call("get_earnings_calendar", symbols=["AAPL", "MSFT", "SPY"], from_date="2026-10-01", to_date="2027-03-01")
    assert [(e["report_date"], e["symbol"]) for e in result["data"]] == [
        ("2026-10-29", "AAPL"), ("2027-01-27", "MSFT"), ("2027-01-28", "AAPL"),
    ]
    assert {s["symbol"]: s["status"] for s in result["meta"]["symbols"]}["SPY"] == "not_applicable"
    again = await call("get_earnings_calendar", symbols=["SPY", "MSFT", "AAPL"], from_date="2026-10-01", to_date="2027-03-01")
    assert again == result and provider.calendar_calls == 1
    refreshed = await call("get_earnings_calendar", symbols=["AAPL"], from_date="2026-10-01", to_date="2027-03-01", refresh=True)
    assert provider.calendar_calls == 2 and refreshed["data"]


async def test_zero_ttl_serves_live_and_writes_nothing(provider, cache_redis):
    response_cache.policy.values.earnings_seconds = 0
    await call("get_next_earnings", symbols=["AAPL"])
    await call("get_next_earnings", symbols=["AAPL"])
    assert provider.calendar_calls == 2 and cache_redis.entries == {}


async def test_stale_answer_is_not_cached(cache_redis, monkeypatch):
    calls = []

    async def stale_next(symbols, provider_name=None):
        calls.append(1)
        response_meta.current().mark_stale("PROVIDER_QUOTA_EXHAUSTED")
        return SimpleNamespace(provider="alphavantage", rows=[])

    monkeypatch.setattr(mcp, "_earnings_service", lambda: SimpleNamespace(next=stale_next))
    monkeypatch.setattr(response_cache, "earnings_today", lambda: TODAY)
    first = await call("get_next_earnings", symbols=["AAPL"])
    await call("get_next_earnings", symbols=["AAPL"])
    assert first["meta"]["stale"] is True and len(calls) == 2 and cache_redis.entries == {}


@pytest.mark.parametrize("arguments,code", [
    ({"symbols": ["I:SPX"]}, "DATA_VALIDATION_ERROR"),
    ({"symbols": []}, "DATA_VALIDATION_ERROR"),
    ({"symbols": [f"S{i}" for i in range(51)]}, "DATA_VALIDATION_ERROR"),
    ({"symbols": ["AAPL"], "from_date": "not-a-date"}, "DATA_VALIDATION_ERROR"),
    ({"symbols": ["AAPL"], "from_date": "2027-01-01", "to_date": "2026-01-01"}, "DATA_VALIDATION_ERROR"),
])
async def test_validation_errors_are_json_rpc_errors(provider, arguments, code):
    error = await call("get_earnings_calendar", **arguments)
    assert error["code"] == code
    assert provider.calendar_calls == 0
