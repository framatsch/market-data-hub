"""Probe the isolated Compose cache harness, without credentials or live brokers."""

import argparse
import json
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("phase", choices=("warm", "outage", "persisted", "coverage"))
parser.add_argument("--url", default="http://localhost:19090")
args = parser.parse_args()

for path in ("/options/AAPL/chain", "/prices/AAPL/history"):
    for format in ("json", "csv"):
        url = f"{args.url}{path}?provider=schwab&format={format}"
        headers = {"Cache-Control": "no-cache"} if args.phase in {"warm", "coverage"} else {}
        with urlopen(Request(url, headers=headers), timeout=5) as response:
            body = response.read()
            expected = "HIT" if args.phase == "persisted" else "MISS"
            assert response.status == 200
            assert response.headers["X-FastAPI-Cache"] == expected
            assert response.headers["Cache-Control"].startswith("max-age=")
            print(f"{args.phase}: {path} {format} HTTP 200 {expected}")
        if args.phase in {"warm", "coverage"}:
            with urlopen(url, timeout=5) as cached:
                assert cached.headers["X-FastAPI-Cache"] == "HIT"
                assert cached.read() == body
                print(f"repeat: {path} {format} HIT, identical body")

if args.phase == "coverage":
    for path in (
        "/companies/AAPL?provider=schwab",
        "/companies/search?q=Apple&provider=schwab",
        "/companies/AAPL/news?provider=schwab",
        "/companies/AAPL/news?provider=schwab&format=csv",
        "/market-status?provider=schwab",
    ):
        with urlopen(Request(f"{args.url}{path}", headers={"Cache-Control": "no-cache"}), timeout=5) as live:
            body = live.read()
            assert live.headers["X-FastAPI-Cache"] == "MISS"
        with urlopen(f"{args.url}{path}", timeout=5) as cached:
            assert cached.headers["X-FastAPI-Cache"] == "HIT"
            assert cached.read() == body
        print(f"coverage: {path} MISS then HIT, identical body")

    for name, tool_args in (
        ("get_historical_prices", {"symbol": "AAPL", "start_date": "2026-01-01", "end_date": "2026-01-02"}),
        ("get_option_chain", {"symbol": "AAPL", "expiry": "2026-12-18"}),
        ("get_company_profile", {"symbol": "AAPL"}),
        ("search_companies", {"query": "Apple"}),
        ("get_company_news", {"symbol": "AAPL"}),
        ("get_market_status", {}),
    ):
        responses = []
        for refresh in (True, False):
            payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": name, "arguments": {**tool_args, "provider": "schwab", "refresh": refresh},
            }}
            request = Request(f"{args.url}/mcp", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=5) as response:
                result = json.load(response)
                assert "error" not in result, result
                responses.append(result["result"])
        assert responses[0] == responses[1]
        print(f"coverage: MCP {name} refresh then cached call, identical body")

with urlopen(f"{args.url}/api/admin/cache", timeout=5) as status:
    payload = json.load(status)
    assert payload["state"] == ("unavailable" if args.phase == "outage" else "connected")
    if args.phase == "coverage":
        assert len(payload["key_counts"]) == 6
        assert all(count >= 2 for count in payload["key_counts"].values())
    print(f"cache state: {payload['state']}; key counts: {payload['key_counts']}")
