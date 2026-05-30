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
from datetime import date, datetime, timedelta
from typing import Any, AsyncGenerator, Dict

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse

from app.services.price_service import PriceService
from app.services.options_service import OptionsService
from app.services.company_service import CompanyService
from app.providers.registry import get_registry
from app.utils.errors import AppError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

# ---------------------------------------------------------------------------
# Session registry: session_id -> asyncio.Queue of SSE event strings
# ---------------------------------------------------------------------------
_ACTIVE_STREAMS: Dict[str, asyncio.Queue[str]] = {}


# ---------------------------------------------------------------------------
# SSE transport
# ---------------------------------------------------------------------------

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
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _ACTIVE_STREAMS.pop(session_id, None)
            logger.debug("MCP SSE session closed: %s", session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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

    try:
        result = await _dispatch(method, params)
        if rpc_id is None:
            # Notification, no response needed
            return Response(status_code=202)
        response_payload: dict = {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    except AppError as exc:
        logger.warning("MCP AppError in method=%s: %s", method, exc.message)
        response_payload = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"message": exc.message, "code": exc.code},
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("MCP unexpected error in method=%s: %s", method, exc, exc_info=True)
        response_payload = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"message": str(exc)},
        }

    queue = _ACTIVE_STREAMS.get(session_id)
    if queue:
        msg = json.dumps(response_payload)
        await queue.put(f"event: message\ndata: {msg}\n\n")
    else:
        logger.warning("MCP session not found: %s — response dropped", session_id)

    return Response(status_code=202)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def _dispatch(method: str, params: dict) -> dict | None:
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

def _text_content(data: Any) -> dict:
    """Wrap serialised data in the standard MCP content envelope."""
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


async def _tool_get_last_price(args: dict) -> dict:
    symbol = args["symbol"].upper()
    sec_type = args.get("sec_type", "stock")
    quote = await _price_service().get_latest_price(symbol, sec_type=sec_type)
    return _text_content(quote.model_dump())


async def _tool_get_historical_prices(args: dict) -> dict:
    symbol = args["symbol"].upper()
    interval = args.get("interval", "1d")
    sec_type = args.get("sec_type", "stock")
    end = datetime.now()
    start = end - timedelta(days=30)
    if "start_date" in args:
        start = datetime.fromisoformat(args["start_date"])
    if "end_date" in args:
        end = datetime.fromisoformat(args["end_date"])
    bars = await _price_service().get_historical_prices(symbol, interval, start, end, sec_type=sec_type)
    return _text_content([b.model_dump() for b in bars])


async def _tool_get_option_chain(args: dict) -> dict:
    symbol = args["symbol"].upper()
    expiry_str = args.get("expiry")
    expiry = date.fromisoformat(expiry_str) if expiry_str else date.today()
    chain = await _options_service().get_option_chain(symbol, expiry)
    return _text_content(chain.model_dump())


async def _tool_get_option_quote(args: dict) -> dict:
    symbol = args["symbol"].upper()
    option_id = args["option_id"]
    quote = await _options_service().get_option_quote(symbol, option_id)
    return _text_content(quote.model_dump())


async def _tool_get_company_profile(args: dict) -> dict:
    symbol = args["symbol"].upper()
    profile = await _company_service().get_company_profile(symbol)
    return _text_content(profile.model_dump())


async def _tool_search_companies(args: dict) -> dict:
    query = args["query"]
    results = await _company_service().search_companies(query)
    return _text_content([r.model_dump() for r in results])


async def _tool_get_company_news(args: dict) -> dict:
    symbol = args["symbol"].upper()
    to_date = date.today()
    from_date = to_date - timedelta(days=7)
    if "from_date" in args:
        from_date = date.fromisoformat(args["from_date"])
    if "to_date" in args:
        to_date = date.fromisoformat(args["to_date"])
    limit = int(args.get("limit", 20))
    registry = get_registry()
    provider = registry.get_news_provider()
    articles = await provider.get_company_news(symbol, from_date, to_date, limit=limit)
    return _text_content([a.model_dump() for a in articles])


# ---------------------------------------------------------------------------
# Tool registry (MCP schema descriptors)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: list[dict] = [
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
            },
        },
    },
]

TOOL_HANDLERS: Dict[str, Any] = {
    "get_last_price": _tool_get_last_price,
    "get_historical_prices": _tool_get_historical_prices,
    "get_option_chain": _tool_get_option_chain,
    "get_option_quote": _tool_get_option_quote,
    "get_company_profile": _tool_get_company_profile,
    "search_companies": _tool_search_companies,
    "get_company_news": _tool_get_company_news,
}
