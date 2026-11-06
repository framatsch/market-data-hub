from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import cache as response_cache
from app.admin.runtime import set_admin_runtime
from app.admin.settings_repository import SettingsRepository
from app.api.routes_admin import router
from app.config import settings


@pytest.fixture
def audit_logger(monkeypatch):
    logger = Mock()
    monkeypatch.setattr("app.api.routes_admin.audit_log", logger)
    return logger


@pytest.fixture
def client(cache_redis, tmp_path, monkeypatch, audit_logger):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", False)
    set_admin_runtime(settings_repository=SettingsRepository(str(tmp_path / "keys.db")))
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    set_admin_runtime()


def test_status_states(client, cache_redis, monkeypatch):
    cache_redis.entries.update(
        {
            "mdh:options:chain:AAPL:provider=schwab": b"a",
            "mdh:prices:history:AAPL:provider=ibkr": b"b",
            "foreign": b"c",
        }
    )
    result = client.get("/api/admin/cache")
    assert result.status_code == 200
    body = result.json()
    assert body["state"] == "connected"
    assert body["key_counts"] == {
        "options_chain": 1, "historical_prices": 1, "company_profile": 0,
        "company_search": 0, "company_news": 0, "market_status": 0, "volatility": 0,
    }
    assert body["memory"]["used_memory"] == 1024
    assert body["market"]["state"] in {"session", "settle_grace", "settled"}
    assert body["market"]["next_open"]
    cache_redis.fail = True
    unavailable = client.get("/api/admin/cache").json()
    assert unavailable["state"] == "unavailable"
    assert unavailable["key_counts"] is None
    monkeypatch.setattr(response_cache, "_backend", None)
    assert client.get("/api/admin/cache").json()["state"] == "disabled"


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/api/admin/cache", None),
        ("put", "/api/admin/cache/policy", {"option_chain_seconds": 10}),
        ("post", "/api/admin/cache/clear", {"confirm": True}),
    ],
)
def test_admin_auth_required(client, monkeypatch, method, path, payload):
    monkeypatch.setattr(settings, "ADMIN_AUTH_ENABLED", True)
    kwargs = {"json": payload} if payload is not None else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_partial_policy_update_without_redis(client, monkeypatch, audit_logger):
    monkeypatch.setattr(response_cache, "_backend", None)
    result = client.put(
        "/api/admin/cache/policy",
        json={"historical_intraday_seconds": 120, "extend_when_market_closed": False},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["historical_intraday_seconds"] == 120
    assert body["extend_when_market_closed"] is False
    assert body["option_chain_seconds"] == settings.CACHE_TTL_OPTION_CHAIN_SECONDS
    audit_logger.info.assert_called_once_with(
        "cache_policy_updated", user="local",
        changes={"historical_intraday_seconds": 120, "extend_when_market_closed": False},
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"option_chain_seconds": -1},
        {"historical_closed_seconds": 2592001},
        {"option_chain_seconds": None},
        {"option_chain_seconds": True},
        {"unexpected": 1},
    ],
)
def test_invalid_policy_not_persisted(client, payload):
    before = client.get("/api/admin/cache").json()["policy"]
    assert client.put("/api/admin/cache/policy", json=payload).status_code == 422
    assert client.get("/api/admin/cache").json()["policy"] == before


def test_confirmation_guard(client, cache_redis):
    cache_redis.entries["mdh:options:chain:AAPL:provider=schwab"] = b"value"
    for payload in ({}, {"confirm": False}):
        assert client.post("/api/admin/cache/clear", json=payload).status_code == 400
    assert not cache_redis.unlinked


def test_scoped_provider_clear_exact_match_and_audit(client, cache_redis, audit_logger):
    cache_redis.entries.update(
        {
            "mdh:options:chain:AAPL:provider=schwab": b"a",
            "mdh:options:chain:SPX:expiry=2026-12-18&provider=schwab": b"b",
            "mdh:options:chain:AAPL:provider=schwabx": b"c",
            "mdh:options:chain:AAPL:provider=ibkr": b"d",
            "mdh:prices:history:AAPL:provider=schwab": b"e",
            "foreign": b"f",
        }
    )
    result = client.post(
        "/api/admin/cache/clear",
        json={"confirm": True, "scope": "options_chain", "provider": "Schwab"},
    )
    assert result.status_code == 200
    assert result.json()["deleted"] == 2
    assert "mdh:options:chain:AAPL:provider=schwabx" in cache_redis.entries
    assert "mdh:prices:history:AAPL:provider=schwab" in cache_redis.entries
    audit_logger.info.assert_called_once_with(
        "cache_cleared", user="local", scope="options_chain", provider="Schwab", deleted=2,
    )
    result = client.post("/api/admin/cache/clear", json={"confirm": True})
    assert result.json()["deleted"] == 3
    assert cache_redis.entries == {"foreign": b"f"}


