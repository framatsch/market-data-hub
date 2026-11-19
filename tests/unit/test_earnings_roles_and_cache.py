"""Role composition, kind filtering and the store-less mode of per-symbol providers."""

import json
from datetime import date

import pytest

from app.models.earnings import EarningsEvent
from app.providers.base import BaseEarningsHistoryProvider, BaseEarningsUpcomingProvider
from app.providers.registry import ProviderRegistry
from app.services import earnings_service as module
from app.services.earnings_service import (
    EarningsService,
    merge_ephemeral,
    parse_symbol_list,
)
from app.utils.errors import AppError, CapabilityNotSupportedError, DataNotFoundError

TODAY = date(2026, 11, 18)


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value


def ev(symbol, day, provider, **kwargs):
    return EarningsEvent(symbol=symbol, report_date=day, provider=provider, **kwargs)


class Upcoming(BaseEarningsUpcomingProvider, BaseEarningsHistoryProvider):
    name = "earningsapi"
    upcoming_mode = "symbol"
    earnings_day_calendar = True

    def __init__(self):
        self.day_calls, self.symbol_calls = [], []

    async def get_earnings_for_date(self, day):
        self.day_calls.append(day)
        return [ev("ADI", day, self.name)] if day == date(2026, 11, 24) else []

    async def get_symbol_earnings(self, root):
        self.symbol_calls.append(root)
        if root != "NVDA":
            raise DataNotFoundError("Earnings", root)
        return [ev("NVDA", date(2027, 2, 18), self.name), ev("NVDA", date(2026, 8, 20), self.name, eps_actual="1")]

    async def get_earnings_history(self, root):
        return [e for e in await self.get_symbol_earnings(root) if e.reported]

    async def test_connection(self):
        return {}


class History(BaseEarningsHistoryProvider):
    name = "financialdatasets"

    def __init__(self):
        self.calls = []

    async def get_earnings_history(self, root):
        self.calls.append(root)
        return [
            ev(root, date(2026, 8, 19), self.name, eps_actual="3"),
            ev(root, date(2026, 11, 24), self.name, eps_actual="4"),  # report day, as filed
        ]

    async def test_connection(self):
        return {}


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "earnings_today", lambda: TODAY)
    monkeypatch.setattr(module, "budget_redis", lambda: None)


def build(providers, upcoming=None, history=None):
    registry = ProviderRegistry.__new__(ProviderRegistry)
    registry._providers = {p.name: p for p in providers}
    registry.default_earnings_upcoming_provider = upcoming
    registry.default_earnings_history_provider = history
    registry._provider_locks, registry._provider_inflight, registry._provider_drained = {}, {}, {}
    return EarningsService(registry)


def syms(text):
    return parse_symbol_list(text)


async def test_forward_from_one_provider_history_from_another():
    up, hist = Upcoming(), History()
    svc = build([up, hist], "earningsapi", "financialdatasets")
    result = await svc.company(syms("ADI")[0], date(2026, 1, 1), date(2027, 6, 1))
    assert result.provider is None
    assert result.providers == {"upcoming": "earningsapi", "history": "financialdatasets"}
    by_date = {e.report_date: e for e in result.events}
    assert by_date[date(2026, 8, 19)].provider == "financialdatasets"
    # Report day overlap: the reported filing wins over the announced event.
    assert by_date[date(2026, 11, 24)].reported and by_date[date(2026, 11, 24)].provider == "financialdatasets"
    assert len([e for e in result.events if e.report_date == date(2026, 11, 24)]) == 1


async def test_one_provider_for_both_roles_is_not_composed():
    up = Upcoming()
    svc = build([up], "earningsapi", "earningsapi")
    result = await svc.company(syms("NVDA")[0], date(2026, 1, 1), date(2027, 6, 1))
    assert result.provider == "earningsapi" and result.providers is None


