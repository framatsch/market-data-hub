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
import os
import warnings
from contextlib import asynccontextmanager

import uvicorn
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.utils.errors import AppError, ErrorResponse, ErrorDetail
from app.api import routes_admin, routes_meta, routes_prices, routes_companies, routes_options, routes_ws
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)

# Suppress known deprecation warnings from upstream libraries (uvicorn/websockets migration in progress)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets.legacy")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn.protocols.websockets")

# Setup custom logging
setup_logging()


def _public_base_url() -> str:
    host = os.getenv("PUBLIC_APP_HOST", "localhost")
    return f"http://{host}:{settings.APP_PORT}"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    from app.providers.registry import registry
    from app.admin.runtime import initialize_admin_runtime

    initialize_admin_runtime()
    await registry.reload_from_config()
    
    # --- STARTUP PROTOCOL OVERVIEW ---
    active_providers = list(registry._providers.keys())
    mcp_status = "ENABLED ✅" if settings.MCP_ENABLED else "DISABLED ❌"
    base_url = _public_base_url()
    
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
    for p in ["ibkr", "lseg", "finnhub", "polygon", "prixe"]:
        status = "✅ Active" if p in active_providers else "❌ Unavailable"
        banner += f"  - {p.upper():<8}: {status}\n"
    
    banner += (
        f"{'-' * 60}\n"
        f"Admin UI    : {base_url}/admin\n"
        f"API docs    : {base_url}/docs\n"
        "Service is ready to accept requests\n"
        f"{'=' * 60}"
    )
    
    # Force print to stdout to ensure it shows in Docker logs immediately
    print(banner, flush=True)
    logger.info("Startup protocol displayed.")
    
    yield
    
    logger.info(f"Shutting down {settings.APP_NAME}")
    await registry.shutdown()



app = FastAPI(
    title=settings.APP_NAME,
    description="Real-time market data aggregation from IBKR, LSEG, and Finnhub",
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
app.include_router(routes_admin.router)

def _resolve_admin_static_dir() -> Path:
    """Resolve the admin static directory at call time (not at module load).

    This allows the volume-mounted dist/ to be updated (e.g. npm run build:watch)
    without restarting the server — every request re-resolves the file from disk.
    """
    # 1. Sibling static/ next to the app/ package — used in Docker with volume mount
    #    ./admin/dist:/app/static/admin  →  /app/static/admin
    app_package_dir = Path(__file__).resolve().parent          # /app/app
    repo_root = app_package_dir.parent                         # /app
    candidate = repo_root / "static" / "admin"
    if candidate.exists():
        return candidate
    # 2. app/static/admin — baked into the image (Dockerfile COPY)
    candidate2 = app_package_dir / "static" / "admin"
    if candidate2.exists():
        return candidate2
    # 3. Dev fallback: running directly from repo checkout (no Docker)
    fallback = repo_root / "admin" / "dist"
    if fallback.exists():
        return fallback
    return candidate  # return non-existing path so callers get 404


@app.get("/admin/assets/{asset_path:path}", include_in_schema=False)
async def serve_admin_asset(asset_path: str):
    """Serve admin JS/CSS assets dynamically so volume-mount updates are picked up without restart."""
    asset_file = _resolve_admin_static_dir() / "assets" / asset_path
    if asset_file.exists() and asset_file.is_file():
        return FileResponse(asset_file)
    return JSONResponse(status_code=404, content={"detail": "Asset not found"})


@app.get("/admin", include_in_schema=False)
async def serve_admin_root():
    index = _resolve_admin_static_dir() / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(status_code=404, content={"detail": "Admin UI not built"})


@app.get("/admin/{full_path:path}", include_in_schema=False)
async def serve_admin_spa(full_path: str):
    static_dir = _resolve_admin_static_dir()
    file_path = static_dir / full_path
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    index = _resolve_admin_static_dir() / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(status_code=404, content={"detail": "Admin UI not built"})

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
    """Run the HTTP API (single Uvicorn process on configured host/port)."""
    is_docker = os.path.exists('/.dockerenv')

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=False if is_docker else (settings.APP_ENV == "dev"),
        log_level=settings.LOG_LEVEL.lower()
    )