def test_clear_unavailable_and_invalid_scope(client, cache_redis, monkeypatch):
    assert (
        client.post(
            "/api/admin/cache/clear", json={"confirm": True, "scope": "foreign"}
        ).status_code
        == 422
    )
    cache_redis.fail = True
    assert (
        client.post("/api/admin/cache/clear", json={"confirm": True}).status_code == 503
    )
    monkeypatch.setattr(response_cache, "_backend", None)
    assert (
        client.post("/api/admin/cache/clear", json={"confirm": True}).status_code == 503
    )


async def test_clear_batches_and_no_library_keys(cache_redis):
    cache_redis.entries.update(
        {f"mdh:options:chain:SYM{i}:provider=schwab": b"value" for i in range(1001)}
    )
    cache_redis.entries["foreign"] = b"untouched"
    assert await response_cache.clear_cache() == 1001
    assert cache_redis.entries == {"foreign": b"untouched"}
    assert await response_cache._backend.clear(key="foreign") == 0


@pytest.mark.parametrize("scope,route", [
    ("company_profile", "companies:profile"),
    ("company_search", "companies:search"),
    ("company_news", "companies:news"),
    ("market_status", "market-status"),
    ("volatility", "volatility:snapshot"),
])
def test_new_scopes_count_and_clear_http_mcp(client, cache_redis, scope, route):
    entries = {
        f"mdh:{route}:AAPL:provider=finnhub": b"http",
        f"mdh:{route}:AAPL:channel=mcp&provider=finnhub": b"mcp",
        f"mdh:{route}:AAPL:channel=mcp&provider=ibkr": b"other provider",
        "mdh:options:chain:AAPL:provider=finnhub": b"other scope",
        "foreign": b"untouched",
    }
    cache_redis.entries.update(entries)
    assert client.get("/api/admin/cache").json()["key_counts"][scope] == 3
    result = client.post("/api/admin/cache/clear", json={"confirm": True, "scope": scope, "provider": "Finnhub"})
    assert result.status_code == 200 and result.json()["deleted"] == 2
    assert client.get("/api/admin/cache").json()["key_counts"][scope] == 1
    assert cache_redis.entries["foreign"] == b"untouched"
    assert "mdh:options:chain:AAPL:provider=finnhub" in cache_redis.entries


@pytest.mark.parametrize("field", ["company_profile_seconds", "company_search_seconds", "company_news_seconds", "market_status_seconds", "volatility_seconds"])
def test_new_policy_update_and_validation(client, field):
    result = client.put("/api/admin/cache/policy", json={field: 123})
    assert result.status_code == 200 and result.json()[field] == 123
    assert len(result.json()) == 10
    for invalid in (-1, 2592001, 1.5, True, None):
        assert client.put("/api/admin/cache/policy", json={field: invalid}).status_code == 422
        assert client.get("/api/admin/cache").json()["policy"][field] == 123


def test_volatility_scope_covers_all_operations(client, cache_redis):
    for operation in ("snapshot", "history", "stats"):
        cache_redis.entries[f"mdh:volatility:{operation}:AAPL:provider=lseg"] = b"http"
        cache_redis.entries[f"mdh:volatility:{operation}:AAPL:channel=mcp&provider=lseg"] = b"mcp"
    cache_redis.entries["mdh:volatility:snapshot:AAPL:provider=ibkr"] = b"other provider"
    assert client.get("/api/admin/cache").json()["key_counts"]["volatility"] == 7
    response = client.post("/api/admin/cache/clear", json={"confirm": True, "scope": "volatility", "provider": "LSEG"})
    assert response.status_code == 200 and response.json()["deleted"] == 6
    assert cache_redis.entries == {"mdh:volatility:snapshot:AAPL:provider=ibkr": b"other provider"}
