# Deployment Resources

This directory contains all deployment configurations for Market Data Hub.

## Files

### `kubernetes.yaml`
Combined Kubernetes manifest containing:
- **ConfigMap**: Non-sensitive configuration (IBKR host/port, app settings)
- **Deployment**: Pod specification with health checks, resource limits, secret/configmap injection
- **Service**: ClusterIP service exposing ports 8000 (HTTP) and 8001 (MCP SSE)

**Usage:**
```bash
# Create namespace first
kubectl create namespace market-data-hub

# Create Kubernetes Secret (manual - never in git!)
kubectl create secret generic market-data-hub-secrets \
  --from-literal=lseg_app_key=$LSEG_APP_KEY \
  --from-literal=lseg_username=$LSEG_USERNAME \
  --from-literal=lseg_password=$LSEG_PASSWORD \
  -n market-data-hub

# Apply deployment
kubectl apply -f kubernetes.yaml -n market-data-hub

# Verify
kubectl get all -n market-data-hub
```

### `secret-template.yaml`
Template showing Kubernetes Secret structure. **Never commit with actual values!**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: market-data-hub-secrets
  labels:
    app: market-data-hub
type: Opaque
data:
  # These values should be base64-encoded
  # Use: echo -n "value" | base64
  lseg_app_key: base64-encoded-app-key-here
  lseg_username: base64-encoded-username-here
  lseg_password: base64-encoded-password-here
```

Use `kubectl create secret` command instead:
```bash
kubectl create secret generic market-data-hub-secrets \
  --from-literal=lseg_app_key=YOUR_KEY \
  --from-literal=lseg_username=YOUR_USER \
  --from-literal=lseg_password=YOUR_PASS
```

## Docker Compose

See root `docker-compose.yml` for local development with Docker Compose.

### Quick Start with Docker Compose

```bash
# 1. Setup environment
cp .env.example .env
# Edit .env with your LSEG credentials

# 2. Build and start
docker-compose up --build

# 3. Access application
# HTTP: http://localhost:8000
# Swagger: http://localhost:8000/docs
# MCP: http://localhost:8001

# 4. View logs
docker-compose logs -f

# 5. Stop
docker-compose down
```

The `docker-compose.yml` automatically:
- Builds the Docker image locally
- Reads environment variables from `.env`
- Mounts source code for live development (`volumes: [.:/app]`)
- Includes health checks
- Exposes both HTTP (8000) and MCP (8001) ports

## Configuration

### Via Environment Variables (.env)

Copy `.env.example` to `.env` and set your values:
```bash
IBKR_HOST=localhost           # IBKR Gateway/TWS host
IBKR_PORT=4002               # Gateway: 4002, TWS Paper: 7497
IBKR_CLIENT_ID=815           # Unique client ID
IBKR_MARKET_DATA_TYPE=2      # 1=Live, 2=Frozen, 3=Delayed
LSEG_APP_KEY=your-key        # REQUIRED - LSEG API key
LSEG_USERNAME=your-email     # REQUIRED - LSEG username
LSEG_PASSWORD=your-password  # REQUIRED - LSEG password
APP_ENV=dev                  # dev, test, prod
LOG_LEVEL=INFO               # DEBUG, INFO, WARNING, ERROR
```

### Via Kubernetes ConfigMap/Secret

Edit `kubernetes.yaml` ConfigMap section for IBKR settings:
```yaml
data:
  ibkr_host: "your-gateway-ip"
  ibkr_port: "4002"
```

Create Secret for LSEG credentials (never in YAML!):
```bash
kubectl create secret generic market-data-hub-secrets \
  --from-literal=lseg_app_key=$LSEG_APP_KEY \
  --from-literal=lseg_username=$LSEG_USERNAME \
  --from-literal=lseg_password=$LSEG_PASSWORD
```

## Scaling & Updates

### Kubernetes

```bash
# Scale replicas
kubectl scale deployment market-data-hub --replicas=3 -n market-data-hub

# Rolling update
kubectl set image deployment/market-data-hub \
  app=ghcr.io/yourusername/market-data-hub:v1.0.0 \
  -n market-data-hub

# Rollback
kubectl rollout undo deployment/market-data-hub -n market-data-hub

# Watch status
kubectl rollout status deployment/market-data-hub -n market-data-hub
```

### Docker Compose

```bash
# Rebuild image
docker-compose up --build

# Scale service (requires docker-compose v1.13+)
docker-compose up -d --scale market-data-hub=3

# View logs from one container
docker-compose logs market-data-hub
```

## Troubleshooting

### Kubernetes Pod Won't Start

```bash
# Check pod status
kubectl describe pod -n market-data-hub <pod-name>

# View logs
kubectl logs -n market-data-hub deployment/market-data-hub

# Check if secrets exist
kubectl get secrets -n market-data-hub
kubectl describe secret market-data-hub-secrets -n market-data-hub

# Check configmap
kubectl get configmap -n market-data-hub
```

### Docker Compose Issues

```bash
# Check service logs
docker-compose logs market-data-hub

# Verify environment variables loaded
docker-compose exec market-data-hub env | grep LSEG

# Test connectivity
docker-compose exec market-data-hub curl http://localhost:8000/health

# Rebuild from scratch
docker-compose down
docker-compose up --build
```

### LSEG Authentication Failed

```bash
# Verify credentials in .env
grep LSEG .env

# Check pod/container environment
# Kubernetes:
kubectl exec -n market-data-hub <pod-name> -- env | grep LSEG

# Docker Compose:
docker-compose exec market-data-hub env | grep LSEG

# Test LSEG connectivity
docker-compose exec market-data-hub python -c \
  "import refinitiv.data as rd; print('LSEG SDK OK')"
```

## See Also

- [Main README](../README.md) - Quick start and feature overview
- [DEPLOYMENT.md](../DEPLOYMENT.md) - Detailed deployment documentation
