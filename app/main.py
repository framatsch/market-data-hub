import logging
import warnings
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.utils.errors import AppError, ErrorResponse, ErrorDetail
from app.api import routes_meta, routes_prices, routes_companies, routes_options, routes_ws
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)

# Suppress known deprecation warnings from upstream libraries (uvicorn/websockets migration in progress)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets.legacy")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn.protocols.websockets")

# Setup custom logging
setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    logger.info(f"Starting {settings.APP_NAME} in {settings.APP_ENV} mode")
    if settings.MCP_ENABLED:
        logger.info("MCP enabled — endpoints available at /mcp/sse and /mcp/messages")
    yield
    logger.info(f"Shutting down {settings.APP_NAME}")


app = FastAPI(
    title=settings.APP_NAME,
    description="Real-time market data aggregation from IBKR and LSEG",
    version="1.0.0",
    lifespan=lifespan
)

# REST routers
app.include_router(routes_meta.router)
app.include_router(routes_prices.router)
app.include_router(routes_companies.router)
app.include_router(routes_options.router)
app.include_router(routes_ws.router)

# MCP router (opt-in via MCP_ENABLED=true)
if settings.MCP_ENABLED:
    from app.api.mcp import router as mcp_router
    app.include_router(mcp_router)

# Exception Handlers
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    status_code = 500
    if exc.code == "DATA_NOT_FOUND":
        status_code = 404
    elif exc.code == "INVALID_PROVIDER":
        status_code = 400
    elif exc.code in ("PROVIDER_NOT_AVAILABLE", "PROVIDER_TIMEOUT"):
        status_code = 503

    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                details=exc.details
            )
        ).model_dump()
    )


@app.exception_handler(Exception)
async def general_error_handler(request: Request, exc: Exception):
    """Handle unexpected errors."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


if __name__ == "__main__":
    """Run the HTTP API (single Uvicorn process on port 8000)."""
    import os
    is_docker = os.path.exists('/.dockerenv')

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False if is_docker else (settings.APP_ENV == "dev"),
        log_level=settings.LOG_LEVEL.lower()
    )
