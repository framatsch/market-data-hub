"""MCP (Model Context Protocol) server implementation."""

from fastmcp import FastMCP
from fastapi import FastAPI
import logging

logger = logging.getLogger(__name__)


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

    logger.info("MCP server created with SSE transport")
    return mcp
