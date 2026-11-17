from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.admin.settings_repository import SettingsRepository
from app.main import app_error_handler
from app.models.earnings import (
    EarningsEvent,
    EarningsMeta,
    EarningsSymbolStatus,
    NextEarnings,
)
from app.providers.base import BaseEarningsProvider
from app.providers.registry import ProviderRegistry
from app.utils.errors import AppError, InvalidProviderError, ProviderQuotaExhaustedError


class FakeEarningsProvider(BaseEarningsProvider):
    name = "fake"

    async def get_upcoming_earnings(self, start, end, roots):
        return []

    async def get_earnings_history(self, root):
        return []

    async def test_connection(self):
        return {"success": True}


def make_registry(monkeypatch):
    monkeypatch.setattr(ProviderRegistry, "_initialize_providers", lambda self: None)
    return ProviderRegistry()


def test_reporting_state_and_decimal():
    event = EarningsEvent(
        symbol="AAPL", report_date=date.today() - timedelta(days=3),
        provider="fake", eps_estimate="1.23",
    )
    assert event.reported and event.date_status == "confirmed"
    assert event.eps_estimate == Decimal("1.23")
    assert event.eps_actual is None and event.report_time == "unknown"
    future = event.model_dump() | {"report_date": date.today() + timedelta(days=10), "reported": False, "date_status": "unknown", "eps_actual": Decimal(0)}
    assert EarningsEvent(**future).reported


def test_next_and_meta_shape():
    row = NextEarnings(symbol="SPY", status="not_applicable")
    assert row.event is None and row.days_until is None
    meta = EarningsMeta(
        provider="fake", data_as_of=datetime.now(UTC), stale=False,
        symbols=[EarningsSymbolStatus(symbol="AAPL", history="pending")],
    ).model_dump(mode="json")
    assert meta["provider"] == "fake" and meta["stale"] is False
    assert meta["symbols"][0]["history"] == "pending"


async def test_registry_default_capability_and_lease(monkeypatch):
    reg = make_registry(monkeypatch)
    reg._providers = {"fake": FakeEarningsProvider(), "other": object()}
    reg._apply_default_settings({"default_earnings_provider": "fake"})
    assert reg.get_earnings_provider().name == "fake"
    assert reg.list_available_providers()["earnings"] == ["fake"]
    async with reg.use_earnings_provider() as provider:
        assert reg._provider_inflight[id(provider)] == 1
    assert not reg._provider_inflight
    with pytest.raises(InvalidProviderError):
        reg.get_earnings_provider("other")
    reg._apply_default_settings({"default_earnings_provider": "other"})
    assert reg.default_earnings_provider is None
    with pytest.raises(AppError, match="No earnings provider configured"):
        reg.get_earnings_provider()


async def test_fresh_install_and_allowlist(monkeypatch, tmp_path):
    repo = SettingsRepository(str(tmp_path / "settings.db"))
    reg = make_registry(monkeypatch)
    reg._apply_default_settings(await repo.get_all())
    assert reg.default_earnings_provider is None
    await repo.set("default_earnings_provider", "fake")
    assert await repo.get("default_earnings_provider") == "fake"


async def test_quota_error_maps_to_http_429():
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)

    @app.get("/quota")
    def quota():
        raise ProviderQuotaExhaustedError("alphavantage", "day", 25)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/quota")
    assert response.status_code == 429
    assert response.json()["error"]["details"] == {
        "provider": "alphavantage", "period": "day", "budget": 25,
    }
