"""Guard the recorded free-tier responses used by Alpha Vantage provider tests."""

import csv
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "alphavantage"


def load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("name", ["cal_3m.csv", "cal_12m.csv"])
def test_calendar_fixture_retains_edge_cases(name):
    with (FIXTURES / name).open(newline="") as source:
        rows = list(csv.DictReader(source))

    assert len(rows) == 30
    assert set(rows[0]) == {
        "symbol", "name", "reportDate", "fiscalDateEnding", "estimate",
        "currency", "timeOfTheDay",
    }
    assert {row["timeOfTheDay"] for row in rows} == {
        "", "pre-market", "post-market",
    }
    assert any(not row["estimate"] for row in rows)
    assert {"BF.B", "LEN.B", "HEI.A", "JPM-PD", "KEY-PL"} <= {
        row["symbol"] for row in rows
    }


@pytest.mark.parametrize("name", ["earn_AAPL.json", "earn_BRK-B.json"])
def test_full_earnings_history_fixture(name):
    history = load_json(name)
    assert history["annualEarnings"]
    assert len(history["quarterlyEarnings"]) > 100
    assert any(
        value == "None"
        for quarter in history["quarterlyEarnings"]
        for value in quarter.values()
    )


@pytest.mark.parametrize(
    "name", ["earn_BRK.B.json", "earn_SPY.json", "earn_UNKNOWN.json"]
)
def test_missing_earnings_fixture(name):
    assert load_json(name) == {}


@pytest.mark.parametrize(
    "name", ["daily_compact_AAPL.json", "daily_compact_SPY.json"]
)
def test_daily_fixture_keeps_full_compact_window(name):
    assert len(load_json(name)["Time Series (Daily)"]) == 100


def test_weekly_fixture_keeps_split_and_full_history():
    bars = load_json("weekly_AAPL.json")["Weekly Time Series"]
    assert len(bars) > 1400
    assert float(bars["2020-08-28"]["4. close"]) > 490
    assert float(bars["2020-09-04"]["4. close"]) < 130


def test_quote_fixture_keeps_trading_day():
    quote = load_json("quote_AAPL.json")["Global Quote"]
    assert quote["01. symbol"] == "AAPL"
    assert quote["07. latest trading day"]


@pytest.mark.parametrize("name", ["daily_full_AAPL.json", "daily_adj_AAPL.json"])
def test_premium_notice_fixture(name):
    assert "premium" in load_json(name)["Information"].lower()


def test_burst_notice_fixture_retains_ambiguous_limit_text():
    notice = load_json("burst_limit.json")["Information"]
    assert "1 request per second" in notice
    assert "25 requests per day" in notice
    assert "premium endpoints" in notice
