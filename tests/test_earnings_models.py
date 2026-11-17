from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.earnings import (
    EarningsEvent,
    EarningsMeta,
    EarningsSymbolStatus,
    NextEarnings,
)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.models.earnings.earnings_today", lambda: date(2026, 11, 17))


def event(**kwargs):
    return EarningsEvent(symbol="AAPL", provider="alphavantage", **kwargs)


def test_past_event_is_reported_without_actual():
    value = event(report_date=date(2026, 11, 14))
    assert value.reported
    assert value.date_status == "confirmed"
    assert value.eps_actual is None


def test_zero_actual_is_reported_and_decimal():
    value = event(report_date=date(2026, 11, 17), eps_actual="0", eps_estimate="1.25")
    assert value.reported
    assert value.eps_actual == Decimal(0)
    assert value.eps_estimate == Decimal("1.25")


def test_unknown_upcoming_confirmation_is_preserved():
    value = event(report_date=date(2027, 1, 28))
    assert not value.reported
    assert value.date_status == "unknown"
    assert value.report_time == "unknown"


@pytest.mark.parametrize("changes", [
    {"report_time": "afternoon"}, {"date_status": "estimated"}, {"eps_actual": "NaN"},
])
def test_invalid_values(changes):
    with pytest.raises(ValidationError):
        event(report_date=date(2027, 1, 28), **changes)


def test_batch_metadata_and_next_shape():
    meta = EarningsMeta(provider="alphavantage", stale=False, symbols=[
        EarningsSymbolStatus(symbol="AAPL", history="pending"),
    ])
    assert meta.model_dump(mode="json")["symbols"][0]["history"] == "pending"
    value = NextEarnings(symbol="AAPL", status="none_scheduled")
    assert value.event is None and value.days_until is None