async def test_next_uses_upcoming_role_only():
    up, hist = Upcoming(), History()
    svc = build([up, hist], "earningsapi", "financialdatasets")
    result = await svc.next(syms("ADI"))
    assert result.rows[0].event.report_date == date(2026, 11, 24) and hist.calls == []
    assert result.provider == "earningsapi"


async def test_explicit_history_only_provider_with_kind_all_and_501():
    up, hist = Upcoming(), History()
    svc = build([up, hist], "earningsapi", "financialdatasets")
    result = await svc.company(syms("ADI")[0], date(2026, 1, 1), date(2027, 6, 1), "financialdatasets")
    assert result.provider == "financialdatasets" and all(e.reported for e in result.events)
    with pytest.raises(CapabilityNotSupportedError) as error:
        await svc.next(syms("AAPL"), "financialdatasets")
    assert error.value.details["supported"] == ["earningsapi"] or "earningsapi" in str(error.value.details["supported"])
    assert "only delivers reported earnings" in error.value.message
    with pytest.raises(CapabilityNotSupportedError):
        await svc.calendar(syms("AAPL"), date(2026, 11, 1), date(2026, 12, 1), "financialdatasets", "upcoming")


async def test_missing_role_contributes_nothing_and_both_missing_is_503():
    up = Upcoming()
    svc = build([up], "earningsapi", None)
    result = await svc.calendar(syms("ADI"), date(2026, 11, 1), date(2026, 12, 31))
    assert result.events and "no history earnings provider configured" in (result.symbols[0].message or "")
    with pytest.raises(AppError) as error:
        await build([up]).calendar(syms("ADI"), date(2026, 11, 1), date(2026, 12, 31))
    assert error.value.message == "No earnings provider configured — enable a provider in the admin UI"
    with pytest.raises(AppError) as error:
        await svc.calendar(syms("ADI"), date(2026, 11, 1), date(2026, 12, 31), kind="reported")
    assert "history" in error.value.message


async def test_kind_upcoming_and_reported_filter():
    up = Upcoming()
    svc = build([up], "earningsapi", "earningsapi")
    upcoming = await svc.company(syms("NVDA")[0], date(2026, 1, 1), date(2027, 6, 1), None, "upcoming")
    assert [e.report_date for e in upcoming.events] == [date(2027, 2, 18)]
    up.day_calls.clear()
    reported = await svc.company(syms("NVDA")[0], date(2026, 1, 1), date(2027, 6, 1), None, "reported")
    assert [e.report_date for e in reported.events] == [date(2026, 8, 20)]
    assert up.day_calls == []  # kind=reported requests no day calendar


async def test_without_store_each_day_and_symbol_is_requested_once(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(module, "budget_redis", lambda: redis)
    up = Upcoming()
    svc = build([up], "earningsapi", "earningsapi")
    first = await svc.next(syms("NVDA,ADI"))
    second = await svc.next(syms("NVDA,ADI"))
    assert len(up.day_calls) == len(set(up.day_calls)) == 9
    assert up.symbol_calls == ["NVDA"]
    by = {r.symbol: r for r in second.rows}
    assert by["ADI"].event.report_date == date(2026, 11, 24)
    assert by["NVDA"].event.report_date == date(2027, 2, 18)
    assert {r.symbol: r.status for r in first.rows} == {r.symbol: r.status for r in second.rows}
    assert any(key.startswith("mdh:earnings:provider-day:earningsapi:") for key in redis.data)
    assert json.loads(redis.data["mdh:earnings:provider-symbol:earningsapi:NVDA"])["events"]


def test_merge_ephemeral_day_wins_for_moved_dates():
    moved = {"ADI": [ev("ADI", date(2026, 12, 9), "x"), ev("ADI", date(2026, 8, 19), "x", eps_actual="1")]}
    days = {date(2026, 11, 24): [ev("ADI", date(2026, 11, 24), "x")]}
    merged = merge_ephemeral(days, moved, TODAY)
    assert sorted(e.report_date for e in merged) == [date(2026, 8, 19), date(2026, 11, 24)]
