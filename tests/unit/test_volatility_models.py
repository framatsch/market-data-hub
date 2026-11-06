from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.volatility import (
    ImpliedVolatilityTenor,
    VolatilityHistory,
    VolatilityPoint,
    VolatilitySnapshot,
    VolatilityStats,
    combine_iv,
    quantize_iv,
    uniform_tenors,
)
from app.providers.base import BaseVolatilityProvider
from app.utils.errors import CapabilityNotSupportedError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.2676", Decimal("0.2676")),
        (0.2519055923990361, Decimal("0.2519")),
        (Decimal("0.22345"), Decimal("0.2235")),
        (1.05, Decimal("1.0500")),
        (None, None),
        (float("nan"), None),
        (Decimal("NaN"), None),
        (float("inf"), None),
        (float("-inf"), None),
        (0, None),
        (-999, None),
        ("<NA>", None),
    ],
)
def test_quantize_iv(value, expected):
    assert quantize_iv(value) == expected


@pytest.mark.parametrize(
    ("call", "put", "combined", "expected"),
    [
        ("0.20", "0.30", None, Decimal("0.2500")),
        ("0.20", None, None, Decimal("0.2000")),
        (None, "0.30", None, Decimal("0.3000")),
        (None, None, "0.251905592", Decimal("0.2519")),
        (None, None, None, None),
        (float("nan"), -999, None, None),
        ("0.2001", "0.2000", None, Decimal("0.2001")),
    ],
)
def test_combine_iv(call, put, combined, expected):
    assert combine_iv(call, put, combined) == expected


def test_uniform_tenors_and_snapshot_shape():
    tenor = ImpliedVolatilityTenor(tenor_days=30, iv="0.251905592")
    tenors = uniform_tenors({30: tenor})
    assert [item.tenor_days for item in tenors] == [30, 60, 90]
    assert tenors[0].iv == Decimal("0.2519")
    assert tenors[1].model_dump() == {
        "tenor_days": 60, "iv_call": None, "iv_put": None, "iv": None
    }
    snapshot = VolatilitySnapshot(
        symbol="AAPL", sec_type="stock", method="provider_model_30d",
        source_instrument="AAPL", implied=[tenor], provider="ibkr",
    )
    assert snapshot.implied == tenors
    assert snapshot.model_dump(mode="json")["implied"][0]["iv"] == "0.2519"


@pytest.mark.parametrize("field,value", [("sec_type", "option"), ("method", "unknown")])
def test_snapshot_rejects_invalid_contract(field, value):
    fields = {
        "symbol": "AAPL", "sec_type": "stock", "method": "provider_atm_index",
        "source_instrument": "AAPLATMIV.U", "implied": [], "provider": "lseg",
    }
    fields[field] = value
    with pytest.raises(ValidationError):
        VolatilitySnapshot(**fields)


def test_history_sorts_and_normalizes_points():
    history = VolatilityHistory(
        symbol="AAPL", sec_type="stock", source_instrument="AAPLATMIV.U",
        tenor_days=30, provider="lseg", points=[
            VolatilityPoint(date=date(2026, 11, 5), iv="0.26765"),
            VolatilityPoint(date=date(2026, 11, 4), iv="0.2241"),
        ],
    )
    assert [point.date.day for point in history.points] == [4, 5]
    assert history.points[-1].iv == Decimal("0.2677")


def test_stats_precision():
    stats = VolatilityStats(
        symbol="AAPL", sec_type="stock", source_instrument="AAPLATMIV.U",
        tenor_days=30, provider="lseg", window=252, window_points=20,
        window_start=date(2026, 10, 1), window_end=date(2026, 11, 5),
        current="0.26765", min="0.162", max="0.3231",
        iv_rank="65.555", iv_percentile="74.123",
    )
    assert stats.current == Decimal("0.2677")
    assert stats.iv_rank == Decimal("65.56")
    assert stats.iv_percentile == Decimal("74.12")


def test_base_volatility_provider_is_abstract_and_configurable():
    with pytest.raises(TypeError):
        BaseVolatilityProvider()

    class Provider(BaseVolatilityProvider):
        async def get_implied_volatility(self, *args, **kwargs):
            pass

        async def get_implied_volatility_history(self, *args, **kwargs):
            pass

        async def test_connection(self):
            return {"success": True}

    provider = Provider()
    config = SimpleNamespace(
        timeout_seconds=10, retry_count=2, retry_backoff_seconds=1,
        rate_limit_per_sec=5, circuit_breaker_enabled=True,
        circuit_breaker_failure_threshold=3, circuit_breaker_reset_seconds=30,
        connection_config={},
    )
    provider.configure(config)
    assert provider._runtime_config is config
    assert provider.timeout_seconds == 10
    assert provider.volatility_tenors == frozenset()


@pytest.mark.asyncio
async def test_capability_error_maps_to_501():
    from app.main import app_error_handler

    error = CapabilityNotSupportedError(
        "ibkr", "history", sec_type="future", supported=["stock", "etf", "index"]
    )
    assert error.code == "CAPABILITY_NOT_SUPPORTED"
    assert error.details["supported"] == ["stock", "etf", "index"]
    response = await app_error_handler(SimpleNamespace(), error)
    assert response.status_code == 501
