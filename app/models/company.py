from typing import Optional
from pydantic import BaseModel, HttpUrl

class CompanySummary(BaseModel):
    symbol: str
    name: str
    exchange: str
    sector: Optional[str] = None
    provider: str

class CompanyProfile(BaseModel):
    symbol: str
    name: str
    description: Optional[str] = None
    exchange: str
    currency: str
    website: Optional[HttpUrl] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    employees: Optional[int] = None
    provider: str
