# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""LSEG news is retired without removing news support from other providers."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import mcp, routes_admin, routes_companies, routes_meta
from app.dependencies import get_news_service
from app.main import app_error_handler
from app.models.news import NewsArticle
from app.providers.base import (
    BaseCompanyProvider,
    BaseNewsProvider,
    BasePriceProvider,
    BaseVolatilityProvider,
)
from app.providers.lseg import LSEGProvider
from app.providers.registry import ProviderRegistry
from app.services.news_service import NewsService
from app.utils.errors import AppError, InvalidProviderError


@pytest.fixture
def news_env(monkeypatch):
    monkeypatch.setattr("app.providers.lseg.REFINITIV_AVAILABLE", True)
    monkeypatch.setattr("app.providers.lseg._patch_refinitiv_httpx_proxy_handling", lambda: None)
    lseg = LSEGProvider()
    lseg.name = "lseg"
    # Keep red tests safe: the old implementation must never contact LSEG.
    if hasattr(lseg, "_get_company_news_sync"):
        monkeypatch.setattr(lseg, "_get_company_news_sync", Mock(
            side_effect=AssertionError("Retired LSEG news SDK must not be called")
        ))
    finnhub = Mock(spec=BaseNewsProvider)
    finnhub.name = "finnhub"
    finnhub.get_company_news = AsyncMock(return_value=[NewsArticle(
        article_id="finnhub:1", title="Test headline", summary="Summary",
        published_at=datetime(2026, 11, 6, tzinfo=UTC),
        source="Finnhub", url="https://example.com/news",
    )])
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    registry = ProviderRegistry()
    registry._providers = {"lseg": lseg, "finnhub": finnhub}
    registry.default_news_provider = "finnhub"
    monkeypatch.setattr(mcp, "get_registry", lambda: registry)
    monkeypatch.setattr(routes_meta, "get_registry", lambda: registry)
    return lseg, finnhub, registry


@pytest.fixture
def news_client(news_env, cache_redis):
    _, _, registry = news_env
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(routes_companies.router)
    app.include_router(routes_meta.router)
    app.dependency_overrides[get_news_service] = lambda: NewsService(registry)
    return TestClient(app, raise_server_exceptions=False)


def test_lseg_capabilities_no_longer_include_news(news_env):
    lseg, _, registry = news_env
    assert not isinstance(lseg, BaseNewsProvider)
    assert not hasattr(lseg, "get_company_news")
    assert not hasattr(lseg, "_get_company_news_sync")
    assert all(isinstance(lseg, base) for base in (
        BasePriceProvider, BaseCompanyProvider, BaseVolatilityProvider,
    ))
    assert routes_admin._provider_capabilities("lseg", lseg) == routes_admin.PROVIDER_CAPABILITIES["lseg"]
    with pytest.raises(InvalidProviderError):
        registry.get_news_provider("lseg")


def test_retired_lseg_news_default_is_ignored(news_env):
    lseg, _, registry = news_env
    registry._apply_default_settings({
        "default_price_provider": "lseg", "default_news_provider": "lseg",
    })
    assert registry.default_news_provider is None
    assert registry.get_price_provider() is lseg
    with pytest.raises(AppError) as error:
        registry.get_news_provider()
    assert error.value.code == "PROVIDER_NOT_AVAILABLE"


def test_public_provider_catalog_does_not_advertise_lseg_news(news_client):
    available = news_client.get("/providers").json()["data"]["available"]
    assert "lseg" not in available["news"]
    assert "lseg" in available["price"]
    assert "lseg" in available["company"]
    assert "lseg" in available["volatility"]


def test_lseg_news_is_rejected_without_caching_or_sdk_calls(news_client, cache_redis):
    for _ in range(2):
        response = news_client.get("/companies/AAPL/news?provider=lseg")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_PROVIDER"
    assert not cache_redis.entries


async def test_mcp_lseg_news_is_rejected(news_env, cache_redis):
    with pytest.raises(InvalidProviderError):
        await mcp._tool_get_company_news({"symbol": "AAPL", "provider": "lseg"})
    assert not cache_redis.entries


@pytest.mark.parametrize("format", ["json", "csv"])
def test_other_news_provider_still_works_and_caches(news_client, news_env, format):
    _, finnhub, _ = news_env
    url = f"/companies/AAPL/news?provider=finnhub&format={format}"
    first, second = news_client.get(url), news_client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert second.headers["x-fastapi-cache"] == "HIT"
    finnhub.get_company_news.assert_awaited_once()


def test_news_api_descriptions_do_not_offer_lseg(news_client):
    params = news_client.get("/openapi.json").json()["paths"]["/companies/{symbol}/news"]["get"]["parameters"]
    description = next(p["description"] for p in params if p["name"] == "provider")
    assert "lseg" not in description.lower()
    schema = next(tool for tool in mcp.TOOL_REGISTRY if tool["name"] == "get_company_news")
    assert "lseg" not in schema["inputSchema"]["properties"]["provider"]["description"].lower()
