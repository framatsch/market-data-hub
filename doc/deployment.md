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

## History Store (optional PostgreSQL)

Closed daily/weekly/hourly/4-hour price bars and daily IV points can be kept in
PostgreSQL, so a history or IV Rank request needs at most one small provider call
(the newest bars) instead of a full download. Without `DATABASE_URL` MDH needs no
PostgreSQL and behaves exactly as before; credentials, provider configuration and
settings stay in SQLite (`KEYS_DB_PATH`) in both cases.

| Variable | Default | Meaning |
|----------|---------|---------|
| `DATABASE_URL` | empty (disabled) | e.g. `postgresql://user:pass@host:5432/mdh` |
| `HISTORY_STORE_RESYNC_SECONDS` | 300 | minimum interval between top-up calls per series |
| `HISTORY_STORE_OVERLAP_BARS` | 5 (2–30) | newest stored bars re-read to detect split revisions |
| `HISTORY_STORE_MIGRATE_ON_STARTUP` | true | apply Alembic migrations at startup (advisory lock) |

**Docker Compose.** Set `DATABASE_URL=postgresql://mdh:mdh@postgres:5432/mdh` in `.env`
and start with the profile: `docker compose --profile postgres up -d`. Without the
profile no PostgreSQL container is started and the store is disabled.

**Kubernetes.** Provide the database outside this repository (same namespace as MDH) and
set `DATABASE_URL` from a secret. Recommended volume: 5 Gi, 10 Gi when `1h` bars are stored.

**Stored intervals** are a provider setting (`history_store_intervals`, default `["1d"]`),
edited in the provider details of the Admin UI and effective without a restart. `1h`, `4h`
and `1w` are derived from smaller bars where a provider does not deliver them natively.

**Behaviour.** Only closed bars are stored; the forming bar always comes from the provider.
A database outage never fails a request (one warning, 30 s cooldown, provider path). When a
provider fails and the stored series covers the range, the stored data is returned with
`meta.stale = true`. Daily bars may come from another provider's series
(`meta.source_provider`); IV never does. Admin: `GET /api/admin/history-store` and
`POST /api/admin/history-store/clear`. Metric: `mdh_history_store_reads_total`.

**Rollback:** unset `DATABASE_URL`; no data migration in either direction.

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
