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

"""
MCP (Model Context Protocol) router — integrated into FastAPI.

Exposes two endpoints when MCP_ENABLED=true:
  GET  /mcp/sse       — SSE stream (session establishment + notifications)
  POST /mcp/messages  — JSON-RPC 2.0 tool calls

Session routing: each SSE connection gets a UUID; POST requests carry it
as a query param so responses can be pushed back into the SSE stream.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.providers.registry import get_registry
from app.services.company_service import CompanyService
from app.services.options_service import OptionsService
from app.services.price_service import PriceService
from app.utils.errors import AppError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])
metadata_router = APIRouter(tags=["mcp"])

# ---------------------------------------------------------------------------
# Session registry: session_id -> asyncio.Queue of SSE event strings
# ---------------------------------------------------------------------------
_ACTIVE_STREAMS: dict[str, asyncio.Queue[str]] = {}


# ---------------------------------------------------------------------------
# SSE transport
# ---------------------------------------------------------------------------

@router.get("")
@router.get("/sse")
async def mcp_sse(request: Request) -> StreamingResponse:
    """
    Open a persistent SSE stream for an MCP client.

    Immediately emits an 'endpoint' event with the session-specific POST URL.
    Sends keepalive comments every 15 s to prevent TCP timeout.
    Cleans up the session on disconnect.
    """
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue[str] = asyncio.Queue()
    _ACTIVE_STREAMS[session_id] = queue
    logger.debug("MCP SSE session opened: %s", session_id)

    async def event_stream() -> AsyncGenerator[str, None]:
        # Tell the client which URL to POST to
        yield f"event: endpoint\ndata: /mcp/messages?session_id={session_id}\n\n"
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield msg
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _ACTIVE_STREAMS.pop(session_id, None)
            logger.debug("MCP SSE session closed: %s", session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@metadata_router.get("/.well-known/oauth-protected-resource")
@metadata_router.get("/.well-known/oauth-protected-resource/mcp")
@router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata(request: Request) -> JSONResponse:
    """Advertise that the public MCP endpoint does not require OAuth."""
    return JSONResponse(
        {
            "resource": str(request.url_for("mcp_streamable_http")),
            "authorization_servers": [],
            "scopes_supported": [],
            "bearer_methods_supported": ["header"],
        }
    )


@metadata_router.get("/.well-known/oauth-authorization-server")
@metadata_router.get("/.well-known/oauth-authorization-server/mcp")
@metadata_router.get("/.well-known/openid-configuration")
@metadata_router.get("/.well-known/openid-configuration/mcp")
@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/openid-configuration")
async def oauth_not_required_metadata() -> JSONResponse:
    """Return a controlled response for OAuth discovery probes from MCP clients."""
    return JSONResponse(
        {"error": "oauth_not_required", "error_description": "This MCP endpoint is public."},
        status_code=404,
    )


@metadata_router.post("/register")
async def oauth_dynamic_registration_not_required() -> JSONResponse:
    """Claude probes this during remote MCP setup; no registration is needed here."""
    return JSONResponse(
        {"error": "oauth_not_required", "error_description": "This MCP endpoint is public."},
        status_code=400,
    )


# ---------------------------------------------------------------------------
# JSON-RPC message endpoint
# ---------------------------------------------------------------------------

@router.post("/messages")
async def mcp_messages(
    request: Request,
    session_id: str = Query(..., description="Session ID returned by /mcp/sse"),
) -> Response:
    """
    Accept a JSON-RPC 2.0 MCP tool call, dispatch it, and push the result
    into the SSE queue for the given session.
    """
    payload = await request.json()
    method = payload.get("method")
    rpc_id = payload.get("id")
    params = payload.get("params", {})

    response_payload = await _handle_json_rpc(method, params, rpc_id)
    if response_payload is None:
        return Response(status_code=202)

    queue = _ACTIVE_STREAMS.get(session_id)
    if queue:
        msg = json.dumps(response_payload)
        await queue.put(f"event: message\ndata: {msg}\n\n")
    else:
        logger.warning("MCP session not found: %s — response dropped", session_id)

    return Response(status_code=202)


@router.post("", name="mcp_streamable_http")
async def mcp_streamable_http(request: Request) -> Response:
    """
    Accept Streamable HTTP JSON-RPC calls at /mcp.

    Claude's remote MCP connector posts directly to the configured URL. Keep the
    legacy SSE endpoint above, but answer these calls inline instead of requiring
    the /mcp/messages session transport.
    """
    payload = await request.json()
    method = payload.get("method")
    rpc_id = payload.get("id")
    params = payload.get("params", {})

    response_payload = await _handle_json_rpc(method, params, rpc_id)
    if response_payload is None:
        return Response(status_code=202)
    return JSONResponse(response_payload)


async def _handle_json_rpc(method: str, params: dict[str, Any], rpc_id: Any) -> dict[str, Any] | None:
    """Dispatch a JSON-RPC request and serialise the response payload."""
    try:
        result = await _dispatch(method, params)
        if rpc_id is None:
            return None
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    except AppError as exc:
        logger.warning("MCP AppError in method=%s: %s", method, exc.message)
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"message": exc.message, "code": exc.code},
        }
    except Exception as exc:
        logger.error("MCP unexpected error in method=%s: %s", method, exc, exc_info=True)
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"message": str(exc)},
        }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def _dispatch(method: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Route an MCP JSON-RPC call to the appropriate handler."""
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "market-data-hub",
                "version": "1.0.0"
            }
        }

    if method == "notifications/initialized":
        return None

    if method == "ping":
        return {}

    if method == "tools/list":
        return {"tools": TOOL_REGISTRY}

    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            raise AppError("Tool name must be a string", code="INVALID_PARAMS")
        args = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            raise AppError(f"Unknown tool: {name}", code="UNKNOWN_TOOL")
        return await handler(args)

    raise AppError(f"Unknown method: {method}", code="UNKNOWN_METHOD")


