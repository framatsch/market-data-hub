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

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None

class ErrorResponse(BaseModel):
    error: ErrorDetail

class ResponseEnvelope(BaseModel, Generic[T]):
    """Standard API response envelope."""
    data: T | None = None
    meta: dict[str, Any] | None = None
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float

class MarketStatus(BaseModel):
    market: str  # e.g. "open", "closed", "extended-hours"
    exchanges: dict[str, str] | None = None
    server_time: datetime
    provider: str
