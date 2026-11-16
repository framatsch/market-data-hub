"""Shared fixtures of the history store integration tests."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.store import engine
from app.store.engine import async_database_url
from app.store.migrate import ensure_schema

URL = os.getenv("TEST_DATABASE_URL", "postgresql://mdh:mdh@localhost:55432/mdh_test")


async def _drop_all(eng):
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "DROP TABLE IF EXISTS iv_points_daily, price_bars, "
                "history_series, alembic_version CASCADE"
            )
        )


@pytest.fixture
async def db():
    eng = create_async_engine(async_database_url(URL))
    try:
        await ensure_schema(eng)
    except Exception:
        try:
            await _drop_all(eng)
            await ensure_schema(eng)
        except Exception:
            await eng.dispose()
            pytest.skip("no PostgreSQL available for the history store tests")
    async with eng.begin() as conn:
        await conn.execute(
            text("TRUNCATE history_series, price_bars, iv_points_daily CASCADE")
        )
    engine.set_session_factory(async_sessionmaker(eng, expire_on_commit=False))
    yield eng
    engine.set_session_factory(None)
    await eng.dispose()


