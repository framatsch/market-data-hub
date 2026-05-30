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
    from app.providers.registry import registry
    
    # --- STARTUP PROTOCOL OVERVIEW ---
    active_providers = list(registry._providers.keys())
    mcp_status = "ENABLED ✅" if settings.MCP_ENABLED else "DISABLED ❌"
    
    banner = f"""
{"=" * 60}
{settings.APP_NAME} - STARTUP PROTOCOL
{"-" * 60}
Environment : {settings.APP_ENV}
MCP Status  : {mcp_status}
{"MCP Path    : /mcp/sse, /mcp/messages" if settings.MCP_ENABLED else ""}
{"-" * 60}
ACTIVE PROVIDERS:
"""
    for p in ["ibkr", "lseg", "schwab", "finnhub"]:
        status = "✅ Active" if p in active_providers else "❌ Unavailable"
        banner += f"  - {p.upper():<8}: {status}\n"
    
    banner += f"{'-' * 60}\nService is ready to accept requests\n{'=' * 60}"
    
    # Force print to stdout to ensure it shows in Docker logs immediately
    print(banner, flush=True)
    logger.info("Startup protocol displayed.")
    
    yield
    
    logger.info(f"Shutting down {settings.APP_NAME}")
    await registry.shutdown()


from fastapi.middleware.cors import CORSMiddleware
...
app = FastAPI(
    title=settings.APP_NAME,
    description="Real-time market data aggregation from IBKR, LSEG, and Schwab",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for MCP Inspector and other clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    elif exc.code in ("PROVIDER_NOT_AVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_CONNECTION_ERROR"):
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
