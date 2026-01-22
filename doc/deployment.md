# Market Data Hub - Deployment Guide

This guide covers deploying Market Data Hub using Docker and Kubernetes.

## Quick Start (Local Development)

### Prerequisites
- Python 3.12+
- pip or uv package manager

### Installation & Running

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start HTTP server (FastAPI)
python -m app.main http

# 3. Test endpoint
curl http://localhost:8000/health
```

Available modes:

```bash
# HTTP mode (FastAPI REST API)
python -m app.main http

# MCP mode (SSE Protocol)
python -m app.main mcp

# Both modes
python -m app.main both
```

---

## Docker Deployment

### Build Locally

```bash
# Build image
docker build -t market-data-hub:latest .
```

### Run Locally (HTTP)

```bash
docker run -p 8000:8000 \
  -e IBKR_HOST=host.docker.internal \
  -e IBKR_PORT=4002 \
  -e IBKR_CLIENT_ID=815 \
  -e IBKR_MARKET_DATA_TYPE=2 \
  -e LSEG_APP_KEY=$LSEG_APP_KEY \
  -e LSEG_USERNAME=$LSEG_USERNAME \
  -e LSEG_PASSWORD=$LSEG_PASSWORD \
  market-data-hub:latest \
  python -m app.main http
```

### Run Locally (MCP SSE)

```bash
docker run -p 8001:8001 \
  -e IBKR_HOST=host.docker.internal \
  -e IBKR_PORT=4002 \
  -e IBKR_CLIENT_ID=815 \
  -e IBKR_MARKET_DATA_TYPE=2 \
  -e LSEG_APP_KEY=$LSEG_APP_KEY \
  -e LSEG_USERNAME=$LSEG_USERNAME \
  -e LSEG_PASSWORD=$LSEG_PASSWORD \
  market-data-hub:latest \
  python -m app.main mcp
```

---

## Kubernetes (Summary)

### 1) Namespace
```bash
kubectl create namespace market-data-hub
```

### 2) Secrets (LSEG)
```bash
kubectl create secret generic market-data-hub-secrets \
  --from-literal=lseg_app_key=$LSEG_APP_KEY \
  --from-literal=lseg_username=$LSEG_USERNAME \
  --from-literal=lseg_password=$LSEG_PASSWORD \
  -n market-data-hub
```

### 3) ConfigMap (IBKR/App)
```bash
kubectl create configmap market-data-hub-config \
  --from-literal=ibkr_host=172.31.16.1 \
  --from-literal=ibkr_port=4002 \
  --from-literal=ibkr_client_id=815 \
  --from-literal=ibkr_market_data_type=2 \
  --from-literal=app_env=prod \
  --from-literal=log_level=INFO \
  --from-literal=default_price_provider=ibkr \
  -n market-data-hub
```

### 4) Apply Manifests
```bash
kubectl apply -f k8s/deployment.yaml -n market-data-hub
kubectl apply -f k8s/service.yaml -n market-data-hub
```

### 5) Verify
```bash
kubectl get pods -n market-data-hub
kubectl logs -n market-data-hub deployment/market-data-hub
```

---

## Environment Variables Reference

### IBKR
- `IBKR_HOST`: Gateway/TWS host
- `IBKR_PORT`: Gateway 4002, TWS Paper 7497, TWS Live 7496
- `IBKR_CLIENT_ID`: Unique client ID
- `IBKR_MARKET_DATA_TYPE`: 1=Live, 2=Frozen, 3=Delayed

### LSEG
- `LSEG_APP_KEY`, `LSEG_USERNAME`, `LSEG_PASSWORD`

### App
- `APP_ENV` (dev/test/prod), `LOG_LEVEL`, `DEFAULT_PRICE_PROVIDER`

---

## Troubleshooting (Quick)
- IBKR connect fails → Verify TWS/Gateway running and host/port
- LSEG errors → Check credentials/scope
- Health check → `curl http://localhost:8000/health`
