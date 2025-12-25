You are an expert Python backend engineer and cloud architect.  
Your task is to design and implement a **FastAPI-based data service** that exposes market- and company-data from multiple external providers (e.g. IBKR and LSEG) in a clean, provider-agnostic REST/WebSocket API.

The service will later be deployed as a Docker container into a Kubernetes cluster and should be suitable to be wrapped as an MCP tool (Model Context Protocol) for AI agents.  
Focus on clean architecture, strong typing, and a well-documented Swagger/OpenAPI spec.

---

## High-level architecture

Implement **Pattern 1 (single service with pluggable backends)**:

- One FastAPI service acting as an **aggregator**:
  - It exposes a stable, provider-agnostic API to clients.
  - Internally it uses a set of **pluggable “provider” classes** to talk to external backends like IBKR and LSEG.
- Providers implement a common interface so that the service can:
  - Fetch prices from provider A and company data from provider B.
  - Optionally combine data from multiple providers in one response (aggregator pattern).
- Dynamic provider selection:
  - Global default mapping via configuration (e.g. IBKR for prices, LSEG for fundamentals).
  - Per-request override via query parameter (e.g. `?provider=ibkr` or `?price_provider=ibkr&company_provider=lseg`).

Do **not** implement real IBKR/LSEG API calls – instead:
- Provide clear abstraction layers and stub/mock implementations (e.g. in-memory or dummy data),
- But design the code so that real implementations can be dropped in later with minimal changes.

---

## Requirements

### 1. Technology stack

- Python 3.11+
- FastAPI
- Pydantic v2
- HTTPX or aiohttp (for async HTTP calls to providers)
- Uvicorn (ASGI server)
- Optional: `tenacity` or a simple retry mechanism for robust provider calls

### 2. Project structure

Propose and implement a clear, production-like project layout, for example:

- `app/`
  - `main.py`                – FastAPI app creation and routing
  - `config.py`              – settings (env vars, provider defaults)
  - `dependencies.py`        – common dependency injection for FastAPI
  - `api/`
    - `routes_prices.py`     – REST endpoints for price data
    - `routes_companies.py`  – REST endpoints for company data
    - `routes_options.py`    – REST endpoints for options / derivatives
    - `routes_meta.py`       – health checks, provider listing, etc.
    - `routes_ws.py`         – WebSocket endpoints for streaming
  - `models/`
    - `price.py`             – Pydantic models for price data
    - `company.py`           – Pydantic models for company data
    - `options.py`           – Pydantic models for options data
    - `common.py`            – common response envelopes, error models
  - `providers/`
    - `base.py`              – abstract base interfaces for providers
    - `ibkr.py`              – stub IBKR provider implementation
    - `lseg.py`              – stub LSEG provider implementation
    - `registry.py`          – provider registry and selection logic
  - `services/`
    - `price_service.py`     – business logic for price queries (uses providers)
    - `company_service.py`   – business logic for company data
    - `options_service.py`   – business logic for options data
  - `utils/`
    - `logging.py`           – logging setup
    - `errors.py`            – shared exception classes, error handling helpers

Also create:
- `Dockerfile`
- `pyproject.toml` or `requirements.txt`
- A minimal `k8s/` directory with manifests:
  - `deployment.yaml`
  - `service.yaml`
  - optional `configmap.yaml` and `secret.yaml` for provider configuration

### 3. Configuration

Implement a typed configuration layer using Pydantic settings:

- General:
  - `APP_NAME`
  - `APP_ENV` (dev/test/prod)
  - `LOG_LEVEL`
- Provider defaults:
  - `DEFAULT_PRICE_PROVIDER`       (e.g. `"ibkr"` or `"lseg"`)
  - `DEFAULT_COMPANY_PROVIDER`
  - `DEFAULT_OPTIONS_PROVIDER`
- IBKR provider config:
  - `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID`, `IBKR_ACCOUNT_ID`, `IBKR_ENV`
- LSEG provider config:
  - `LSEG_BASE_URL`, `LSEG_API_KEY` (or token)
- Timeouts and retries:
  - `PROVIDER_REQUEST_TIMEOUT`
  - `PROVIDER_MAX_RETRIES`

Use environment variables with reasonable defaults.  
Expose an endpoint `/config/providers` that returns **only** non-sensitive configuration info (e.g. which provider is default for which data type), NOT secrets.

### 4. Provider abstraction (Strategy pattern)

In `providers/base.py` define abstract base classes:

- `BasePriceProvider`
  - `async def get_historical_prices(symbol: str, interval: str, start: datetime, end: datetime) -> list[PriceBar]`
  - `async def get_last_price(symbol: str) -> PriceQuote`
- `BaseCompanyProvider`
  - `async def get_company_profile(symbol: str) -> CompanyProfile`
  - `async def search_companies(query: str) -> list[CompanySummary]`
- `BaseOptionsProvider`
  - `async def get_option_chain(symbol: str, expiry: date) -> OptionChain`
  - `async def get_option_quote(symbol: str, option_id: str) -> OptionQuote`

These type names (`PriceBar`, `PriceQuote`, etc.) should refer to Pydantic models in `app/models`.

