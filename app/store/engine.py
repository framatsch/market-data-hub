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

"""Async engine, state and fail-open guard of the history store (design D1, D10)."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal, TypeVar
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

from app.config import settings
from app.observability.telemetry import span

logger = logging.getLogger(__name__)
T = TypeVar("T")
StoreState = Literal["disabled", "connected", "unavailable"]
COOLDOWN_SECONDS = 30.0

_engine: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None
_state: StoreState = "disabled"
_retry_at = 0.0
_failed = False


def async_database_url(url: str) -> str:
    """Normalise `postgres://` and `postgresql://` to the asyncpg driver."""
    parsed = make_url(url)
    if parsed.drivername in {"postgres", "postgresql", "postgresql+psycopg2"}:
        parsed = parsed.set(drivername="postgresql+asyncpg")
    return parsed.render_as_string(hide_password=False)


def redacted_database_url(url: str | None = None) -> str:
    """Database URL without user name and password."""
    raw = settings.DATABASE_URL if url is None else url
    if not raw:
        return ""
    parsed = urlsplit(raw)
    return urlunsplit(
        (parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", "")
    )


def store_state() -> StoreState:
    return _state


def store_enabled() -> bool:
    """True when the store is configured and not in its error cooldown."""
    return _state != "disabled" and _sessions is not None


def store_usable() -> bool:
    return (
        _state == "connected"
        and _sessions is not None
        and time.monotonic() >= _retry_at
    )


def failed(exc: BaseException) -> None:
    """Fail-open: one warning, skip the store for 30 s."""
    global _failed, _retry_at
    if not _failed:
        logger.warning(
            "History store unavailable (%s); serving from the provider (retry in %ds)",
            type(exc).__name__,
            int(COOLDOWN_SECONDS),
        )
    _failed = True
    _retry_at = time.monotonic() + COOLDOWN_SECONDS


def recovered() -> None:
    global _failed, _retry_at
    if _failed:
        logger.info("History store recovered")
    _failed = False
    _retry_at = 0.0


async def guarded(call: Callable[[], Awaitable[T]], default: T) -> T:
    """Run a store call; on a database error log once and return `default`."""
    if not store_usable():
        return default
    try:
        result = await call()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        failed(exc)
        return default
    recovered()
    return result


@asynccontextmanager
async def session_scope(
    *, operation: Literal["read", "write"] = "read"
) -> AsyncIterator[AsyncSession]:
    """Transactional session; raises when the store is off (callers use `guarded`)."""
    if _sessions is None:
        raise RuntimeError("History store is not configured")
    async with span("db", operation), _sessions() as session, session.begin():
        yield session


def set_session_factory(
    factory: async_sessionmaker[AsyncSession] | None,
    state: StoreState = "connected",
) -> None:
    """Install a session factory directly (tests)."""
    global _sessions, _state, _retry_at, _failed
    _sessions = factory
    _state = state if factory is not None else "disabled"
    _retry_at = 0.0
    _failed = False


def get_engine() -> AsyncEngine | None:
    return _engine


async def setup_store() -> StoreState:
    """Open the pool, migrate, and report `disabled`, `connected` or `unavailable`."""
    global _engine, _sessions, _state
    await shutdown_store()
    if not settings.DATABASE_URL:
        logger.info("History store disabled (DATABASE_URL not set)")
        return "disabled"
    _engine = _create_async_engine(
        async_database_url(settings.DATABASE_URL), pool_pre_ping=True, pool_size=5
    )
    _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    _state = "unavailable"
    try:
        from app.store.migrate import ensure_schema

        await ensure_schema(_engine, migrate=settings.HISTORY_STORE_MIGRATE_ON_STARTUP)
        _state = "connected"
        logger.info(
            "History store connected: %s", redacted_database_url(settings.DATABASE_URL)
        )
    except Exception as exc:
        logger.warning(
            "History store unavailable at startup (%s): %s",
            type(exc).__name__,
            redacted_database_url(settings.DATABASE_URL),
        )
        failed(exc)
    return _state


async def probe_store() -> StoreState:
    """Late connect: an `unavailable` store becomes `connected` when the database appears."""
    global _state
    if _state != "unavailable" or _engine is None or time.monotonic() < _retry_at:
        return _state
    try:
        from app.store.migrate import ensure_schema

        await ensure_schema(_engine, migrate=settings.HISTORY_STORE_MIGRATE_ON_STARTUP)
        _state = "connected"
        recovered()
        logger.info("History store connected")
    except Exception as exc:
        failed(exc)
    return _state


async def shutdown_store() -> None:
    global _engine, _sessions, _state, _retry_at, _failed
    engine, _engine = _engine, None
    _sessions = None
    _state = "disabled"
    _retry_at = 0.0
    _failed = False
    if engine is not None:
        try:
            await engine.dispose()
        except Exception:
            logger.warning("History store pool close failed")


__all__ = [
    "Any",
    "StoreState",
    "async_database_url",
    "failed",
    "get_engine",
    "guarded",
    "probe_store",
    "recovered",
    "redacted_database_url",
    "session_scope",
    "set_session_factory",
    "setup_store",
    "shutdown_store",
    "store_enabled",
    "store_state",
    "store_usable",
]
