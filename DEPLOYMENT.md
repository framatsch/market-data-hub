# Market Data Hub - Deployment Guide

This guide covers deploying Market Data Hub using Docker, Kubernetes, and GitHub Actions.

## Quick Start (Local Development)

### Prerequisites
- Python 3.12+
- pip or uv package manager
- FastAPI/Uvicorn installed

### Installation & Running

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start HTTP server only (default)
python -m app.main http

# 3. In another terminal, test endpoint
curl http://localhost:8000/health

# Expected response:
# {"status": "ok"}
```

### Available Modes

```bash
# HTTP mode (FastAPI REST API)
python -m app.main http
# Runs on port 8000

# MCP mode (MCP SSE Protocol)
python -m app.main mcp
# Runs on port 8001

# Both modes (parallel operation)
python -m app.main both
# HTTP on 8000, MCP on 8001
```

---

## Docker Deployment

### Build Locally

```bash
# Build image
docker build -t market-data-hub:latest .

# Verify image
docker images | grep market-data-hub
```

### Run Locally

#### HTTP Mode (REST API)

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

#### MCP Mode (SSE Protocol)

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

#### Both Modes (with Docker Compose)

Create `docker-compose.yml`:
```yaml
version: "3.8"

services:
  market-data-hub-http:
    image: market-data-hub:latest
    ports:
      - "8000:8000"
    environment:
      IBKR_HOST: host.docker.internal
      IBKR_PORT: 4002
      IBKR_CLIENT_ID: 815
      IBKR_MARKET_DATA_TYPE: 2
      LSEG_APP_KEY: ${LSEG_APP_KEY}
      LSEG_USERNAME: ${LSEG_USERNAME}
      LSEG_PASSWORD: ${LSEG_PASSWORD}
    command: python -m app.main http

  market-data-hub-mcp:
    image: market-data-hub:latest
    ports:
      - "8001:8001"
    environment:
      IBKR_HOST: host.docker.internal
      IBKR_PORT: 4002
      IBKR_CLIENT_ID: 815
      IBKR_MARKET_DATA_TYPE: 2
      LSEG_APP_KEY: ${LSEG_APP_KEY}
      LSEG_USERNAME: ${LSEG_USERNAME}
      LSEG_PASSWORD: ${LSEG_PASSWORD}
    command: python -m app.main mcp
```

Run:
```bash
docker-compose up -d
docker-compose logs -f
```

---

## GitHub Container Registry (GHCR) Setup

### Automatic via GitHub Actions

The CI/CD workflow automatically builds and pushes images to GHCR on:
- Push to `main` or `develop` branches
- Create git tag starting with `v*` (e.g., `v1.0.0`)

**No manual setup required!** GitHub Actions uses the built-in `GITHUB_TOKEN`.

### Verify Image in Registry

After workflow completes:
```bash
# Check registry
echo ${{ github.repository }}
# Example: yourusername/market-data-hub

# View image
# https://github.com/yourusername/market-data-hub/pkgs/container/market-data-hub

# Pull image locally
docker login ghcr.io -u USERNAME -p TOKEN
docker pull ghcr.io/yourusername/market-data-hub:latest
```

### Image Tags Generated

```
ghcr.io/yourusername/market-data-hub:main           # Latest on main
ghcr.io/yourusername/market-data-hub:develop        # Latest on develop
ghcr.io/yourusername/market-data-hub:sha-a1b2c3d   # Specific commit
ghcr.io/yourusername/market-data-hub:v1.0.0        # Semantic version tag
```

### Private Registry Setup (Optional)

If you prefer a private registry instead of GHCR:

1. Create registry secret in GitHub:
   - Go to: Settings → Secrets and variables → Actions
   - Add `PRIVATE_REGISTRY_URL`, `PRIVATE_REGISTRY_USERNAME`, `PRIVATE_REGISTRY_PASSWORD`

2. Update `.github/workflows/ci.yml`:
   ```yaml
   - name: Log in to Private Registry
     uses: docker/login-action@v3
     with:
       registry: ${{ secrets.PRIVATE_REGISTRY_URL }}
       username: ${{ secrets.PRIVATE_REGISTRY_USERNAME }}
       password: ${{ secrets.PRIVATE_REGISTRY_PASSWORD }}
   ```

3. Update image references in deployment.yaml

---

## Kubernetes Deployment

### Prerequisites

- kubectl configured with cluster access
- Kubernetes 1.19+
- IBKR Gateway or TWS running (accessible from cluster)

### 1. Create Namespace

```bash
kubectl create namespace market-data-hub
```

### 2. Create Secrets from .env

**⚠️ IMPORTANT: Never commit .env file with secrets!**

```bash
# Create secrets from environment variables
kubectl create secret generic market-data-hub-secrets \
  --from-literal=lseg_app_key=$LSEG_APP_KEY \
  --from-literal=lseg_username=$LSEG_USERNAME \
  --from-literal=lseg_password=$LSEG_PASSWORD \
  -n market-data-hub

