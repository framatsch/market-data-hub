from typing import Any

from pydantic import BaseModel, Field


class ConnectionTestResult(BaseModel):
    status_code: int = Field(..., description="HTTP-like status code for the provider connection test")
    success: bool = Field(..., description="Whether the provider connection test succeeded")
    message: str = Field(..., description="Human-readable test result message")
    details: dict[str, Any] = Field(default_factory=dict, description="Provider-specific connection test details")
