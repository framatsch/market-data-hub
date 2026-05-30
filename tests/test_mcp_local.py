import asyncio
import httpx
import json

BASE_URL = "http://localhost:9000"

async def test_mcp_flow():
    print("Starting MCP local integration test...")
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Connect to SSE
        print("[1] Connecting to /mcp/sse...")
        async with client.stream("GET", f"{BASE_URL}/mcp/sse") as response:
            if response.status_code != 200:
                print(f"FAILED: /mcp/sse returned {response.status_code}")
                return

            lines = response.aiter_lines()
            session_id = None
            async for line in lines:
                if "data: /mcp/messages?session_id=" in line:
                    session_id = line.split("session_id=")[1].strip()
                    print(f"SUCCESS: Got session_id: {session_id}")
                    break
            
            if not session_id:
                print("FAILED: Could not find session_id in SSE stream")
                return

            # 2. Call tools/list
            print("[2] Calling tools/list via POST /mcp/messages...")
            payload = {
                "jsonrpc": "2.0",
                "id": "list-test",
                "method": "tools/list",
                "params": {}
            }
            resp = await client.post(f"{BASE_URL}/mcp/messages?session_id={session_id}", json=payload)
            if resp.status_code != 202:
                print(f"FAILED: POST returned {resp.status_code}: {resp.text}")
                return
            
            # 3. Read result from SSE
            print("[3] Waiting for tools/list response in SSE stream...")
            result = None
            async for line in lines:
                if line.startswith("data: {"):
                    result = json.loads(line[6:].strip())
                    break
            
            if result and result.get("id") == "list-test":
                tools = result["result"]["tools"]
                print(f"SUCCESS: Found {len(tools)} tools")
                for t in tools:
                    print(f"  - {t['name']}")
            else:
                print(f"FAILED: Unexpected result: {result}")
                return

            # 4. Test tool call (get_last_price)
            # Since LSEG is not available, this should return an error if it's the default,
            # but we can at least see how the error is handled.
            print("[4] Calling get_last_price for AAPL...")
            payload = {
                "jsonrpc": "2.0",
                "id": "price-test",
                "method": "tools/call",
                "params": {
                    "name": "get_last_price",
                    "arguments": {"symbol": "AAPL"}
                }
            }
            await client.post(f"{BASE_URL}/mcp/messages?session_id={session_id}", json=payload)
            
            print("[5] Waiting for tool response...")
            async for line in lines:
                if line.startswith("data: {"):
                    result = json.loads(line[6:].strip())
                    break
            
            if "error" in result:
                print(f"INFO: Tool returned error as expected (Provider likely unavailable): {result['error']['message']}")
            else:
                print(f"SUCCESS: Got price data: {result['result']}")

    print("\nLocal MCP Integration Test Finished.")

if __name__ == "__main__":
    asyncio.run(test_mcp_flow())
