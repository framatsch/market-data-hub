<div align="center">

![# Market Data Hub Logo](logo.svg)

# Market Data Hub

</div>


Market Data Hub (MDH) is a focused, production-ready aggregation service for market data. It unifies multiple providers (IBKR, LSEG/Refinitiv, Polygon, Prixe, and Finnhub for news) behind a single, consistent REST/WebSocket API and an MCP server, so your apps can query prices, options, companies, and news without coupling to any one vendor.

**What It Does**
- Aggregates real-time and delayed market data from IBKR, LSEG, Polygon, and Prixe
- Provides options chains and quotes (IBKR), equity prices (IBKR and LSEG), company profiles, and news
- Exposes a clean, provider-agnostic API surface with strong Pydantic models
- Runs reliably in Docker and Kubernetes; supports managed IBKR Gateway

**Why It Exists**
- Broker and data APIs differ wildly; this hub standardizes responses, typing (Decimal for financials), and error handling
- Lets you choose the provider per request (or set sensible defaults) while keeping identical response formats
- Gracefully degrades when certain entitlements are missing (e.g., IBKR Level 2), and documents when behavior differs across providers

**Key Capabilities**
- Prices: latest quotes and historical bars
- Options: chains and quotes with Greeks (IBKR only)
- Companies: profiles, basic search (LSEG)
- News: institutional-grade headlines (LSEG) and alternative news (Finnhub)

**Providers & Data Types**
- IBKR: real-time equities and options; supports `market_data_type` (1=Live/Level 2, 2=Frozen, 3=Delayed)
- LSEG: equity prices via daily summaries; ignores `market_data_type`; not suitable for options Greeks
- Polygon: equity quotes and historical OHLCV (1m-1w granularity)
- Prixe: latest stock price via `POST /api/last_sold` (Bearer token)
- Finnhub: supplemental news and company data for fallback scenarios

**Behavior Highlights**
- `market_data_type` defaults to 3 (Delayed) for IBKR, minimizing subscription requirements
- If you request IBKR Level 1 (Live) without entitlements, the API returns HTTP 503 with a clear error code (`PROVIDER_NOT_AVAILABLE`)
- LSEG returns the latest daily summary and logs an informational message when `market_data_type` is provided (and ignored)

**How It Works**
- API Layer (FastAPI) -> Service Layer -> Provider Layer (IBKR/LSEG/Polygon/Prixe/Finnhub)
- Strong Pydantic models ensure type-safety (Decimal for prices, Optional fields for missing data)
- Async-first with `ib_async` for IBKR; synchronous session management for LSEG SDK

**Quick Examples**
- Last price (IBKR, delayed by default):
  - curl "http://localhost:8000/prices/IWM/last?provider=ibkr&market_data_type=3"
- Last price (LSEG, daily summary):
  - curl "http://localhost:8000/prices/IWM/last?provider=lseg"
- Last price (Prixe):
  - curl "http://localhost:8000/prices/IWM/last?provider=prixe"
- Option chain (IBKR only):
  - curl "http://localhost:8000/options/IWM/chain?expiry=2026-01-13&min_strike=227&max_strike=277&market_data_type=3"

See below for setup, configuration, and deployment.

## Quick Start

### Prerequisites
- Python 3.12+
- Docker & Docker Compose (optional, for containerized deployment)
- IBKR Gateway/TWS running (for price data)
- LSEG credentials (for company/fundamental data)

### Option 1: Local Development (HTTP Mode)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create and configure .env file
cp .env.example .env
# Edit .env with your LSEG credentials:
#   LSEG_APP_KEY=your-app-key
#   LSEG_USERNAME=your-username
#   LSEG_PASSWORD=your-password

# 3. Run HTTP server
python -m app.main http

# 4. Access Swagger docs
# Open http://localhost:8000/docs
```

### Option 2: Docker Compose (Recommended for Local Dev)

```bash
# 1. Create .env file with your LSEG credentials
cp .env.example .env
# Edit .env with actual values

# 2. Build and run (builds image automatically)
docker-compose up

# 3. Access Swagger docs
# Open http://localhost:8000/docs

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Option 3: Kubernetes Deployment

See [Kubernetes Deployment](#kubernetes-deployment) section below.

## Provider Matrix

**Recommended provider for each data type:**

| Data Type | Primary Provider | Fallback | Reason |
|-----------|-----------------|----------|--------|
| **Stock Prices** | IBKR | LSEG | IBKR provides real-time market data |
| **Historical OHLCV** |  | IBKR, LSEG |  history back to 1985; no extra subscription needed |
| **Options** | **IBKR ONLY** | - | LSEG and  lack real-time options Greeks |
| **Company Data** | LSEG | Finnhub | LSEG has comprehensive fundamentals |
| **News** | LSEG | Finnhub | LSEG provides institutional-grade news |

### ⚠️ LSEG Options Limitation

**LSEG does NOT support options data.** The current LSEG subscription lacks the required `trapi.data.pricing.read` API scope for real-time option pricing and Greeks.

**Attempted workaround (removed):** Previous implementation included Black-Scholes fallback calculations, but these proved unreliable (30-50% error for American options) and production-unsuitable.

**Solution:** Use IBKR exclusively for options data. IBKR provides:
- ✅ Real-time Greeks (Delta, Gamma, Vega, Theta, IV)
- ✅ Server-calculated values (not theoretical models)
- ✅ Support for American options
- ✅ Market microstructure (Bid/Ask spreads, Open Interest)

## Configuration

Configuration via environment variables (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `IBKR_HOST` | `localhost` | Interactive Brokers Gateway/TWS host |
| `IBKR_PORT` | `4002` | Gateway: 4002, TWS Paper: 7497, TWS Live: 7496 |
| `IBKR_CLIENT_ID` | `815` | Unique client ID for connection |
| `IBKR_MARKET_DATA_TYPE` | `3` | 1=Live, 2=Frozen, 3=Delayed (default; free) |
| `LSEG_APP_KEY` | *(required)* | LSEG application API key |
| `LSEG_USERNAME` | *(required)* | LSEG Workspace username (email) |
| `LSEG_PASSWORD` | *(required)* | LSEG Workspace password |
| `FINNHUB_API_KEY` | `stub-key` | Finnhub API key (get from finnhub.io/dashboard) |
| `FINNHUB_RATE_LIMIT_PER_MIN` | `60` | API rate limit (60 for free tier) |
| `FINNHUB_FALLBACK_ON_RATE_LIMIT` | `true` | Fallback to mock provider when rate limited |
| `APP_ENV` | `dev` | Environment: dev, test, prod |
| `LOG_LEVEL` | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `DEFAULT_PRICE_PROVIDER` | `ibkr` | Default provider: ibkr, lseg, polygon, prixe |
| `PRIXE_API_KEY` | *(empty)* | Prixe API key (Bearer token) |
| `PRIXE_BASE_URL` | `https://api.prixe.io` | Prixe API base URL |
| `SCHWAB_API_KEY` | *(empty)* |  app key — leave empty to disable provider |
| `SCHWAB_APP_SECRET` | *(empty)* |  app secret from developer portal |
| `SCHWAB_CALLBACK_URL` | `https://127.0.0.1:8182` | Must match app config exactly (including trailing slash) |
| `SCHWAB_TOKEN_PATH` | `/tmp/_token.json` | Path to OAuth2 token file (managed by -py) |
| `SCHWAB_TIMEOUT_SECONDS` | `30` | HTTP request timeout |
| `SCHWAB_RATE_LIMIT_PER_SEC` | `5` | Max API calls per second |
| `SCHWAB_ASYNCIO` | `true` | Create  async client (`-py` asyncio mode) |

### LSEG Credentials Setup

To access Refinitiv/LSEG data, obtain credentials from [LSEG Developer Portal](https://developer.lseg.com/):

1. Create or sign in to your LSEG account
2. Generate API key in Developer Portal
3. Note your LSEG Workspace username (typically email address)
4. Set credentials in `.env`:
   ```bash
   LSEG_APP_KEY=your-key-here
   LSEG_USERNAME=your-email@example.com
   LSEG_PASSWORD=your-password-here
   ```

**Note**: Data access requires active LSEG subscription with appropriate entitlements for the data types you retrieve.

### Finnhub Credentials Setup

To access company news and data from Finnhub (fallback provider), obtain an API key from [Finnhub.io](https://finnhub.io/):

1. Sign up for a free account at [finnhub.io/register](https://finnhub.io/register)
2. Get your API key from the [Dashboard](https://finnhub.io/dashboard)
3. Set the API key in `.env`:
   ```bash
   FINNHUB_API_KEY=your-api-key-here
   ```

**Rate Limits**:
- Free tier: 60 API calls per minute
- Premium: 300-600 calls/min depending on plan
- Rate limit handling: Automatically falls back to mock provider when limit exceeded (configurable via `FINNHUB_FALLBACK_ON_RATE_LIMIT`)

See [doc/news-api-guide.md](doc/news-api-guide.md) for detailed news API usage and testing.

###  Credentials Setup

 requires OAuth2 authentication via the [ Developer Portal](https://developer..com/). The `-py` library manages the token lifecycle automatically once set up.

#### 1. Create a  developer app

1. Sign in at [developer..com](https://developer..com/)
2. Create a new app under **Products → Trader API – Individual**
3. Set the callback URL to `https://127.0.0.1:8182` (or another `https://127.0.0.1:<port>` URL)
4. Note your **App Key** and **App Secret**

> **App approval delay:** New and modified apps enter an `Approved - Pending` state and require manual review by . This typically takes a few days. Until the status shows **Ready for Use**, API calls will return `401` errors.

#### 2. Generate the token (one-time per machine)

Run the token generator on a machine with a browser:

```bash
-generate-token.py \
  --token_file /path/to/_token.json \
  --api_key YOUR_APP_KEY \
  --app_secret YOUR_APP_SECRET \
  --callback_url https://127.0.0.1:8182
```

A browser window will open. Log in with your  brokerage account. After redirecting, the token file is written automatically.

> Your browser will warn about an invalid/self-signed certificate on the callback URL — this is expected. Proceed anyway, but verify the address matches your callback URL.

#### 3. Configure `.env`

```bash
SCHWAB_API_KEY=your-app-key-here
SCHWAB_APP_SECRET=your-app-secret-here
SCHWAB_CALLBACK_URL=https://127.0.0.1:8182
SCHWAB_TOKEN_PATH=/path/to/_token.json
```

#### 4. Token rotation (every 7 days)

 refresh tokens expire after **7 days**. Re-run `-generate-token.py` weekly before the token expires, or set a cron job:

```bash
# Example: regenerate token every Sunday at 08:00
0 8 * * 0 -generate-token.py --token_file /path/to/token.json --api_key $SCHWAB_API_KEY --app_secret $SCHWAB_APP_SECRET --callback_url https://127.0.0.1:8182
```

#### 5. Containerized / headless deployments

The login flow requires a browser. For servers:

1. Generate the token on a local machine (step 2 above)
2. Copy `_token.json` to the server / mount it as a secret
3. **Never share or commit the token file** — it grants full account access

**Do not** create, edit, or copy-paste the JSON contents manually. The token file is managed exclusively by `-py`.

#### Verify the setup

```bash
# Check provider is active (requires running server)
curl http://localhost:8000/providers | python -m json.tool

# Fetch historical daily prices via 
curl "http://localhost:8000/prices/history/AAPL?interval=1d&period=1y&provider="
```

## Running Modes

```bash
# HTTP REST API + optional MCP (single process, port 8000)
python -m app.main

# With MCP enabled (exposes /mcp/sse and /mcp/messages on port 8000)
MCP_ENABLED=true python -m app.main

# Docker Compose
docker-compose up

# Docker with MCP enabled
docker run -p 8000:8000 \
  --env-file .env \
  -e MCP_ENABLED=true \
  market-data-hub:latest
```

### MCP Integration

When `MCP_ENABLED=true`, the MCP (Model Context Protocol) endpoints are available at:

| Endpoint | Description |
|----------|-------------|
| `GET  /mcp/sse` | SSE stream — establishes a session and receives tool results |
| `POST /mcp/messages?session_id=<id>` | JSON-RPC 2.0 tool calls |

Connect an MCP client to `http://localhost:8000/mcp/sse`.

Available MCP tools: `get_last_price`, `get_historical_prices`, `get_option_chain`, `get_option_quote`, `get_company_profile`, `search_companies`, `get_company_news`.

For more details on connecting clients and using the tools, see the [MCP Guide](doc/mcp-guide.md).

## Architecture

This service implements the **Aggregator Pattern**:
- **API Layer**: Exposes unified REST and WebSocket endpoints.
- **Service Layer**: Orchestrates data fetching and business logic.
- **Provider Layer**: Abstracts external APIs (IBKR, LSEG) via strict interfaces.

## API Examples

### Health Check
```bash
curl http://localhost:8000/health
```

### Get Last Price
```bash
curl "http://localhost:8000/prices/AAPL/last?provider=ibkr&market_data_type=3"
```

Provider behavior for `/prices/{symbol}/last`:
- IBKR: honors `market_data_type` (1=Live, 2=Frozen, 3=Delayed). Level 1 requires subscription; if unavailable, returns HTTP 503.
- LSEG: ignores `market_data_type` and returns the latest daily summary via Refinitiv `historical_pricing.summaries`.

### Get Company Profile
```bash
curl "http://localhost:8000/companies/AAPL?provider=lseg"
```

### WebSocket Prices
Connect to `ws://localhost:8000/ws/prices` and send:
```json
{"type": "subscribe", "symbols": ["AAPL"], "provider": "ibkr"}
```

## Kubernetes Deployment

### Prerequisites
- kubectl configured with cluster access
- Kubernetes 1.19+
- IBKR Gateway accessible from cluster

### Setup Steps

```bash
# 1. Create namespace
kubectl create namespace market-data-hub

# 2. Create Kubernetes Secret from environment variables
kubectl create secret generic market-data-hub-secrets \
  --from-literal=lseg_app_key=$LSEG_APP_KEY \
  --from-literal=lseg_username=$LSEG_USERNAME \
  --from-literal=lseg_password=$LSEG_PASSWORD \
  -n market-data-hub

# 3. Update image reference in deploy/kubernetes.yaml
# Replace: ghcr.io/yourusername/market-data-hub:latest
sed -i 's|ghcr.io/yourusername/market-data-hub:latest|ghcr.io/YOUR_USERNAME/market-data-hub:latest|g' deploy/kubernetes.yaml

# 4. Apply Kubernetes resources (all-in-one file)
kubectl apply -f deploy/kubernetes.yaml -n market-data-hub

# 5. Verify deployment
kubectl get pods -n market-data-hub
kubectl logs -n market-data-hub deployment/market-data-hub

# 6. Port forward for local testing
kubectl port-forward -n market-data-hub svc/market-data-hub 8000:8000 &
curl http://localhost:8000/health
```

### Update Deployment

```bash
# Update with new image
kubectl set image deployment/market-data-hub \
  app=ghcr.io/username/market-data-hub:v1.0.0 \
  -n market-data-hub

# Watch rollout
kubectl rollout status deployment/market-data-hub -n market-data-hub

# Rollback if needed
kubectl rollout undo deployment/market-data-hub -n market-data-hub
```

### Cleanup

```bash
# Remove all resources
kubectl delete -f deploy/kubernetes.yaml -n market-data-hub
kubectl delete namespace market-data-hub
```

## Docker Image Building & Pushing

### Local Build
```bash
docker build -t market-data-hub:latest .
```

### Push to GitHub Container Registry (GHCR)
```bash
# Automatic via GitHub Actions on push to main/develop or tag creation
# Images pushed to: ghcr.io/yourusername/market-data-hub:latest

# Or manual push:
docker login ghcr.io -u USERNAME -p TOKEN
docker tag market-data-hub:latest ghcr.io/yourusername/market-data-hub:latest
docker push ghcr.io/yourusername/market-data-hub:latest
```

### Docker Compose Auto-Build
The `docker-compose.yml` automatically builds the image locally:
```bash
docker-compose up --build  # Force rebuild
docker-compose up          # Use cache if available
```

## Deployment Files

All deployment resources are in the `deploy/` directory:

| File | Purpose |
|---|---|
| `kubernetes.yaml` | Combined K8s ConfigMap, Deployment, Service manifest |
| `secret-template.yaml` | Template showing Secret structure (never commit with real values) |
| `.env.example` | Environment variables template |

See [doc/deployment.md](doc/deployment.md) for detailed deployment documentation.

## Development

### Running Tests
```bash
pytest --maxfail=1 --disable-warnings
```

### Code Linting
```bash
ruff check .
```

### API Documentation
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