# ---------------------------------------------------------------------------
# Shared service instances (re-use the same singletons as the HTTP layer)
# ---------------------------------------------------------------------------

def _price_service() -> PriceService:
    return PriceService(get_registry())


def _options_service() -> OptionsService:
    return OptionsService(get_registry())


def _company_service() -> CompanyService:
    return CompanyService(get_registry())


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _text_content(data: Any) -> dict[str, Any]:
    """Wrap serialised data in the standard MCP content envelope."""
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


async def _tool_get_last_price(args: dict[str, Any]) -> dict[str, Any]:
    symbol = args["symbol"].upper()
    sec_type = args.get("sec_type", "stock")
    provider = args.get("provider")
    quote = await _price_service().get_latest_price(symbol, provider_name=provider, sec_type=sec_type)
    if not quote:
        return _text_content(f"No price data found for {symbol} ({sec_type})")
    return _text_content(quote.model_dump())


async def _tool_get_historical_prices(args: dict[str, Any]) -> dict[str, Any]:
    symbol = args["symbol"].upper()
    interval = args.get("interval", "1d")
    sec_type = args.get("sec_type", "stock")
    provider = args.get("provider")
    end = datetime.now()
    start = end - timedelta(days=30)
    if "start_date" in args:
        start = datetime.fromisoformat(args["start_date"])
    if "end_date" in args:
        end = datetime.fromisoformat(args["end_date"])
    bars = await _price_service().get_historical_prices(
        symbol,
        interval,
        start,
        end,
        provider_name=provider,
        sec_type=sec_type,
    )
    if not bars:
        return _text_content(f"No historical data found for {symbol} ({sec_type})")
    return _text_content([b.model_dump() for b in bars])


async def _tool_get_option_chain(args: dict[str, Any]) -> dict[str, Any]:
    symbol = args["symbol"].upper()
    expiry_str = args.get("expiry")
    expiry = date.fromisoformat(expiry_str) if expiry_str else date.today()
    provider = args.get("provider")
    chain = await _options_service().get_option_chain(symbol, expiry, provider_name=provider)
    return _text_content(chain.model_dump())


async def _tool_get_option_quote(args: dict[str, Any]) -> dict[str, Any]:
    symbol = args["symbol"].upper()
    option_id = args["option_id"].upper()
    provider = args.get("provider")
    quote = await _options_service().get_option_quote(symbol, option_id, provider_name=provider)
    return _text_content(quote.model_dump())


async def _tool_get_company_profile(args: dict[str, Any]) -> dict[str, Any]:
    symbol = args["symbol"].upper()
    provider = args.get("provider")
    profile = await _company_service().get_company_profile(symbol, provider_name=provider)
    return _text_content(profile.model_dump())


async def _tool_search_companies(args: dict[str, Any]) -> dict[str, Any]:
    query = args["query"]
    provider = args.get("provider")
    results = await _company_service().search_companies(query, provider_name=provider)
    return _text_content([r.model_dump() for r in results])


