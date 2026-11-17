# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""LSEG company profile/search via the Search API (no DataGrid scope)."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.providers.lseg import LSEGProvider, _lseg_ticker_symbol, _trbc_sector_industry
from app.utils.errors import DataNotFoundError, ProviderNotEntitledError

AAPL_ROW = {
    "RIC": "AAPL.O",
    "TickerSymbol": "AAPL",
    "CommonName": "APPLE ORD",
    "IssuerCommonName": "Apple Inc.",
    "ExchangeName": "NASDAQ Global Select Consolidated",
    "ExchangeCode": "NSQ",
    "Currency": "USD",
    "RCSTRBC2012Name": (
        "Technology\\Technology Equipment\\Computers, Phones & Household Electronics"
        "\\Phones & Handheld Devices\\Phones & Smart Phones"
    ),
    "RCSTRBC2012Leaf": "Phones & Smart Phones",
    "NumberOfEmployees": 166000,
}


@pytest.fixture
def lseg_provider():
    with patch("app.providers.lseg.REFINITIV_AVAILABLE", True):
        with patch("app.providers.lseg.rd"):
            provider = LSEGProvider()
            provider._get_session = MagicMock()  # type: ignore[method-assign]
            provider._throttle = MagicMock()  # type: ignore[method-assign]
            yield provider


def _search_returning(rows):
    definition = MagicMock()
    definition.get_data.return_value.data.df = pd.DataFrame(rows)
    return patch("app.providers.lseg.search.Definition", return_value=definition)


@pytest.mark.asyncio
async def test_company_profile_maps_search_record(lseg_provider):
    lseg_provider._ticker_to_ric = MagicMock(return_value="AAPL.O")
    with _search_returning([AAPL_ROW]) as definition:
        profile = await lseg_provider.get_company_profile("AAPL")

    assert definition.call_args.kwargs["filter"] == "RIC eq 'AAPL.O'"
    assert profile.name == "Apple Inc."
    assert profile.exchange == "NASDAQ Global Select Consolidated"
    assert profile.currency == "USD"
    assert profile.sector == "Technology"
    assert profile.industry == "Phones & Handheld Devices"
    assert profile.employees == 166000
    assert profile.website is None and profile.description is None
    assert profile.provider == "lseg"


@pytest.mark.asyncio
async def test_company_profile_without_record_is_not_found(lseg_provider):
    lseg_provider._ticker_to_ric = MagicMock(return_value="ZZZ.O")
    with _search_returning([]):
        with pytest.raises(DataNotFoundError):
            await lseg_provider.get_company_profile("ZZZ")


@pytest.mark.asyncio
async def test_company_profile_missing_optional_fields(lseg_provider):
    lseg_provider._ticker_to_ric = MagicMock(return_value="X.N")
    row = {"RIC": "X.N", "TickerSymbol": "X", "CommonName": "X ORD"}
    with _search_returning([row]):
        profile = await lseg_provider.get_company_profile("X")

    assert profile.name == "X ORD"
    assert profile.exchange == "UNKNOWN"
    assert profile.sector is None and profile.industry is None
    assert profile.employees is None


@pytest.mark.asyncio
async def test_search_companies_returns_tickers(lseg_provider):
    other = {**AAPL_ROW, "TickerSymbol": "APLE", "IssuerCommonName": "Apple Hospitality REIT Inc"}
    no_ticker = {**AAPL_ROW, "TickerSymbol": None}
    with _search_returning([AAPL_ROW, other, no_ticker]) as definition:
        results = await lseg_provider.search_companies("apple")

    assert definition.call_args.kwargs["query"] == "apple"
    assert "IsPrimaryRIC eq true" in definition.call_args.kwargs["filter"]
    assert [r.symbol for r in results] == ["AAPL", "APLE"]
    assert results[0].name == "Apple Inc."
    assert results[0].sector == "Technology"
    assert all(r.provider == "lseg" for r in results)


@pytest.mark.asyncio
async def test_search_companies_empty_falls_back_to_unfiltered(lseg_provider):
    with _search_returning([]) as definition:
        assert await lseg_provider.search_companies("nothing") == []

    assert definition.call_count == 2
    assert "filter" not in definition.call_args_list[1].kwargs


def test_ticker_to_ric_prefers_us_primary_quote(lseg_provider):
    definition = MagicMock()
    definition.get_data.return_value.data.df = pd.DataFrame([{"RIC": "SPY"}])
    with patch("app.providers.lseg.search.Definition", return_value=definition) as d:
        assert lseg_provider._ticker_to_ric("SPY") == "SPY"

    first = d.call_args_list[0].kwargs
    assert first["filter"] == (
        "TickerSymbol eq 'SPY' and ExchangeCountry eq 'USA' and IsPrimaryRIC eq true"
    )


@pytest.mark.asyncio
async def test_search_scope_error_is_not_entitled(lseg_provider):
    definition = MagicMock()
    definition.get_data.side_effect = RuntimeError("Insufficient scope for key=/search")
    with patch("app.providers.lseg.search.Definition", return_value=definition):
        with pytest.raises(ProviderNotEntitledError):
            await lseg_provider.search_companies("apple")


def test_trbc_levels():
    assert _trbc_sector_industry({"RCSTRBC2012Name": "Financials\\Banking"}) == (
        "Financials",
        "Banking",
    )
    assert _trbc_sector_industry({"RCSTRBC2012Leaf": "Banks"}) == (None, "Banks")


@pytest.mark.parametrize(
    ("ticker", "expected"),
    [("BRK.B", "BRK B"), ("BF-B", "BF B"), ("heI/a", "HEI A"), ("AAPL", "AAPL"), ("SPY", "SPY")],
)
def test_lseg_ticker_symbol_share_classes(ticker, expected):
    assert _lseg_ticker_symbol(ticker) == expected


def test_ticker_to_ric_share_class_uses_active_issue_quote(lseg_provider):
    empty = MagicMock()
    empty.get_data.return_value.data.df = pd.DataFrame()
    found = MagicMock()
    found.get_data.return_value.data.df = pd.DataFrame([{"RIC": "BRKb"}])
    with patch("app.providers.lseg.search.Definition", side_effect=[empty, found]) as d:
        assert lseg_provider._ticker_to_ric("BRK.B") == "BRKb"

    second = d.call_args_list[1].kwargs["filter"]
    assert second.startswith("TickerSymbol eq 'BRK B' and ")
    assert "AssetState eq 'AC'" in second and "IsPrimaryIssueRIC eq true" in second
