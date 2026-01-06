# Market Data Hub

A FastAPI-based data service that aggregates market and company data from multiple external providers (IBKR, LSEG) in a clean, provider-agnostic REST/WebSocket API with MCP (Model Context Protocol) support.

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
| **Options** | **IBKR ONLY** | - | LSEG lacks `trapi.data.pricing.read` scope for Greeks |
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
| `IBKR_MARKET_DATA_TYPE` | `2` | 1=Live, 2=Frozen, 3=Delayed |
| `LSEG_APP_KEY` | *(required)* | LSEG application API key |
| `LSEG_USERNAME` | *(required)* | LSEG Workspace username (email) |
| `LSEG_PASSWORD` | *(required)* | LSEG Workspace password |
| `APP_ENV` | `dev` | Environment: dev, test, prod |
| `LOG_LEVEL` | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `DEFAULT_PRICE_PROVIDER` | `ibkr` | Default provider: ibkr, lseg |

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

## Running Modes

```bash
# HTTP REST API (port 8000)
python -m app.main http

# MCP SSE Protocol (port 8001)
python -m app.main mcp

# Both services in parallel (ports 8000 + 8001)
python -m app.main both

# Docker Compose (HTTP mode by default)
docker-compose up

# Docker - custom mode
docker run -p 8000:8000 \
  --env-file .env \
  market-data-hub:latest \
  python -m app.main http
```

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
curl "http://localhost:8000/prices/AAPL/last?provider=ibkr"
```

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

See [DEPLOYMENT.md](./DEPLOYMENT.md) for detailed deployment documentation.

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
