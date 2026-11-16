"""Tests for suppressing benign websocket 1001 close logs."""

import logging

import pytest

from app.logging_config import WebsocketGoingAwayFilter, setup_logging


def _record(msg: str, level: int = logging.ERROR) -> logging.LogRecord:
    return logging.LogRecord("websocket", level, __file__, 1, msg, None, None)


def test_filter_drops_close_status_1001() -> None:
    assert WebsocketGoingAwayFilter().filter(_record("close status: 1001")) is False


@pytest.mark.parametrize(
    "msg",
    ["close status: 1008", "close status: 4001", "Websocket connected", "error from callback"],
)
def test_filter_keeps_other_messages(msg: str) -> None:
    assert WebsocketGoingAwayFilter().filter(_record(msg)) is True


def test_setup_logging_installs_filter_once(caplog: pytest.LogCaptureFixture) -> None:
    setup_logging()
    setup_logging()
    ws_logger = logging.getLogger("websocket")
    assert sum(isinstance(f, WebsocketGoingAwayFilter) for f in ws_logger.filters) == 1

    with caplog.at_level(logging.INFO, logger="websocket"):
        ws_logger.error("close status: 1001")
        ws_logger.error("close status: 1008")
    messages = [r.getMessage() for r in caplog.records if r.name == "websocket"]
    assert messages == ["close status: 1008"]