# Verify (shows only key names, not values)
kubectl get secrets -n market-data-hub
kubectl describe secret market-data-hub-secrets -n market-data-hub
```

**For CI/CD, store secrets as GitHub Repository Secrets**, then reference in workflow:
```bash
kubectl create secret generic market-data-hub-secrets \
  --from-literal=lseg_app_key=${{ secrets.LSEG_APP_KEY }} \
  --from-literal=lseg_username=${{ secrets.LSEG_USERNAME }} \
  --from-literal=lseg_password=${{ secrets.LSEG_PASSWORD }} \
  -n market-data-hub
```

### 3. Create ConfigMap

```bash
# Create ConfigMap for non-sensitive configuration
kubectl create configmap market-data-hub-config \
  --from-literal=ibkr_host=172.31.16.1 \
  --from-literal=ibkr_port=4002 \
  --from-literal=ibkr_client_id=815 \
  --from-literal=ibkr_market_data_type=2 \
  --from-literal=app_env=prod \
  --from-literal=log_level=INFO \
  --from-literal=default_price_provider=ibkr \
  -n market-data-hub

# Verify
kubectl get configmap market-data-hub-config -n market-data-hub -o yaml
```

### 4. Update Deployment Image Reference

Edit `k8s/deployment.yaml` and update the image:
```yaml
image: ghcr.io/yourusername/market-data-hub:latest
```

### 5. Apply Kubernetes Resources

```bash
# Apply ConfigMap
kubectl apply -f k8s/configmap.yaml -n market-data-hub

# Apply Deployment
kubectl apply -f k8s/deployment.yaml -n market-data-hub

# Apply Service
kubectl apply -f k8s/service.yaml -n market-data-hub

# Verify deployment
kubectl get pods -n market-data-hub
kubectl get svc -n market-data-hub
kubectl get configmap -n market-data-hub
kubectl get secret -n market-data-hub
```

### 6. Verify Deployment

```bash
# Watch pod status
kubectl get pods -n market-data-hub -w

# Check pod logs
kubectl logs -n market-data-hub deployment/market-data-hub

# Describe deployment for events
kubectl describe deployment market-data-hub -n market-data-hub

# Verify environment variables
kubectl exec -n market-data-hub $(kubectl get pods -n market-data-hub -o name | head -1) -- env | grep -E "(IBKR|LSEG|APP)"
```

### 7. Access Application

#### Port Forward (Local Testing)

```bash
# Forward HTTP port (8000)
kubectl port-forward -n market-data-hub svc/market-data-hub 8000:8000 &

# Forward MCP SSE port (8001)
kubectl port-forward -n market-data-hub svc/market-data-hub 8001:8001 &

# Test endpoints
curl http://localhost:8000/health
curl -N http://localhost:8001/sse
```

#### Ingress (Production Access)

Create `k8s/ingress.yaml`:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: market-data-hub
  namespace: market-data-hub
spec:
  rules:
  - host: market-data.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: market-data-hub
            port:
              number: 8000
```

Apply and verify:
```bash
kubectl apply -f k8s/ingress.yaml
kubectl get ingress -n market-data-hub
```

### 8. Scale Deployment

```bash
# Scale to 3 replicas
kubectl scale deployment market-data-hub --replicas=3 -n market-data-hub

# Verify replicas
kubectl get pods -n market-data-hub
kubectl get deployment market-data-hub -n market-data-hub
```

### 9. Update Deployment (Rolling Update)

```bash
# Update image
kubectl set image deployment/market-data-hub \
  app=ghcr.io/yourusername/market-data-hub:v1.0.0 \
  -n market-data-hub

# Watch rollout
kubectl rollout status deployment/market-data-hub -n market-data-hub

# Rollback if needed
kubectl rollout undo deployment/market-data-hub -n market-data-hub
```

### 10. Update Secrets/ConfigMap

```bash
# Update ConfigMap
kubectl set env configmap/market-data-hub-config \
  ibkr_host=new-host-ip \
  -n market-data-hub

# Restart pods to pick up ConfigMap changes
kubectl rollout restart deployment/market-data-hub -n market-data-hub

# Update Secret (delete and recreate)
kubectl delete secret market-data-hub-secrets -n market-data-hub
kubectl create secret generic market-data-hub-secrets \
  --from-literal=lseg_app_key=$LSEG_APP_KEY \
  --from-literal=lseg_username=$LSEG_USERNAME \
  --from-literal=lseg_password=$LSEG_PASSWORD \
  -n market-data-hub

# Restart pods for secret changes
kubectl rollout restart deployment/market-data-hub -n market-data-hub
```

---

## Health Checks

### HTTP Endpoint

```bash
# From container or local (with port-forward)
curl -v http://localhost:8000/health

# Expected response (200 OK):
# {"status": "ok"}
```

### MCP SSE Endpoint

