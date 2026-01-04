import logging
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

from app.config import settings
from app.utils.errors import AppError, ErrorResponse, ErrorDetail
from app.api import routes_meta, routes_prices, routes_companies, routes_options, routes_ws
from app.logging_config import setup_logging

mcp_logger = logging.getLogger(__name__)

# Setup custom logging
setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    mcp_logger.info(f"Starting {settings.APP_NAME} in {settings.APP_ENV} mode")
    yield
    mcp_logger.info(f"Shutting down {settings.APP_NAME}")





app = FastAPI(
    title=settings.APP_NAME,
    description="Real-time market data aggregation from IBKR and LSEG",
    version="1.0.0",
    lifespan=lifespan
)

# Routers
app.include_router(routes_meta.router)
app.include_router(routes_prices.router)
app.include_router(routes_companies.router)
app.include_router(routes_options.router)
app.include_router(routes_ws.router)

# Create MCP server
mcp = FastMCP("Market Data Hub MCP")

# Add example MCP tools
@mcp.tool()
def get_api_health() -> dict:
    """Get the health status of the Market Data Hub API."""
    return {"status": "OK", "message": "Market Data Hub is running"}

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
    mcp_logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


if __name__ == "__main__":
    """
    Run both HTTP API and MCP servers in parallel.

    - HTTP API: http://0.0.0.0:8000/
    - MCP SSE:  http://0.0.0.0:8001/sse
    """
    import os
    is_docker = os.path.exists('/.dockerenv')

    # Start HTTP server in background thread
    def run_http():
        mcp_logger.info("Starting HTTP API server on port 8000")
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=False if is_docker else (settings.APP_ENV == "dev"),
            log_level=settings.LOG_LEVEL.lower()
        )

    http_thread = threading.Thread(target=run_http, daemon=True)
    http_thread.start()

    # Run MCP server in main thread
    mcp_logger.info("Starting MCP SSE server on port 8001")
    mcp.run(transport="sse", host="0.0.0.0", port=8001)