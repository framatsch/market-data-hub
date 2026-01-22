````markdown
# IBKR HTTP Backend Test Plan

This document outlines the steps to verify the IBKR provider integration through the HTTP backend (FastAPI).

## Prerequisites
1. **IBKR TWS or Gateway** running (default: 127.0.0.1:4001 or as configured).
2. **API Settings** in TWS:
   - "Enable ActiveX and Socket Clients" is **Check**.
   - "Trusted IPs": Add `127.0.0.1`.
3. **Application Running**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

## Test Cases

### 1. Market Price Snapshot
**Endpoint**: `GET /prices/{symbol}/last`
**Description**: Fetches the latest price snapshot.
**Test**:
```bash
curl "http://localhost:8000/prices/AAPL/last?provider=ibkr"
```
**Expected Result**:
- Status: 200 OK
- Body contains `price`, `bid`, `ask` similar to TWS.

### 2. Historical Prices
**Endpoint**: `GET /prices/{symbol}/history`
**Description**: Fetches daily bars for the last 30 days.
**Test**:
```bash
curl "http://localhost:8000/prices/AAPL/history?provider=ibkr&interval=1d"
```
**Expected Result**:
- Status: 200 OK
- Body is a list of bars with `open`, `high`, `low`, `close` matching recent chart data.

### 3. Option Chain
**Endpoint**: `GET /options/{symbol}/chain`
**Description**: Fetches option chain for a future expiry.
**Test**:
```bash
# Note: You might need to find a valid expiry date (e.g. standard monthly expiry).
# The API defaults to +30 days if not specified, which might not be a valid expiry.
# Check TWS for a valid expiry, e.g., 2026-01-16
curl "http://localhost:8000/options/AAPL/chain?expiry=2026-01-16&provider=ibkr"
```
**Expected Result**:
- Status: 200 OK
- Returns list of Call/Put options with strikes and prices.

### 4. Specific Option Quote
**Endpoint**: `GET /options/{symbol}/quote/{option_id}`
**Description**: Fetches quote for a specific option contract.
**Test**:
```bash
# Obtain an 'option_id' (e.g. localSymbol 'AAPL  240119C00150000') from the chain response above.
curl "http://localhost:8000/options/AAPL/quote/AAPL..LOCALS..SYMBOL?provider=ibkr"
```
**Expected Result**:
- Status: 200 OK
- Returns detailed quote for that option.

## Automated Verification script
A script `tests/integration/test_ibkr_http.py` is provided to run these tests automatically.
Usage:
```bash
python3 tests/integration/test_ibkr_http.py
```

````