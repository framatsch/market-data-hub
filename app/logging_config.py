"""Custom logging configuration for uvicorn."""

import logging

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


def setup_logging():
    """Setup custom logging configuration."""
    # Add the health check filter to the access logger
    access_logger.addFilter(HealthCheckFilter())
