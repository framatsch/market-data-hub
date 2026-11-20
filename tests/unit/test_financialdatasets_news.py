import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.api import mcp, routes_companies, routes_meta
from app.dependencies import get_news_service
from app.observability.metrics import UPSTREAM_REQUESTS
from app.providers import request_budget
from app.providers.financialdatasets import FinancialDatasetsProvider
from app.providers.news_categories import detect_category
from app.providers.registry import ProviderRegistry
from app.services.news_service import NewsService
from app.utils.errors import AppError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "financialdatasets"
START, END = date(2026, 11, 1), date(2026, 11, 30)


def fixture_data(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
async def upstream(monkeypatch):
    monkeypatch.setattr(request_budget, "_local", {})
    monkeypatch.setattr(request_budget, "budget_redis", lambda: None)
    monkeypatch.setattr("app.providers.metered.get_provider_credential_sync", lambda *_: "fixture-key")

    provider = FinancialDatasetsProvider()
    provider.retry_count = 0
    calls = []
    responses = [httpx.Response(200, json=fixture_data("news"))]

    def send(request):
        calls.append(request)
        return responses.pop(0)

    provider._client = httpx.AsyncClient(base_url=provider.base_url, transport=httpx.MockTransport(send))
    try:
        yield provider, calls, responses
    finally:
        await provider.close()


@pytest.mark.parametrize("title,expected", [
    ("Apple reports Q4 RESULTS", "earnings"),
    ("Apple acquires a hardware company", "merger"),
    ("Apple previews a new device", "product"),
    ("Apple faces an antitrust lawsuit", "legal"),
    ("Apple opens a store", None),
])
def test_title_only_category(title, expected):
    assert detect_category(title) == expected


async def test_news_fields_order_stable_ids_and_usage(upstream):
    provider, calls, responses = upstream
    responses.append(httpx.Response(200, json=fixture_data("news")))
    counter = UPSTREAM_REQUESTS.labels(provider.name)._value
    before = counter.get()

    articles = await provider.get_company_news("aapl", START, END)
    assert len(articles) == 9  # The fixture has one article without a URL.
    assert [item.title for item in articles[:2]] == ["Apple prepares a new device", "Apple opens a store"]
    assert articles[2].model_dump() == {
        "article_id": "financialdatasets:785a3617ae75b0b7",
        "title": "Apple reports earnings for the quarter",
        "summary": "",
        "published_at": datetime(2026, 11, 12, tzinfo=UTC),
        "source": "Example Markets",
        "url": "https://example.com/news/quarterly-earnings",
        "category": "earnings",
        "full_text": None,
        "image": None,
        "sentiment": None,
    }
    assert len(calls) == 1
    assert counter.get() == before + 1
    assert (await provider.budget.usage())["month"]["used"] == 1

    repeated = await provider.get_company_news("AAPL", START, END)
    assert [item.article_id for item in repeated] == [item.article_id for item in articles]


@pytest.mark.parametrize("start,end,query,expected_days", [
    (date(2026, 11, 10), date(2026, 11, 12), {}, [12, 11, 10]),
    (START, END, {"category": "earnings"}, [12, 10]),
    (START, END, {"category": "earnings", "offset": 1, "limit": 1}, [10]),
    (START, END, {"offset": 10}, []),
    (START, END, {"offset": 20}, []),
])
async def test_news_filters_are_local(upstream, start, end, query, expected_days):
    provider, calls, _ = upstream
    result = await provider.get_company_news("AAPL", start, end, **query)
    assert [article.published_at.day for article in result] == expected_days
    assert len(calls) == 1
    assert dict(calls[0].url.params) == {"ticker": "AAPL", "limit": "10"}


async def test_news_skips_malformed_items(upstream):
    provider, _, responses = upstream
    article = fixture_data("news")["news"][0]
    responses[0] = httpx.Response(200, json={"news": [
        None, {**article, "title": ""}, {**article, "date": "invalid"}, article,
    ]})
    result = await provider.get_company_news("AAPL", START, END)
    assert [item.title for item in result] == [article["title"]]


@pytest.mark.parametrize("raw", ["2026-11-12T16:42:26+00:00", "2026-11-13T00:15:00+02:00"])
async def test_news_live_timestamp_maps_to_midnight_on_utc_day(upstream, raw):
    provider, _, responses = upstream
    row = {**fixture_data("news")["news"][0], "date": raw}
    responses[0] = httpx.Response(200, json={"news": [row]})
    day = date(2026, 11, 12)
    articles = await provider.get_company_news("AAPL", day, day)
    assert [item.published_at for item in articles] == [datetime(2026, 11, 12, tzinfo=UTC)]


async def test_news_non_english_does_not_load_credentials_or_make_request(upstream, monkeypatch):
    provider, calls, _ = upstream

    def fail(*_):
        pytest.fail("Non-English news query should not load credentials")

    monkeypatch.setattr("app.providers.metered.get_provider_credential_sync", fail)
    assert await provider.get_company_news("AAPL", START, END, language="de") == []
    assert not calls
    assert (await provider.budget.usage())["month"]["used"] == 0


@pytest.mark.parametrize("status,code", [
    (401, "PROVIDER_NOT_AVAILABLE"),
    (402, "PROVIDER_NOT_AVAILABLE"),
    (404, "DATA_NOT_FOUND"),
])
async def test_news_error_mapping(upstream, status, code):
    provider, calls, responses = upstream
    error = fixture_data(f"error_{status}")
    responses[0] = httpx.Response(status, json=error)
    with pytest.raises(AppError) as exc:
        await provider.get_company_news("AAPL", START, END)
    assert exc.value.code == code
    if status in (401, 402):
        assert exc.value.message == error["message"]
    assert len(calls) == 1


async def test_news_budget_refusal_does_not_make_request(upstream):
    provider, calls, _ = upstream
    provider.budget.configure({"request_budget_per_month": 1})
    await provider.get_company_news("AAPL", START, END)
    counter = UPSTREAM_REQUESTS.labels(provider.name)._value
    before = counter.get()

    with pytest.raises(AppError) as exc:
        await provider.get_company_news("AAPL", START, END)
    assert exc.value.code == "PROVIDER_QUOTA_EXHAUSTED"
    assert len(calls) == 1
    assert counter.get() == before
    assert (await provider.budget.usage())["month"]["used"] == 1


async def test_news_follows_and_meters_cursor_pages(upstream):
    provider, calls, responses = upstream
    rows = fixture_data("news")["news"]
    responses[:] = [
        httpx.Response(200, json={"news": rows[:4], "next_page_url": f"{provider.base_url}/news?cursor=page-2"}),
        httpx.Response(200, json={"news": rows[4:]}),
    ]
    assert len(await provider.get_company_news("AAPL", START, END)) == 9
    assert dict(calls[1].url.params) == {"cursor": "page-2"}
    assert (await provider.budget.usage())["month"]["used"] == 2


@pytest.mark.parametrize("fixture,count", [("news", 9), ("news_empty", 0)])
async def test_news_catalog_route_cache_and_mcp(upstream, cache_redis, monkeypatch, fixture, count):
    provider, calls, responses = upstream
    responses[:] = [httpx.Response(200, json=fixture_data(fixture)) for _ in range(2)]
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    registry = ProviderRegistry()
    registry._providers[provider.name] = provider
    registry._apply_default_settings({"default_news_provider": provider.name})
    assert registry.get_news_provider() is provider
    monkeypatch.setattr(routes_meta, "get_registry", lambda: registry)
    monkeypatch.setattr(mcp, "get_registry", lambda: registry)

    app = FastAPI()
    app.include_router(routes_companies.router)
    app.include_router(routes_meta.router)
    app.dependency_overrides[get_news_service] = lambda: NewsService(registry)
    assert "10 most recent" in app.openapi()["paths"]["/companies/{symbol}/news"]["get"]["description"]
    args = {"from_date": str(START), "to_date": str(END), "provider": provider.name}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        catalog = (await client.get("/providers")).json()["data"]
        assert catalog["available"]["news"] == [provider.name]
        assert catalog["defaults"]["news"] == provider.name
        first = await client.get("/companies/AAPL/news", params=args)
        second = await client.get("/companies/AAPL/news", params=args)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(first.json()["data"]) == count
    assert first.json()["meta"]["has_more"] is False
    assert second.headers["x-fastapi-cache"] == "HIT"
    assert len(calls) == 1
    assert (await provider.budget.usage())["month"]["used"] == 1

    result = await mcp._tool_get_company_news({"symbol": "AAPL", **args})
    text = json.loads(result["content"][0]["text"])
    assert [item["article_id"] for item in text] == [item["article_id"] for item in first.json()["data"]]
