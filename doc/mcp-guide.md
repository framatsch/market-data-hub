# Model Context Protocol (MCP) Guide

The Market Data Hub (MDH) features an integrated **Model Context Protocol (MCP)** server. This allows AI assistants and agents (like Claude Desktop, Cursor, or other MCP-compatible clients) to securely interact with the financial data provided by the hub, such as querying live stock prices, options chains, and company news.

## Enabling the MCP Server

The MCP server runs within the same FastAPI process as the standard REST API and WebSocket services. It is disabled by default.

To enable the MCP server, set the `MCP_ENABLED` environment variable to `true` when starting the application:

```bash
# Using standard Python
MCP_ENABLED=true python -m app.main

# Using Docker
docker run -p 8000:8000 \
  -e MCP_ENABLED=true \
  -e IBKR_HOST=... \
  market-data-hub
```

When enabled, the MCP server is exposed on the identical port (default `8000`) at the following endpoints:

- `GET /mcp/sse` — Establishes the Server-Sent Events (SSE) stream for the session.
- `POST /mcp/messages?session_id=<id>` — Endpoint for JSON-RPC 2.0 tool calls.

## Available MCP Tools

The MCP server currently exposes the following tools to clients:

- `get_last_price`: Retrieve the latest price for a given ticker symbol.
- `get_historical_prices`: Fetch historical price data (candles) for a specific symbol.
- `get_option_chain`: Retrieve the available options chain (strikes and expirations) for a symbol.
- `get_option_quote`: Get a real-time quote for a specific option contract.
- `get_company_profile`: Fetch fundamental profile information for a company.
- `search_companies`: Search for companies by name or ticker.
- `get_company_news`: Retrieve the latest news articles related to a company.

## Connecting an MCP Client

### Connecting from Claude Desktop

You can configure Claude Desktop to connect to the MDH MCP server using the `sse` transport mechanism if your client supports configuring generic SSE MCP servers.

> **Note:** Claude Desktop configuration for SSE servers requires an intermediary tool or script that bridges the standard stdio transport to SSE, as Claude Desktop natively expects `stdio` connections.
> If your client supports direct SSE connections, configure the connection URL as: `http://localhost:8000/mcp/sse`.

### Example Client Usage (Python)

If you are writing a custom MCP client using the official MCP Python SDK, you can connect to the MDH like this:

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client("http://localhost:8000/mcp/sse") as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            
            # List available tools
            tools = await session.list_tools()
            print("Available tools:", [tool.name for tool in tools.tools])
            
            # Call a tool
            result = await session.call_tool("get_last_price", arguments={"symbol": "AAPL"})
            print(result)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## Architecture Details

The MCP integration is built directly into the FastAPI application, eliminating the need for a separate process. This design ensures that the MCP tools use the exact same internal services, database sessions, and configuration as the REST and WebSocket APIs.

For an in-depth view of the original implementation design, see the [MCP Implementation Proposal](mcp-implementation-proposal.md).
