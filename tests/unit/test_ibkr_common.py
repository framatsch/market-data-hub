from datetime import date, datetime
from decimal import Decimal

import pytest

from app.providers.ibkr_common import (
    exchange_timezone,
    format_occ_symbol,
    parse_occ_symbol,
    select_front_month,
    tws_trading_hours_open,
)


@pytest.mark.parametrize(
    ("symbol", "root", "right", "strike"),
    [
        ("AAPL  261218C00200000", "AAPL", "C", Decimal(200)),
        ("BRK B 261218P00350250", "BRK B", "P", Decimal("350.25")),
        ("ABC123261218P00000001", "ABC123", "P", Decimal("0.001")),
    ],
)
def test_occ_symbol_round_trip(symbol, root, right, strike):
    expiry = date(2026, 12, 18)
    assert parse_occ_symbol(symbol) == (root, expiry, right, strike)
    assert format_occ_symbol(root, expiry, right, strike) == symbol


@pytest.mark.parametrize(
    "symbol",
    [
        "AAPL-200C",
        "AAPL 261218C00200000",
        "AAPL  261232C00200000",
        "AAPL  261218X00200000",
        " AAPL 261218C00200000",
        "A  PL 261218C00200000",
        "AAPL  261218C0020000９",
        "AAPL  261218C00200000\n",
    ],
)
def test_parse_occ_symbol_rejects_invalid_ids(symbol):
    with pytest.raises(ValueError):
        parse_occ_symbol(symbol)


@pytest.mark.parametrize("strike", ["-1", "1.2345", "100000", "NaN", "Infinity"])
def test_format_occ_symbol_rejects_unrepresentable_strike(strike):
    with pytest.raises(ValueError):
        format_occ_symbol("AAPL", date(2026, 12, 18), "C", Decimal(strike))


def test_front_month_roll_buffer_includes_exact_seven_days_and_keeps_first_tie():
    as_of = date(2026, 12, 11)
    contracts = [
        (date(2027, 3, 19), "March"),
        (date(2026, 12, 17), "Too soon"),
        (date(2026, 12, 18), "December"),
        (date(2026, 12, 18), "Tie"),
    ]
    assert select_front_month(contracts, as_of) == "December"
    assert select_front_month(contracts, date(2026, 12, 12)) == "March"
    assert select_front_month(contracts[1:2], as_of) is None
    assert select_front_month([], as_of) is None


def test_tws_trading_hours_include_open_and_exclude_close():
    hours = "20261119:0400-20261119:2000;20261120:CLOSED"
    zone = exchange_timezone("US/Eastern")
    assert tws_trading_hours_open(hours, datetime(2026, 11, 19, 4, tzinfo=zone)) is True
    assert tws_trading_hours_open(hours, datetime(2026, 11, 19, 20, tzinfo=zone)) is False
    assert tws_trading_hours_open(hours, datetime(2026, 11, 20, 4, tzinfo=zone)) is False
    assert tws_trading_hours_open(hours, datetime(2026, 11, 21, 4, tzinfo=zone)) is None
