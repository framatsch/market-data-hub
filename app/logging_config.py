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

"""Custom logging configuration for uvicorn and application logs."""

import json
import logging
from datetime import datetime, timezone

import structlog

# Create a custom logger for access logs
access_logger = logging.getLogger("uvicorn.access")


class HealthCheckFilter(logging.Filter):
    """Filter to suppress health check endpoint logs unless in DEBUG mode."""

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter health check requests.
        - Returns False to suppress the log (don't show it)
        - Returns True to allow the log
        """
        # Check if this is a health check request
        if "/health" in record.getMessage():
            # Only show health checks if logger is at DEBUG level
            return access_logger.level <= logging.DEBUG
        return True


class RequestContextFilter(logging.Filter):
    """Attach request contextvars to standard logging records."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = structlog.contextvars.get_contextvars()
        provider = context.get("provider")
        if provider is None and record.name.startswith("app.providers."):
            provider = record.name.split(".")[2]
        record.provider = provider or "none"
        return True


class JsonRequestFormatter(logging.Formatter):
    """Emit stdlib logs with source and request context fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "event": record.getMessage(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "provider": getattr(record, "provider", "none"),
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _apply_formatter_to_all_handlers(formatter: logging.Formatter, context_filter: logging.Filter) -> None:
    """Apply formatter + filter to every handler on the root logger and known uvicorn loggers."""
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        root_logger.addHandler(handler)

    target_loggers = [root_logger] + [
        logging.getLogger(n) for n in ("uvicorn", "uvicorn.error", "uvicorn.access")
    ]
    for lg in target_loggers:
        for handler in lg.handlers:
            if not any(isinstance(f, RequestContextFilter) for f in handler.filters):
                handler.addFilter(context_filter)
            handler.setFormatter(formatter)


def patch_refinitiv_loggers() -> None:
    """Replace the plain-text StreamHandler on all active refinitiv.data (rd.*) loggers.

    refinitiv.data creates its own StreamHandler with a custom plain-text formatter
    via ``_log.create_logger()``.  That handler is attached directly to each ``rd.*``
    logger and bypasses our root-logger formatter entirely.

    This function must be called *after* the LSEG session is first opened (because
    loggers are created lazily via @lru_cache in refinitiv.data._log).
    Calling it multiple times is safe — already-patched handlers are skipped.
    """
    formatter = JsonRequestFormatter()
    context_filter = RequestContextFilter()

    # logging.Logger.manager.loggerDict holds every logger that has been created.
    for name, lg in list(logging.Logger.manager.loggerDict.items()):
        if not name.startswith("rd") or not isinstance(lg, logging.Logger):
            continue
        for handler in lg.handlers:
            # Skip if already patched to our formatter
            if isinstance(handler.formatter, JsonRequestFormatter):
                continue
            if not any(isinstance(f, RequestContextFilter) for f in handler.filters):
                handler.addFilter(context_filter)
            handler.setFormatter(formatter)


def setup_logging() -> None:
    """Setup custom logging configuration.

    Called once at module import (app/main.py top-level).  uvicorn.run() will
    later call logging.config.dictConfig() which replaces the root handler's
    formatter.  We therefore also expose `get_uvicorn_log_config()` which must
    be passed as `log_config=` to uvicorn.run() so our formatter survives.
    """
    access_logger.addFilter(HealthCheckFilter())

    context_filter = RequestContextFilter()
    formatter = JsonRequestFormatter()
    _apply_formatter_to_all_handlers(formatter, context_filter)

    # Suppress ib_async.wrapper ERROR logs for subscription errors (10089/10091)
    logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)


def get_uvicorn_log_config(log_level: str = "info") -> dict:
    """Return a logging dictConfig for uvicorn that uses our JsonRequestFormatter.

    Pass this as log_config= to uvicorn.run() so uvicorn's dictConfig call does
    not replace our formatter with its plain-text default.
    """
    level = log_level.upper()
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": "app.logging_config.RequestContextFilter",
            },
        },
        "formatters": {
            "json": {
                "()": "app.logging_config.JsonRequestFormatter",
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
                "filters": ["request_context"],
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": level, "propagate": False},
            # Silence ib_async subscription noise
            "ib_async.wrapper": {"handlers": ["default"], "level": "CRITICAL", "propagate": False},
        },
        "root": {
            "handlers": ["default"],
            "level": level,
        },
    }
