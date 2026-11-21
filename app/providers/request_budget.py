"""Atomic day/month request budgets shared by all capabilities of a provider."""

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any

from app.market_hours import ET, as_utc
from app.observability.metrics import UPSTREAM_REQUESTS
from app.utils.errors import ProviderQuotaExhaustedError

logger = logging.getLogger(__name__)
BUDGET_DEFAULTS = {
    "alphavantage": (25, 0),
    "financialdatasets": (0, 1000),
    "earningsapi": (100, 1000),
}

# Check both limits before either increment. The block key also handles an
# upstream daily notice when the administrator configured an unlimited budget.
_RESERVE = """
local d = tonumber(redis.call('GET', KEYS[1]) or '0')
local m = tonumber(redis.call('GET', KEYS[2]) or '0')
if redis.call('EXISTS', KEYS[3]) == 1 or (tonumber(ARGV[1]) > 0 and d >= tonumber(ARGV[1])) then
    return {1, d, m, 0, 0}
end
if tonumber(ARGV[2]) > 0 and m >= tonumber(ARGV[2]) then return {2, d, m, 0, 0} end
d = redis.call('INCR', KEYS[1]); redis.call('EXPIRE', KEYS[1], ARGV[3])
m = redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], ARGV[4])
local wd = 0; local wm = 0
if tonumber(ARGV[1]) > 0 and d >= tonumber(ARGV[1]) * 0.8 then
    if redis.call('SET', KEYS[4], '1', 'NX', 'EX', ARGV[3]) then wd = 1 end
end
if tonumber(ARGV[2]) > 0 and m >= tonumber(ARGV[2]) * 0.8 then
    if redis.call('SET', KEYS[5], '1', 'NX', 'EX', ARGV[4]) then wm = 1 end
end
return {0, d, m, wd, wm}
"""
_EXHAUST = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
used = math.max(used, tonumber(ARGV[1]))
redis.call('SET', KEYS[1], used, 'EX', ARGV[2])
redis.call('SET', KEYS[2], '1', 'EX', ARGV[2])
return used
"""


@dataclass
class LocalCounters:
    day: str = ""
    month: str = ""
    day_used: int = 0
    month_used: int = 0
    blocked: bool = False
    warned: set[str] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_local: dict[str, LocalCounters] = {}


def budget_redis() -> Any:
    # Lazy import: registry imports providers, while cache imports the registry.
    from app import cache

    backend = cache._backend
    return backend.redis if backend is not None else None


class RequestBudget:
    def __init__(self, provider: str, day: int = 0, month: int = 0):
        self.provider = provider
        self.day_budget = day
        self.month_budget = month
        self.shared = False

    def configure(self, connection_config: dict[str, Any]) -> None:
        day, month = BUDGET_DEFAULTS.get(self.provider, (0, 0))
        self.day_budget = connection_config.get("request_budget_per_day", day)
        self.month_budget = connection_config.get("request_budget_per_month", month)

    def _periods(self, now: datetime):
        now = as_utc(now)
        local = now.astimezone(ET)
        day = local.date().isoformat()
        month = now.strftime("%Y-%m")
        day_reset = datetime.combine(local.date() + timedelta(days=1), time(), ET)
        month_reset = datetime(
            now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=UTC
        )
        keys = [
            f"mdh:quota:{self.provider}:d:{day}",
            f"mdh:quota:{self.provider}:m:{month}",
            f"mdh:quota:{self.provider}:blocked:{day}",
            f"mdh:quota:{self.provider}:warn:d:{day}",
            f"mdh:quota:{self.provider}:warn:m:{month}",
        ]
        return day, month, as_utc(day_reset), month_reset, keys

    def _counters(self, day: str, month: str) -> LocalCounters:
        counters = _local.setdefault(self.provider, LocalCounters())
        if counters.day != day:
            counters.day, counters.day_used, counters.blocked = day, 0, False
            counters.warned.discard("day")
        if counters.month != month:
            counters.month, counters.month_used = month, 0
            counters.warned.discard("month")
        return counters

    def _warning(self, period: str, used: int, budget: int) -> None:
        logger.warning(
            "Provider %s %s budget at 80%% (%s/%s)", self.provider, period, used, budget
        )

    async def consume(self, now: datetime | None = None) -> None:
        """Reserve one actual upstream attempt; refusals never increment counters."""
        now = as_utc(now or datetime.now(UTC))
        day, month, day_reset, month_reset, keys = self._periods(now)
        counters = self._counters(day, month)
        async with counters.lock:
            redis = budget_redis()
            result = None
            if redis is not None:
                try:
                    result = await redis.eval(
                        _RESERVE,
                        5,
                        *keys,
                        self.day_budget,
                        self.month_budget,
                        max(1, math.ceil((day_reset - now).total_seconds())),
                        max(1, math.ceil((month_reset - now).total_seconds())),
                    )
                    self.shared = True
                    counters.day_used, counters.month_used = (
                        int(result[1]),
                        int(result[2]),
                    )
                    if result[3]:
                        counters.warned.add("day")
                        self._warning("day", counters.day_used, self.day_budget)
                    if result[4]:
                        counters.warned.add("month")
                        self._warning("month", counters.month_used, self.month_budget)
                except Exception:
                    self.shared = False
            else:
                self.shared = False
            if result is not None and int(result[0]):
                period = "day" if int(result[0]) == 1 else "month"
                raise ProviderQuotaExhaustedError(
                    self.provider,
                    period,
                    self.day_budget if period == "day" else self.month_budget,
                )
            if result is None:
                if counters.blocked or (
                    self.day_budget and counters.day_used >= self.day_budget
                ):
                    raise ProviderQuotaExhaustedError(
                        self.provider, "day", self.day_budget
                    )
                if self.month_budget and counters.month_used >= self.month_budget:
                    raise ProviderQuotaExhaustedError(
                        self.provider, "month", self.month_budget
                    )
                counters.day_used += 1
                counters.month_used += 1
                for period, used, budget in (
                    ("day", counters.day_used, self.day_budget),
                    ("month", counters.month_used, self.month_budget),
                ):
                    if (
                        budget
                        and used >= budget * 0.8
                        and period not in counters.warned
                    ):
                        counters.warned.add(period)
                        self._warning(period, used, budget)
        UPSTREAM_REQUESTS.labels(self.provider).inc()

    async def exhaust_day(self, now: datetime | None = None) -> None:
        """Called ONLY for an explicit upstream daily-quota exhaustion notice."""
        now = as_utc(now or datetime.now(UTC))
        day, month, reset, _, keys = self._periods(now)
        counters = self._counters(day, month)
        async with counters.lock:
            counters.blocked = True
            counters.day_used = max(counters.day_used, self.day_budget)
            redis = budget_redis()
            if redis is not None:
                try:
                    await redis.eval(
                        _EXHAUST,
                        2,
                        keys[0],
                        keys[2],
                        self.day_budget,
                        max(1, math.ceil((reset - now).total_seconds())),
                    )
                    self.shared = True
                except Exception:
                    self.shared = False

    async def usage(self, now: datetime | None = None) -> dict[str, Any]:
        now = as_utc(now or datetime.now(UTC))
        day, month, day_reset, month_reset, keys = self._periods(now)
        counters = self._counters(day, month)
        async with counters.lock:
            redis = budget_redis()
            self.shared = False
            if redis is not None:
                try:
                    values = await redis.mget(keys[:3])
                    counters.day_used = int(values[0] or 0)
                    counters.month_used = int(values[1] or 0)
                    counters.blocked = bool(values[2])
                    self.shared = True
                except Exception:
                    pass
            return {
                "provider": self.provider,
                "day": {
                    "used": counters.day_used,
                    "budget": self.day_budget,
                    "resets_at": day_reset.isoformat(),
                },
                "month": {
                    "used": counters.month_used,
                    "budget": self.month_budget,
                    "resets_at": month_reset.isoformat(),
                },
                "shared": self.shared,
                "day_exhausted": counters.blocked,
            }

    async def remaining(self, now: datetime | None = None) -> int | None:
        usage = await self.usage(now)
        if usage["day_exhausted"]:
            return 0
        limits = [
            max(0, usage[p]["budget"] - usage[p]["used"])
            for p in ("day", "month")
            if usage[p]["budget"]
        ]
        return min(limits) if limits else None
