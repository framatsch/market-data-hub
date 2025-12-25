# Market Data Hub

A FastAPI-based data service that aggregates market and company data from multiple external providers (IBKR, LSEG) in a clean, provider-agnostic REST/WebSocket API.

## Architecture

This service implements the **Aggregator Pattern**:
- **API Layer**: Exposes unified REST and WebSocket endpoints.
- **Service Layer**: Orchestrates data fetching and business logic.
- **Provider Layer**: Abstracts external APIs (IBKR, LSEG) via strict interfaces.

## Usage

### Local Development

1.  **Install dependencies**:
    ```bash
    pip install .
    ```
2.  **Run the service**:
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```
3.  **Access Documentation**:
    Open [http://localhost:8000/docs](http://localhost:8000/docs) for the Swagger UI.

### Docker

Build the image:
```bash
docker build -t market-data-hub:latest .
```

Run container:
```bash
docker run -p 8000:8000 market-data-hub:latest
```

### Kubernetes

Apply manifests:
```bash
kubectl apply -f k8s/
```

## Configuration

Configuration is handled via environment variables (see `app/config.py`).

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `dev` | Environment (dev/test/prod) |
| `DEFAULT_PRICE_PROVIDER` | `ibkr` | Default provider for price data |
| `DEFAULT_COMPANY_PROVIDER` | `lseg` | Default provider for company data |

### Refinitiv (LSEG) Entitlements

To access Refinitiv/LSEG data, you need valid credentials from the LSEG Workspace platform:

- **`LSEG_APP_KEY`**: Your application API key obtained from the LSEG Developer Portal
- **`LSEG_USERNAME`**: Your LSEG Workspace username (typically an email address)
- **`LSEG_PASSWORD`**: Your LSEG Workspace password

These credentials must be set as environment variables before starting the service. Without valid credentials, any requests to LSEG-backed endpoints will fail with authentication errors.

**Note**: LSEG data access requires an active subscription with appropriate entitlements for the data types you wish to retrieve (equity quotes, fundamentals, historical data, etc.).


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
