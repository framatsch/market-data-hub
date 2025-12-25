import asyncio
import httpx
import sys
from datetime import datetime, timedelta, date

BASE_URL = "http://localhost:8000"

async def test_ibkr_http():
    print(f"--- IBKR HTTP Backend Test (Target: {BASE_URL}) ---")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check Health (Optional, usually /meta/health or similar if exists, skipping for now)

        # 1. Last Price
        symbol = "AAPL"
        print(f"\n[1] Testing Last Price for {symbol} (Provider: ibkr)...")
        try:
            resp = await client.get(f"{BASE_URL}/prices/{symbol}/last", params={"provider": "ibkr"})
            if resp.status_code == 200:
                data = resp.json()
                print("SUCCESS:", data)
            else:
                print(f"FAILED (Status {resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"ERROR: {e}")

        # 2. Historical Prices
        print(f"\n[2] Testing Historical Prices for {symbol} (last 5 days)...")
        try:
            end = datetime.now()
            start = end - timedelta(days=5)
            # Format dates as ISO strings if needed by API? 
            # API takes Query params, usually standard ISO string works for FastAPI datetime
            params = {
                "provider": "ibkr",
                "interval": "1d",
                # "start": start.isoformat(), 
                # "end": end.isoformat() 
                # Note: If start/end skipped, defaults are used. Let's rely on defaults or simple params.
            }
            resp = await client.get(f"{BASE_URL}/prices/{symbol}/history", params=params)
            if resp.status_code == 200:
                data = resp.json()
                bars = data.get("data", [])
                print(f"SUCCESS: Got {len(bars)} bars")
                if bars:
                    print("Sample:", bars[0])
            else:
                print(f"FAILED (Status {resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"ERROR: {e}")

        # 3. Option Chain
        # Need a valid expiry.
        # User hardcoded 2026-01-02 in the previous test. Let's try to pass that or similar.
        expiry = "2026-01-02" # Based on user's manual fix
        print(f"\n[3] Testing Option Chain for {symbol} (Expiry: {expiry})...")
        try:
            resp = await client.get(f"{BASE_URL}/options/{symbol}/chain", params={"provider": "ibkr", "expiry": expiry})
            if resp.status_code == 200:
                data = resp.json()
                chain = data.get("data", {})
                options = chain.get("options", [])
                print(f"SUCCESS: Got {len(options)} options")
                
                # 4. Specific Quote
                if options:
                    
                    # Choose one
                    opt = options[0]
                    # Option ID should be symbol in the list
                    opt_id = opt.get("symbol")
                    print(f"\n[4] Testing Specific Quote for {opt_id}...")
                    
                    # Note: opt_id might contain spaces or special chars, URL encode if needed, 
                    # but httpx handles params. Path param needs care?
                    # Route is /options/{symbol}/quote/{option_id}
                    # If option_id has spaces "AAPL  ...", valid URL encoding is needed.
                    # httpx should handle it if we construct url carefully or let user handle it.
                    # However, path param injection...
                    
                    resp_q = await client.get(f"{BASE_URL}/options/{symbol}/quote/{opt_id}", params={"provider": "ibkr"})
                    if resp_q.status_code == 200:
                        print("SUCCESS:", resp_q.json())
                    else:
                        print(f"FAILED Quote (Status {resp_q.status_code}): {resp_q.text}")

            else:
                print(f"FAILED (Status {resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"ERROR: {e}")

    print("\n--- Test Finished ---")

if __name__ == "__main__":
    asyncio.run(test_ibkr_http())
