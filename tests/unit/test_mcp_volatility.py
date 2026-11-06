import json
from datetime import date, timedelta

import pytest

from app.api import mcp
from app.utils.errors import CapabilityNotSupportedError, DataValidationError


@pytest.mark.parametrize("name", ["get_implied_volatility", "get_implied_volatility_history", "get_implied_volatility_stats"])
async def test_tool_dispatch_and_schema(volatility_env, monkeypatch, name):
    monkeypatch.setattr(mcp, "_volatility_service", lambda: volatility_env.service)
    result = await mcp._dispatch("tools/call", {"name": name, "arguments": {"symbol": "aapl"}})
    data = json.loads(result["content"][0]["text"])
    assert data["symbol"] == "AAPL" and data["provider"] == "lseg"
    schema = next(tool for tool in mcp.TOOL_REGISTRY if tool["name"] == name)["inputSchema"]
    assert schema["properties"]["sec_type"]["enum"] == ["stock", "etf", "index", "future"]
    assert schema["required"] == ["symbol"]


async def test_mcp_history_default_and_explicit_dates(volatility_env, monkeypatch):
    monkeypatch.setattr(mcp, "_volatility_service", lambda: volatility_env.service)
    await mcp._tool_get_implied_volatility_history({"symbol": "AAPL"})
    assert volatility_env.lseg.get_implied_volatility_history.call_args.args[1:3] == (
        date.today() - timedelta(days=365), date.today()
    )
    await mcp._tool_get_implied_volatility_history({
        "symbol": "ES", "start_date": "2026-01-01", "end_date": "2026-11-05", "sec_type": "future", "tenor_days": 60,
    })
    assert volatility_env.lseg.get_implied_volatility_history.call_args.args == (
        "ES", date(2026, 1, 1), date(2026, 11, 5), 60, "future", None,
    )


async def test_mcp_capability_error(volatility_env, monkeypatch):
    monkeypatch.setattr(mcp, "_volatility_service", lambda: volatility_env.service)
    with pytest.raises(CapabilityNotSupportedError):
        await mcp._tool_get_implied_volatility_history({"symbol": "ES", "provider": "ibkr", "sec_type": "future"})
    with pytest.raises(DataValidationError):
        await mcp._tool_get_implied_volatility_history({"symbol": "AAPL", "start_date": "not-a-date"})
