from functools import lru_cache
from typing import Annotated
from fastapi import Depends, HTTPException

from app.services.price_service import PriceService
from app.services.company_service import CompanyService
from app.services.options_service import OptionsService
from app.providers.base import BaseNewsProvider
from app.providers.registry import get_provider
from app.utils.errors import InvalidProviderError

@lru_cache
def get_price_service() -> PriceService:
    return PriceService()

@lru_cache
def get_company_service() -> CompanyService:
    return CompanyService()

@lru_cache
def get_options_service() -> OptionsService:
    return OptionsService()

PriceServiceDep = Annotated[PriceService, Depends(get_price_service)]
CompanyServiceDep = Annotated[CompanyService, Depends(get_company_service)]
OptionsServiceDep = Annotated[OptionsService, Depends(get_options_service)]


def get_news_provider(provider: str = "lseg") -> BaseNewsProvider:
    """
    Get news provider instance.

    Args:
        provider: Provider name ("lseg" or "ibkr")

    Returns:
        BaseNewsProvider instance

    Raises:
        HTTPException: If provider is invalid
    """
    try:
        return get_provider("news", provider)
    except InvalidProviderError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid news provider: {provider}. Available: lseg, ibkr"
        )
