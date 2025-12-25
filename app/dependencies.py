from functools import lru_cache
from typing import Annotated
from fastapi import Depends

from app.services.price_service import PriceService
from app.services.company_service import CompanyService
from app.services.options_service import OptionsService

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
