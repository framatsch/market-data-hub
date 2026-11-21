"""Provider-neutral earnings dates, results and per-symbol response status."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.market_hours import ET
from app.models.common import EnvelopeMeta

ReportTime = Literal["bmo", "amc", "during", "unknown"]
DateStatus = Literal["confirmed", "projected", "unknown"]
HistoryStatus = Literal["complete", "pending", "not_requested"]
SymbolStatusCode = Literal["ok", "not_applicable", "not_found", "error"]


def earnings_today() -> date:
    return datetime.now(ET).date()


class EarningsEvent(BaseModel):
    symbol: str
    report_date: date
    report_time: ReportTime = "unknown"
    date_status: DateStatus = "unknown"
    reported: bool = False
    fiscal_period_end: date | None = None
    eps_estimate: Decimal | None = Field(default=None, allow_inf_nan=False)
    eps_actual: Decimal | None = Field(default=None, allow_inf_nan=False)
    eps_surprise: Decimal | None = Field(default=None, allow_inf_nan=False)
    eps_surprise_pct: Decimal | None = Field(default=None, allow_inf_nan=False)
    revenue_estimate: Decimal | None = Field(default=None, allow_inf_nan=False)
    revenue_actual: Decimal | None = Field(default=None, allow_inf_nan=False)
    currency: str | None = None
    provider: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("revenue_estimate", "revenue_actual", mode="after")
    @classmethod
    def plain_revenue(cls, value: Decimal | None) -> Decimal | None:
        """Whole-number revenue without exponent notation (NUMERIC returns `1.14E+11`)."""
        return (
            Decimal(format(value, "f"))
            if value is not None and value.is_finite()
            else value
        )

    @model_validator(mode="after")
    def reporting_state(self) -> "EarningsEvent":
        if self.eps_actual is not None or self.report_date < earnings_today():
            self.reported = True
        if self.reported:
            self.date_status = "confirmed"
        return self


class EarningsSymbolStatus(BaseModel):
    symbol: str
    status: SymbolStatusCode = "ok"
    history: HistoryStatus = "not_requested"
    message: str | None = None


class EarningsMeta(EnvelopeMeta):
    provider: str
    symbols: list[EarningsSymbolStatus] = Field(default_factory=list)


class NextEarnings(BaseModel):
    symbol: str
    event: EarningsEvent | None = None
    days_until: int | None = None
    last_reported: EarningsEvent | None = None
    status: Literal["ok", "none_scheduled", "not_applicable", "error"]
    message: str | None = None