In `providers/ibkr.py` and `providers/lseg.py`:

- Implement those base classes with **fake/stubbed data** for now, but:
  - simulate realistic response shapes,
  - include TODOs/docstrings where real IBKR/LSEG API calls would go,
  - keep all external API URLs and credentials in `config.py`.

Add a `providers/registry.py` that:

- Maintains a mapping `{provider_name: ProviderInstances}`
- Provides functions like:
  - `get_price_provider(name: str | None) -> BasePriceProvider`
  - `get_company_provider(name: str | None) -> BaseCompanyProvider`
  - `get_options_provider(name: str | None) -> BaseOptionsProvider`
- Implements the logic:
  - If `name` is `None`, use the corresponding default from config.
  - If `name` is unknown, raise a clean, typed error that the API maps to a 400.

### 5. API design (REST + WebSocket)

Design the REST API endpoints with clear, provider-agnostic contracts and good OpenAPI docs:

**Meta / health:**
- `GET /health`
  - Returns service status, uptime, and a simple “OK” flag.
- `GET /providers`
  - Returns list of available providers by role: price, company, options.

**Prices:**
- `GET /prices/{symbol}/last`
  - Query params: `provider` (optional)
  - Returns last price quote for the symbol.
- `GET /prices/{symbol}/history`
  - Query params: `interval`, `start`, `end`, `provider` (optional)
  - Returns list of `PriceBar` items.

**Company data:**
- `GET /companies/{symbol}`
  - Query params: `provider` (optional)
  - Returns `CompanyProfile`.
- `GET /companies/search`
  - Query: `q` (search string), `provider` (optional)
  - Returns list of `CompanySummary`.

**Options:**
- `GET /options/{symbol}/chain`
  - Query params: `expiry`, `provider` (optional)
  - Returns `OptionChain`.
- `GET /options/{symbol}/quote/{option_id}`
  - Query params: `provider` (optional)
  - Returns `OptionQuote`.

**WebSocket for streaming prices:**
- `GET /ws/prices`
  - WebSocket that accepts a subscription message such as:
    - `{"type": "subscribe", "symbols": ["QCOM", "ORCL"], "provider": "ibkr"}`
  - Echoes back simulated streaming updates using the selected provider.
  - Implement a simple subscription manager and heartbeat/ping mechanism.

For each endpoint, provide:
- Pydantic request/response models,
- Descriptive docstrings and FastAPI doc params so the **Swagger UI** is self-explanatory.

### 6. Error handling & resilience

Implement a consistent error model:

- Define custom exceptions in `utils/errors.py`:
  - `ProviderNotAvailableError`
  - `ProviderTimeoutError`
  - `InvalidProviderError`
  - `DataNotFoundError`
- Add FastAPI exception handlers to:
  - map these to HTTP statuses (400, 404, 503),
  - return a typed error response model: `{ "error": { "code": "...", "message": "...", "details": {...} } }`.

Where provider calls happen (even if currently stubbed), implement:
- timeouts,
- simple retry logic (e.g. 2–3 retries with exponential backoff),
- logging of failures.

### 7. Logging & observability

Implement structured logging:

- Initialize logging in `utils/logging.py`.
- Log important events:
  - incoming requests (method, path, provider used),
  - provider calls (duration, success/failure),
  - WebSocket subscriptions and disconnects.
- Add basic metrics hooks or at least place TODOs where a metrics system (Prometheus, etc.) could be integrated later.

### 8. Dockerfile

Create a production-ready `Dockerfile`:

- Multi-stage build (optional but preferred).
- Use a current Python base image.
- Install dependencies using `uv` or pip.
- Run the app with Uvicorn, e.g.:
  - `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Use a non-root user where possible.

### 9. Kubernetes manifests (basic)

Under a `k8s/` directory, create YAML manifests:

- `deployment.yaml`:
  - Container image (placeholder).
  - Environment variables for configuration (esp. provider defaults, timeouts).
  - Resource requests/limits.
  - Readiness/liveness probes on `/health`.
- `service.yaml`:
  - Expose the app internally on port 8000.
- Optional:
  - `configmap.yaml` for non-secret config.
  - `secret.yaml` for tokens/API keys (stub values).

Make sure the manifests are generic enough to be adapted in a real cluster.

### 10. Documentation

Add:
- A `README.md` that explains:
  - the architecture (aggregator + pluggable providers),
  - how to run locally, build Docker image, and run in Kubernetes,
  - how provider selection works (defaults + `?provider=` overrides),
  - examples of API calls (curl) and WebSocket usage.
- Keep explanations concise but clear and developer-friendly.

---

## Output expectations

Please generate:

1. All Python source files with full code, using the proposed structure.
2. A `requirements.txt` or `pyproject.toml` with all needed dependencies.
3. The `Dockerfile`.
4. The Kubernetes manifests in a `k8s/` directory.
5. A `README.md` that documents:
   - architecture,
   - configuration,
   - endpoints,
   - examples.
6. Ensure the FastAPI app starts and the OpenAPI/Swagger UI is usable out of the box (with stubbed providers).

Focus on clean, idiomatic, production-grade Python and FastAPI code.
