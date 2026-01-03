import logging
import sys
import subprocess
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

from app.config import settings
from app.utils.errors import AppError, ErrorResponse, ErrorDetail
from app.api import routes_meta, routes_prices, routes_companies, routes_options, routes_ws

mcp_logger = logging.getLogger(__name__)


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


# Routers
app.include_router(routes_meta.router)
app.include_router(routes_prices.router)
app.include_router(routes_companies.router)
app.include_router(routes_options.router)
app.include_router(routes_ws.router)


def create_mcp_server(app: FastAPI) -> FastMCP:
    """
    Create MCP server from FastAPI application.

    Uses SSE (Server-Sent Events) transport for remote client access.
    Exposes all FastAPI endpoints as MCP resources.

    Args:
        app: FastAPI application instance

    Returns:
        FastMCP server instance ready to run
    """
    mcp = FastMCP.from_fastapi(app=app)
    mcp_logger.info("MCP server created with SSE transport")
    return mcp


def run_http_server(host: str = "0.0.0.0", port: int = 8000):
    """Run FastAPI HTTP server."""
    mcp_logger.info(f"Starting HTTP server on {host}:{port}")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=settings.app_env == "dev",
        log_level=settings.log_level.lower()
    )


def run_mcp_server():
    """Run MCP (Model Context Protocol) server with SSE transport."""
    mcp_logger.info("Starting MCP server with SSE transport on port 8001")
    mcp = create_mcp_server(app)
    mcp.run(transport="sse", host="0.0.0.0", port=8001)


def run_both_servers():
    """
    Run both HTTP and MCP servers in parallel.

    Note: This requires async task management or process forking.
    For production, use orchestration (Docker Compose, Kubernetes) instead.
    """
    # Start HTTP server in background
    http_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    )

    # Start MCP server in foreground
    mcp = create_mcp_server(app)

    try:
        mcp.run(transport="sse", host="0.0.0.0", port=8001)
    except KeyboardInterrupt:
        mcp_logger.info("Shutting down servers...")
        http_process.terminate()
        http_process.wait()


if __name__ == "__main__":
    # Parse CLI arguments
    mode = "http"  # default

    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()

    if mode == "http":
        run_http_server()
    elif mode == "mcp":
        run_mcp_server()
    elif mode == "both":
        run_both_servers()
    else:
        mcp_logger.error(f"Unknown mode: {mode}")
        mcp_logger.info("Usage: python -m app.main [http|mcp|both]")
        sys.exit(1)
