from typing import Generic, TypeVar, Optional
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[dict] = None

class ErrorResponse(BaseModel):
    error: ErrorDetail

class ResponseEnvelope(BaseModel, Generic[T]):
    """Standard API response envelope."""
    data: Optional[T] = None
    meta: Optional[dict] = None
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