async def _tool_get_company_news(args: dict[str, Any]) -> dict[str, Any]:
    symbol = args["symbol"].upper()
    to_date = date.today()
    from_date = to_date - timedelta(days=7)
    if "from_date" in args:
        from_date = date.fromisoformat(args["from_date"])
    if "to_date" in args:
        to_date = date.fromisoformat(args["to_date"])
    limit = int(args.get("limit", 20))
    provider_name = args.get("provider")
    provider = get_registry().get_news_provider(provider_name)
    articles = await provider.get_company_news(symbol, from_date, to_date, limit=limit)
    return _text_content([a.model_dump() for a in articles])


async def _tool_get_market_status(args: dict[str, Any]) -> dict[str, Any]:
    provider = args.get("provider")
    status = await _price_service().get_market_status(provider_name=provider)
    return _text_content(status.model_dump())


# ---------------------------------------------------------------------------
# Tool registry (MCP schema descriptors)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "get_last_price",
        "description": "Get the latest price quote for a stock or index symbol.",
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL"},
                "sec_type": {
                    "type": "string",
                    "enum": ["stock", "index"],
                    "description": "Security type (default: stock)",
                },
                "provider": {
                    "type": "string",
                    "description": "Data provider override (e.g. ibkr, lseg)",
                },
            },
        },
    },
    {
        "name": "get_historical_prices",
        "description": "Get historical OHLCV price bars for a symbol.",
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string"},
                "interval": {
                    "type": "string",
                    "description": "Bar interval, e.g. 1d, 1h, 5m (default: 1d)",
                },
                "start_date": {
                    "type": "string",
                    "format": "date",
                    "description": "ISO date string (default: 30 days ago)",
                },
                "end_date": {
                    "type": "string",
                    "format": "date",
                    "description": "ISO date string (default: today)",
                },
                "sec_type": {"type": "string", "enum": ["stock", "index"]},
                "provider": {
                    "type": "string",
                    "description": "Data provider override (e.g. ibkr, lseg)",
                },
            },
        },
    },
    {
        "name": "get_option_chain",
        "description": "Get all option contracts for a symbol on a given expiry date.",
        "inputSchema": {
            "type": "object",
            "required": ["symbol", "expiry"],
            "properties": {
                "symbol": {"type": "string"},
                "expiry": {
                    "type": "string",
                    "format": "date",
                    "description": "Option expiry date (ISO format, e.g. 2024-01-19)",
                },
                "provider": {
                    "type": "string",
                    "description": "Data provider override (e.g. ibkr, lseg)",
                },
            },
        },
    },
    {
        "name": "get_option_quote",
        "description": "Get a quote for a specific option contract.",
        "inputSchema": {
            "type": "object",
            "required": ["symbol", "option_id"],
            "properties": {
                "symbol": {"type": "string"},
                "option_id": {
                    "type": "string",
                    "description": "Option contract identifier, e.g. AAPL240119C00150000",
                },
                "provider": {
                    "type": "string",
                    "description": "Data provider override (e.g. ibkr, lseg)",
                },
            },
        },
    },
    {
        "name": "get_company_profile",
        "description": "Get fundamental company data (name, sector, market cap, etc.).",
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string"},
                "provider": {
                    "type": "string",
                    "description": "Data provider override (e.g. ibkr, lseg)",
                },
            },
        },
    },
    {
        "name": "search_companies",
        "description": "Search for companies by name or ticker.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Search term, e.g. Apple"},
                "provider": {
                    "type": "string",
                    "description": "Data provider override (e.g. ibkr, lseg)",
                },
            },
        },
    },
    {
        "name": "get_company_news",
        "description": "Get recent news articles for a company.",
        "inputSchema": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string"},
                "from_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Start date (default: 7 days ago)",
                },
                "to_date": {
                    "type": "string",
                    "format": "date",
                    "description": "End date (default: today)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max articles to return (default: 20)",
                },
                "provider": {
                    "type": "string",
                    "description": "Data provider override (e.g. ibkr, lseg)",
                },
            },
        },
    },
    {
        "name": "get_market_status",
        "description": "Get the current market status (open/closed/extended hours).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Data provider (e.g., polygon, ibkr)",
                },
            },
        },
    },
]

TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "get_last_price": _tool_get_last_price,
    "get_historical_prices": _tool_get_historical_prices,
    "get_option_chain": _tool_get_option_chain,
    "get_option_quote": _tool_get_option_quote,
    "get_company_profile": _tool_get_company_profile,
    "search_companies": _tool_search_companies,
    "get_company_news": _tool_get_company_news,
    "get_market_status": _tool_get_market_status,
}
