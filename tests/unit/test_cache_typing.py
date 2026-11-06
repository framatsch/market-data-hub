"""Runtime and mypy regression checks for the shared cache decorator."""

from collections.abc import Awaitable
from typing import assert_type

import pytest
from fastapi import Response
from fastapi_cache import FastAPICache

from app.cache import cache


async def test_cache_preserves_typed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FastAPICache, "get_enable", lambda: False)

    @cache(expire=60)
    async def lookup(symbol: str, *, limit: int = 1) -> str:
        return f"{symbol}:{limit}"

    result = lookup("AAPL", limit=2)
    assert_type(result, Awaitable[str | Response])
    assert await result == "AAPL:2"


async def test_cache_preserves_response_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FastAPICache, "get_enable", lambda: False)

    @cache(expire=60)
    async def respond(status_code: int) -> Response:
        return Response(status_code=status_code)

    result = respond(204)
    assert_type(result, Awaitable[Response])
    assert (await result).status_code == 204
