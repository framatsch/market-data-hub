"""Custom logging configuration for uvicorn."""

import logging

# Create a custom logger for access logs
access_logger = logging.getLogger("uvicorn.access")


class HealthCheckFilter(logging.Filter):
    """Filter to suppress or reduce logging for health check endpoints."""

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter health check requests.
        - Return False to suppress the log
        - Return True to allow the log
        """
        # Check if this is a health check request
        if "/health" in record.getMessage():
            # Only log health checks at DEBUG level
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


def setup_logging():
    """Setup custom logging configuration."""
    # Add the health check filter to the access logger
    access_logger.addFilter(HealthCheckFilter())