```bash
# Test SSE connection with curl
curl -N -v http://localhost:8001/sse

# Expected: HTTP 200, continuous stream of data
# Press Ctrl+C to close
```

### Kubernetes Probe Configuration

The deployment includes three probes:

1. **Startup Probe** (30 attempts × 1s = 30s max)
   - Waits for pod to become ready
   - Checks: GET /health

2. **Readiness Probe** (every 5s, fail after 2 attempts)
   - Determines if pod can receive traffic
   - Checks: GET /health

3. **Liveness Probe** (every 10s, fail after 3 attempts)
   - Restarts pod if unhealthy
   - Checks: GET /health

View probe events:
```bash
kubectl describe pod -n market-data-hub <pod-name>
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker logs <container-id>

# Common issues:
# 1. Missing environment variables
# 2. IBKR Gateway not accessible
# 3. Dependency installation failed
```

### Pod Pending/CrashLoopBackOff

```bash
# Check pod status
kubectl describe pod -n market-data-hub <pod-name>

# Check events
kubectl get events -n market-data-hub --sort-by='.lastTimestamp'

# Check container logs
kubectl logs -n market-data-hub <pod-name> --previous
```

### Connection to IBKR Failed

```bash
# Verify IBKR_HOST and IBKR_PORT
kubectl exec -n market-data-hub <pod-name> -- env | grep IBKR

# Test connectivity from pod
kubectl exec -n market-data-hub <pod-name> -- \
  nc -zv $IBKR_HOST $IBKR_PORT

# Ensure IBKR Gateway is running and accessible
# Default ports: Gateway=4002, TWS Paper=7497, TWS Live=7496
```

### LSEG Authentication Failed

```bash
# Verify LSEG credentials
kubectl get secret -n market-data-hub market-data-hub-secrets -o yaml | grep lseg

# Test LSEG connectivity from pod
kubectl exec -n market-data-hub <pod-name> -- python -c \
  "import refinitiv.data; print('LSEG SDK installed')"

# Check credentials by examining logs
kubectl logs -n market-data-hub <pod-name> | grep -i lseg
```

### High Memory Usage

```bash
# Check current usage
kubectl top pod -n market-data-hub

# Update limits in deployment.yaml
#   limits:
#     memory: "2Gi"

# Apply updated deployment
kubectl apply -f k8s/deployment.yaml
```

### Image Pull Failed

```bash
# Check image availability
docker pull ghcr.io/yourusername/market-data-hub:latest

# Create image pull secret if using private registry
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password=<github-token> \
  -n market-data-hub

# Add to deployment.yaml:
# imagePullSecrets:
#   - name: ghcr-secret
```

### Verify All Components

```bash
# Complete status check
kubectl get all -n market-data-hub

# Detailed pod information
kubectl get pods -n market-data-hub -o wide

# Network connectivity
kubectl exec -n market-data-hub <pod-name> -- nslookup kubernetes.default

# Resource usage
kubectl top nodes
kubectl top pod -n market-data-hub
```

---

## Environment Variables Reference

### IBKR Configuration
- `IBKR_HOST`: Interactive Brokers Gateway/TWS host (default: localhost)
- `IBKR_PORT`: Gateway port 4002, TWS paper 7497, TWS live 7496
- `IBKR_CLIENT_ID`: Unique client ID for connection (default: 815)
- `IBKR_MARKET_DATA_TYPE`: 1=Live, 2=Frozen, 3=Delayed (default: 2)

### LSEG Configuration
- `LSEG_APP_KEY`: Application API key from LSEG console
- `LSEG_USERNAME`: LSEG platform username
- `LSEG_PASSWORD`: LSEG platform password

### Application Configuration
- `APP_ENV`: Environment mode - dev, test, prod (default: prod)
- `LOG_LEVEL`: Logging level - DEBUG, INFO, WARNING, ERROR (default: INFO)
- `DEFAULT_PRICE_PROVIDER`: Default provider - ibkr, lseg (default: ibkr)

---

## Cleanup

### Remove Kubernetes Resources

```bash
# Delete deployment
kubectl delete deployment market-data-hub -n market-data-hub

# Delete service
kubectl delete svc market-data-hub -n market-data-hub

# Delete ConfigMap and Secrets
kubectl delete configmap market-data-hub-config -n market-data-hub
kubectl delete secret market-data-hub-secrets -n market-data-hub

# Delete namespace
kubectl delete namespace market-data-hub
```

### Remove Docker Images

```bash
# Remove local image
docker rmi market-data-hub:latest

# Remove GHCR image (via GitHub web UI or CLI)
# https://github.com/yourusername/market-data-hub/pkgs/container/market-data-hub
```

---

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Docker Documentation](https://docs.docker.com/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [IBKR API Documentation](https://interactivebrokers.com/en/software/tws/usersguidebook.htm)
- [LSEG Refinitiv Data Documentation](https://developer.lseg.com/en/docs)
