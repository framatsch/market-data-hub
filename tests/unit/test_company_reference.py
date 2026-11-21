"""Profiles of indices and sector ETFs come from the curated reference table."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.company import CompanyProfile
from app.providers.financialdatasets import FinancialDatasetsProvider
from app.services.company_service import CompanyService
from app.utils.errors import DataNotFoundError
from app.utils.symbols import PROFILE_TYPES, parse_symbol


def _service(provider: object | None) -> CompanyService:
    registry = MagicMock()
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=provider)
    manager.__aexit__ = AsyncMock(return_value=False)
    registry.use_company_provider.return_value = manager
    return CompanyService(registry)


def _etf_profile(**extra: object) -> CompanyProfile:
    return CompanyProfile(
        symbol="XLK", name="Tech ETF", exchange="ARCX", currency="USD", provider="polygon", **extra
    )


async def test_index_profile_needs_no_provider():
    service = _service(None)
    profile = await service.get_company_profile(parse_symbol("I:NDX", allowed=PROFILE_TYPES))
    assert profile.provider == "reference" and profile.name == "Nasdaq-100 Index"
    assert profile.symbol == "I:NDX"
    service.registry.use_company_provider.assert_not_called()


async def test_unknown_index_is_not_found():
    with pytest.raises(DataNotFoundError):
        await _service(None).get_company_profile(parse_symbol("I:ZZZZ", allowed=PROFILE_TYPES))


async def test_etf_gaps_are_filled_and_provider_values_win():
    provider = MagicMock(name="polygon")
    provider.name = "polygon"
    provider.get_company_profile = AsyncMock(return_value=_etf_profile())
    profile = await _service(provider).get_company_profile(parse_symbol("XLK"))
    assert profile.name == "Tech ETF"  # provider name kept
    assert profile.sector == "Information Technology" and profile.description
    assert profile.provider == "polygon"

    provider.get_company_profile.return_value = _etf_profile(sector="Tech", description="Own")
    profile = await _service(provider).get_company_profile(parse_symbol("XLK"))
    assert (profile.sector, profile.description) == ("Tech", "Own")


async def test_provider_not_found_falls_back_to_reference_only_when_known():
    provider = MagicMock()
    provider.name = "financialdatasets"
    provider.get_company_profile = AsyncMock(side_effect=DataNotFoundError("Company", "XLK"))
    profile = await _service(provider).get_company_profile(parse_symbol("XLK"))
    assert profile.provider == "reference" and profile.sector == "Information Technology"

    provider.get_company_profile.side_effect = DataNotFoundError("Company", "ZZZZ")
    with pytest.raises(DataNotFoundError):
        await _service(provider).get_company_profile(parse_symbol("ZZZZ"))


@pytest.mark.parametrize("row", [{"ticker": "XLK"}, {"name": None, "exchange": None}])
async def test_financialdatasets_etf_row_without_name_is_not_found(row):
    provider = FinancialDatasetsProvider.__new__(FinancialDatasetsProvider)
    provider._request = AsyncMock(return_value={"company_facts": row})
    with pytest.raises(DataNotFoundError):
        await provider.get_company_profile("XLK")


async def test_financialdatasets_null_exchange_does_not_break_profile():
    provider = FinancialDatasetsProvider.__new__(FinancialDatasetsProvider)
    provider._request = AsyncMock(
        return_value={"company_facts": {"name": "Apple Inc", "exchange": None, "sector": None}}
    )
    profile = await provider.get_company_profile("AAPL")
    assert profile.exchange == "" and profile.sector is None
