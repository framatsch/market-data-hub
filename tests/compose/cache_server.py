"""Verification-only fake services; production app lifecycle and Redis are unchanged."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import uvicorn

from app.api import mcp
from app.config import settings
from app.dependencies import (
    get_company_service,
    get_news_service,
    get_options_service,
    get_price_service,
)
from app.main import app
from app.models.common import MarketStatus
from app.models.company import CompanyProfile, CompanySummary
from app.models.news import NewsArticle
from app.models.options import OptionChain
from app.models.price import PriceBar


async def chain(*args, **kwargs):
    print("VERIFY: live option provider called", flush=True)
    return OptionChain(
        underlying_symbol="AAPL",
        expiry=date(2026, 12, 18),
        options=[],
        provider="schwab",
    )


async def history(*args, **kwargs):
    print("VERIFY: live history provider called", flush=True)
    now = datetime.now(UTC)
    return [PriceBar(
        symbol="AAPL", start=now, end=now, open=Decimal("123.45"),
        high=Decimal("123.45"), low=Decimal("123.45"), close=Decimal("123.45"),
        volume=100, provider="schwab",
    )]


async def profile(*args, **kwargs):
    print("VERIFY: live profile provider called", flush=True)
    return CompanyProfile(
        symbol="AAPL", name="Apple", exchange="NASDAQ", currency="USD", provider="schwab",
    )


async def search(*args, **kwargs):
    print("VERIFY: live search provider called", flush=True)
    return [CompanySummary(symbol="AAPL", name="Apple", exchange="NASDAQ", provider="schwab")]


async def news(*args, **kwargs):
    print("VERIFY: live news provider called", flush=True)
    return [NewsArticle(
        article_id="schwab:verify", title="Verification", summary="Fake news data",
        published_at=datetime.now(UTC), source="Test", url="https://example.com/news",
    )]


async def market_status(*args, **kwargs):
    print("VERIFY: live market-status provider called", flush=True)
    return MarketStatus(market="open", server_time=datetime.now(UTC), provider="schwab")


options = SimpleNamespace(get_option_chain=chain)
prices = SimpleNamespace(get_historical_prices=history, get_market_status=market_status)
companies = SimpleNamespace(get_company_profile=profile, search_companies=search)
news_service = SimpleNamespace(get_company_news=news)
app.dependency_overrides[get_options_service] = lambda: options
app.dependency_overrides[get_price_service] = lambda: prices
app.dependency_overrides[get_company_service] = lambda: companies
app.dependency_overrides[get_news_service] = lambda: news_service
mcp._options_service = lambda: options
mcp._price_service = lambda: prices
mcp._company_service = lambda: companies
mcp.get_registry = lambda: SimpleNamespace(get_news_provider=lambda _: news_service)
uvicorn.run(app, host=settings.APP_HOST, port=settings.APP_PORT)
