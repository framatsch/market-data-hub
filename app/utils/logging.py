import logging
import sys
from app.config import settings

def setup_logging():
    """Configures the logging for the application."""
    logger = logging.getLogger("market_data_hub")
    
    # Set level
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)
    
    # Handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    
    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    
    # Avoid duplicate handlers
    if not logger.handlers:
        logger.addHandler(handler)
        
    # Also configure uvicorn loggers to match
    logging.getLogger("uvicorn.access").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)

    return logger

logger = setup_logging()
