import math
from datetime import date, timedelta
from decimal import Decimal

import pytest
import structlog

from app.models.volatility import VolatilityPoint
from app.services.volatility_service import _iv_statistics
from app.utils.errors import (
    CapabilityNotSupportedError,
    DataNotFoundError,
    DataValidationError,
)
from app.utils.symbols import parse_symbol


async def test_snapshot_provider_binding(volatility_env):
    result = await volatility_env.service.get_implied_volatility(parse_symbol("aapl"))
    volatility_env.lseg.get_implied_volatility.assert_awaited_once_with("AAPL", "stock", None)
    assert result.provider == "lseg"
    assert structlog.contextvars.get_contextvars()["provider"] == "lseg"


@pytest.mark.parametrize("operation,sec_type,tenor", [
    ("history", "future", 30), ("history", "stock", 60), ("history", "stock", 90),
    ("stats", "future", 30), ("stats", "index", 60),
])
async def test_unsupported_requests_rejected_before_provider(volatility_env, operation, sec_type, tenor):
    with pytest.raises(CapabilityNotSupportedError) as error:
        if operation == "history":
            await volatility_env.service.get_implied_volatility_history(
                parse_symbol("AAPL", sec_type), date(2026, 1, 1), date(2026, 11, 5), tenor, provider_name="ibkr"
            )
        else:
            await volatility_env.service.get_implied_volatility_stats(parse_symbol("AAPL", sec_type), tenor_days=tenor, provider_name="ibkr")
    assert error.value.details["provider"] == "ibkr"
    assert error.value.details["operation"] == operation
    volatility_env.ibkr.get_implied_volatility_history.assert_not_awaited()


async def test_provider_declaring_no_snapshot_support(volatility_env):
    volatility_env.lseg.volatility_sec_types = frozenset()
    with pytest.raises(CapabilityNotSupportedError):
        await volatility_env.service.get_implied_volatility(parse_symbol("AAPL"))
    volatility_env.lseg.get_implied_volatility.assert_not_awaited()


def test_spec_arithmetic_example():
    # The four-point spec illustrates arithmetic; the public service still needs 20 points.
    result = _iv_statistics([Decimal(value) for value in ("0.20", "0.10", "0.30", "0.25")])
    assert result == {"current": Decimal("0.25"), "min": Decimal("0.10"), "max": Decimal("0.30"),
                      "iv_rank": Decimal("75.00"), "iv_percentile": Decimal("66.67")}


async def test_stats_flat_window_and_history_range(volatility_env):
    result = await volatility_env.service.get_implied_volatility_stats(parse_symbol("AAPL"), window=20)
    assert result.iv_rank is None
    assert result.iv_percentile == Decimal("0.00")
    assert result.window_points == 20
    assert result.current == result.min == result.max == Decimal("0.2000")
    args = volatility_env.lseg.get_implied_volatility_history.call_args.args
    assert args[1] == date.today() - timedelta(days=math.ceil(20 * 365 / 252) + 14)
    assert args[2] == date.today()
    assert result.window_start == date.today() - timedelta(days=20)


async def test_stats_uses_sorted_last_window_and_strict_percentile(volatility_env):
    history = volatility_env.lseg.get_implied_volatility_history.return_value
    values = ["0.1"] * 5 + ["0.20", "0.10", "0.30"] * 7 + ["0.25"]
    history.points = [VolatilityPoint(date=date.today() - timedelta(days=len(values) - index), iv=value)
                      for index, value in enumerate(values)][::-1]
    result = await volatility_env.service.get_implied_volatility_stats(parse_symbol("AAPL"), window=22)
    assert result.window_points == 22
    assert result.iv_rank == Decimal("75.00")
    assert result.iv_percentile == Decimal("66.67")
    assert result.current == Decimal("0.2500")


async def test_insufficient_usable_history(volatility_env):
    history = volatility_env.lseg.get_implied_volatility_history.return_value
    history.points = history.points[:19] + [VolatilityPoint(date=date.today(), iv=None)]
    with pytest.raises(DataNotFoundError) as error:
        await volatility_env.service.get_implied_volatility_stats(parse_symbol("AAPL"))
    assert error.value.details == {"reason": "insufficient_history", "points": 19}


@pytest.mark.parametrize("window", [5, 757, "252", True])
async def test_invalid_window(volatility_env, window):
    with pytest.raises(DataValidationError):
        await volatility_env.service.get_implied_volatility_stats(parse_symbol("AAPL"), window=window)
    volatility_env.lseg.get_implied_volatility_history.assert_not_awaited()


async def test_lseg_supports_future_history_and_all_tenors(volatility_env):
    for tenor in (30, 60, 90):
        await volatility_env.service.get_implied_volatility_history(
            parse_symbol("F:ES"), date(2026, 1, 1), date(2026, 11, 5), tenor
        )
    assert volatility_env.lseg.get_implied_volatility_history.await_count == 3


async def test_results_carry_canonical_symbol(volatility_env):
    snapshot = await volatility_env.service.get_implied_volatility(parse_symbol("^spx"))
    assert snapshot.symbol == "I:SPX"
    volatility_env.lseg.get_implied_volatility.assert_awaited_once_with("SPX", "index", None)
    history = await volatility_env.service.get_implied_volatility_history(
        parse_symbol("ES", "future"), date(2026, 1, 1), date(2026, 11, 5)
    )
    assert history.symbol == "F:ES"
    stats = await volatility_env.service.get_implied_volatility_stats(
        parse_symbol("/ES"), window=20
    )
    assert stats.symbol == "F:ES"
    assert volatility_env.lseg.get_implied_volatility_history.call_args.args[0] == "ES"


async def test_option_type_is_rejected_before_provider(volatility_env):
    with pytest.raises(CapabilityNotSupportedError):
        await volatility_env.service.get_implied_volatility(
            parse_symbol("O:AAPL250117C00150000")
        )
    volatility_env.lseg.get_implied_volatility.assert_not_awaited()
