# Provider Setup Guide

This guide provides step-by-step instructions for configuring the different market data providers in the Market Data Hub.

## 1. Polygon.io Setup (Recommended for US Stocks & Options)

Polygon.io provides a modern REST API for high-performance market data. It is the easiest provider to set up and highly reliable for US markets.

**Steps:**
1.  Go to [Polygon.io](https://polygon.io/) and create an account.
2.  Navigate to your **Dashboard** to find your **API Key**.
3.  Add the key to your `.env` file:
    ```env
    POLYGON_API_KEY=your_actual_key_here
    ```
4.  (Optional) Set Polygon as your default provider for prices:
    ```env
    DEFAULT_PRICE_PROVIDER=polygon
    ```

**Supported Features:**
- Real-time Stock NBBO Quotes
- Real-time Options OPRA Quotes (includes Greeks & IV)
- Historical Aggregates (1m, 5m, 1h, 1d)
- Ticker Details & Market Status

## 2. Prixe Setup (Simple REST Price Provider)

Prixe is a lightweight REST provider for latest stock prices via `POST /api/last_sold`.

**Steps:**
1. Go to [Prixe](https://prixe.io) and create an account.
2. Generate or copy your API key from the Prixe dashboard.
3. Add the key to your `.env` file:
   ```env
   PRIXE_API_KEY=your-prixe-api-key
   ```
4. (Optional) Set Prixe as default price provider:
   ```env
   DEFAULT_PRICE_PROVIDER=prixe
   ```
5. (Optional) Override base URL only if needed (default is already set in config):
   ```env
   PRIXE_BASE_URL=https://api.prixe.io
   ```

**Current Supported Features:**
- Last sold price lookup (`/prices/{symbol}/last?provider=prixe`)
- Bearer token authentication via `PRIXE_API_KEY`
- Mapping to internal `PriceQuote` model (`Decimal` for monetary values)

**Notes:**
- If `PRIXE_API_KEY` is missing, the provider fails initialization and is treated as unavailable.
- Historical prices are not implemented yet for Prixe.

## 3. LSEG (Refinitiv) Setup

LSEG (formerly Refinitiv) is used for detailed company fundamentals, global prices, and news.

**Steps:**
1.  You need an active **LSEG Workspace** or **Data Platform** account.
2.  Create an **App Key** in the LSEG Developer Portal.
3.  Add your credentials to your `.env` file:
    ```env
    LSEG_APP_KEY=your_app_key
    LSEG_USERNAME=your_username
    LSEG_PASSWORD=your_password
    ```

**Advanced Configuration:**
- **Rate Limiting**: Controlled via `LSEG_RATE_LIMIT_PER_SEC` (default: 10).
- **Caching**: Quote data is cached for `LSEG_CACHE_TTL_SECONDS` (default: 5).
- **Session Type**: This hub uses the **Platform Session** (Cloud). If you need to use a local Workspace Desktop session, ensure your Workspace app is running and the API proxy is active.

**Supported Features:**
- Global Stock Prices (Historical Summaries)
- In-depth Company Fundamentals (SIC codes, employee counts, etc.)
- Global News Feed

## 4. Interactive Brokers (IBKR) Setup

IBKR is used for global trading data and deep options liquidity. It requires a running instance of IB Gateway or TWS.

**Steps:**
1.  Install and run **IB Gateway** or **TWS**.
2.  In TWS/Gateway settings, go to `Configuration -> API -> Settings`:
    - Enable **"ActiveX and Socket Clients"**.
    - Disable **"Read-Only API"** (if you want to place orders in the future).
    - Note the **"Socket Port"** (default 4002 for Paper, 4001 for Live).
3.  Ensure the port matches your `.env`:
    ```env
    IBKR_HOST=localhost
    IBKR_PORT=4002
    IBKR_CLIENT_ID=815
    ```

**Market Data Types (`IBKR_MARKET_DATA_TYPE`):**
- `1`: **Live** (Requires paid subscriptions for every exchange).
- `2`: **Frozen** (Data from market close).
- `3`: **Delayed** (Default - free, no subscription required, usually 15-20 min delay).
- `4`: **Delayed Frozen**.

**Supported Features:**
- Global Real-time Quotes (Stocks, Options, Futures, FX)
- Advanced Option Chains & Greeks
- Historical Data (Intraday and Daily)

## 5. Finnhub Setup (News)

Finnhub is the primary provider for real-time news and sentiment analysis.

**Steps:**
1.  Get a free API key at [Finnhub.io](https://finnhub.io/).
2.  Add it to your `.env` file:
    ```env
    FINNHUB_API_KEY=your_finnhub_key
    ```

**Note:** The free tier is limited to 60 calls per minute. The hub will automatically log a warning if you hit this limit.

---

## Troubleshooting

### "Provider Unavailable" in Startup Protocol
- **Check Keys**: Ensure the key in `.env` has no trailing spaces.
- **Missing Dependencies**: Some providers (like LSEG) require specific libraries. Check Docker logs for `ImportError`.
- **Connectivity**: For IBKR, ensure the Gateway is actually running and "Socket Port" matches.

### "Data Not Found" (404)
- **Symbology**: Different providers use different formats.
    - Polygon: `AAPL` (Stock), `O:AAPL...` (Option)
    - LSEG: `AAPL.O` (RIC format) - the hub handles this automatically.
    - IBKR: `AAPL` (Symbol) - the hub handles contract lookup.

### CORS Errors in MCP Inspector
- Ensure `APP_ENV=dev` or check that `CORSMiddleware` in `app/main.py` allows your origin.


---

## Summary: Recommended `.env` Configuration

For a fully functional setup with all features enabled, your `.env` should look like this:

```env
# Core
APP_ENV=dev
MCP_ENABLED=true
ENABLED_PROVIDERS=polygon,prixe,ibkr,finnhub,lseg

# Polygon (High-speed Stocks/Options)
POLYGON_API_KEY=xxx

# Prixe (Simple latest-price endpoint)
PRIXE_API_KEY=xxx

# LSEG (Company Fundamentals)
LSEG_APP_KEY=xxx
LSEG_USERNAME=xxx
LSEG_PASSWORD=xxx

# IBKR (Real-time fallback)
IBKR_HOST=localhost
IBKR_PORT=4002

# Finnhub (News)
FINNHUB_API_KEY=xxx
```
