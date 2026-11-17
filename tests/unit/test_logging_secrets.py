"""Credentials in query strings must never reach the logs (Alpha Vantage `apikey=`)."""

import logging

import httpx
import pytest

from app.logging_config import setup_logging


@pytest.fixture
def restore_levels():
    names = ("httpx", "httpcore")
    saved = {name: logging.getLogger(name).level for name in names}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


async def test_request_urls_are_not_logged(caplog, restore_levels):
    logging.getLogger("httpx").setLevel(logging.INFO)  # httpx's default behaviour
    setup_logging()
    caplog.set_level(logging.DEBUG)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    async with httpx.AsyncClient(transport=transport) as client:
        await client.get("https://example.test/query", params={"apikey": "SECRET-KEY"})
    assert "SECRET-KEY" not in caplog.text
    assert logging.getLogger("httpx").level >= logging.WARNING
