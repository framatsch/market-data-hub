import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.providers import request_budget as module
from app.providers.request_budget import RequestBudget
from app.utils.errors import ProviderQuotaExhaustedError

NOW = datetime(2026, 11, 17, 15, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    module._local.clear()
    monkeypatch.setattr(module, "budget_redis", lambda: None)


async def test_refusal_and_shared_capabilities():
    prices = RequestBudget("alphavantage", 2, 0)
    earnings = RequestBudget("alphavantage", 2, 0)
    await prices.consume(NOW)
    await earnings.consume(NOW)
    with pytest.raises(ProviderQuotaExhaustedError) as error:
        await prices.consume(NOW)
    assert error.value.details["period"] == "day"
    usage = await earnings.usage(NOW)
    assert usage["day"]["used"] == 2 and usage["month"]["used"] == 2
    assert usage["shared"] is False


async def test_new_day_month_and_dst_reset():
    budget = RequestBudget("p", 1, 2)
    await budget.consume(NOW)
    tomorrow = datetime(2026, 11, 18, 15, tzinfo=UTC)
    await budget.consume(tomorrow)
    with pytest.raises(ProviderQuotaExhaustedError):
        await budget.consume(datetime(2026, 11, 19, 15, tzinfo=UTC))
    await budget.consume(datetime(2026, 12, 1, 15, tzinfo=UTC))
    usage = await budget.usage(datetime(2026, 3, 8, 5, tzinfo=UTC))
    assert usage["day"]["resets_at"] == "2026-03-09T04:00:00+00:00"


async def test_unlimited_counts_and_daily_notice_blocks():
    budget = RequestBudget("p")
    for _ in range(10):
        await budget.consume(NOW)
    assert (await budget.usage(NOW))["day"]["used"] == 10
    assert await budget.remaining(NOW) is None
    await budget.exhaust_day(NOW)
    assert await budget.remaining(NOW) == 0
    with pytest.raises(ProviderQuotaExhaustedError):
        await budget.consume(NOW)


async def test_warning_once_per_period(caplog):
    budget = RequestBudget("p", 5, 5)
    for _ in range(5):
        await budget.consume(NOW)
    assert caplog.text.count("day budget at 80%") == 1
    assert caplog.text.count("month budget at 80%") == 1


async def test_redis_down_falls_back(monkeypatch):
    redis = AsyncMock()
    redis.eval.side_effect = ConnectionError()
    redis.mget.side_effect = ConnectionError()
    monkeypatch.setattr(module, "budget_redis", lambda: redis)
    budget = RequestBudget("p", 1, 0)
    await budget.consume(NOW)
    assert not (await budget.usage(NOW))["shared"]
    with pytest.raises(ProviderQuotaExhaustedError):
        await budget.consume(NOW)


async def test_redis_atomic_refusal_and_expiry(monkeypatch):
    redis = AsyncMock()
    redis.eval.side_effect = [[0, 1, 1, 0, 0], [2, 1, 1, 0, 0]]
    redis.mget.return_value = [b"1", b"1", None]
    monkeypatch.setattr(module, "budget_redis", lambda: redis)
    budget = RequestBudget("p", 0, 1)
    await budget.consume(NOW)
    with pytest.raises(ProviderQuotaExhaustedError) as error:
        await budget.consume(NOW)
    assert error.value.details["period"] == "month"
    assert (await budget.usage(NOW))["shared"]
    args = redis.eval.call_args.args
    assert args[1] == 5 and args[-1] > args[-2] > 0


async def test_concurrent_local_reservations_never_exceed_budget():
    budget = RequestBudget("p", 3, 0)
    results = await asyncio.gather(*(budget.consume(NOW) for _ in range(20)), return_exceptions=True)
    assert sum(value is None for value in results) == 3
    assert (await budget.usage(NOW))["day"]["used"] == 3
