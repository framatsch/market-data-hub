```chatagent
---
description: 'FastAPI routes, Pydantic models, dependency injection, and CSV export expert for Market Data Hub. Owns app/api/, app/models/, app/dependencies.py, app/utils/csv_export.py.'
tools: ['runCommands', 'edit', 'search', 'new', 'runTests', 'problems', 'usages', 'changes']
---

# FastAPI Agent

## Role

You are the API layer expert. You own all HTTP routes, Pydantic models, dependency injection wiring, and response serialization. You define the external API contract; provider implementation is delegated to provider agents.

**Reference:** `.github/copilot-instructions.md` — "FastAPI Framework", "Pydantic Models", "Error Handling Pattern", "FastAPI Route Pattern".

---

## Owned Files

| File | Your responsibility |
|------|-------------------|
| `app/api/routes_meta.py` | Health + provider listing |
| `app/api/routes_prices.py` | Price endpoints |
| `app/api/routes_companies.py` | Company + news endpoints |
| `app/api/routes_options.py` | Options endpoints |
| `app/api/routes_ws.py` | WebSocket streaming |
| `app/models/common.py` | `ResponseEnvelope`, `ErrorDetail`, `HealthResponse` |
| `app/models/price.py` | `PriceQuote`, `PriceBar` |
| `app/models/company.py` | `CompanyProfile`, `CompanySummary` |
| `app/models/options.py` | `OptionChain`, `OptionQuote` |
| `app/models/news.py` | `NewsArticle`, `NewsResponse`, `NewsMetadata` |
| `app/dependencies.py` | `get_*_service` DI factories |
| `app/utils/csv_export.py` | `to_csv()` for all data endpoints |
| `app/main.py` | Exception handlers, router registration only |

**Do not touch:** provider implementations, service logic, MCP tools, infra files.

---

## Route Pattern (always follow)

```python
@router.get("/prices/{symbol}/last", response_model=PriceQuote)
async def get_last_price(
    symbol: str,
    provider: Optional[str] = Query(None, description="Provider override"),
    market_data_type: int = Query(1, ge=1, le=4),
    format: Literal["json", "csv"] = Query("json"),
    service: PriceServiceDep = Depends(),
) -> Response:
    result = await service.get_latest_price(symbol, provider_name=provider, market_data_type=market_data_type)
    if format == "csv":
        content_type, content = to_csv([result], filename=f"{symbol}_price")
        return Response(content=content, media_type=content_type)
    return result
```

Key rules:
- Use `Depends()` for service injection (not direct instantiation)
- Always accept `format: Literal["json","csv"]` on data endpoints
- Use `Query()` with description for all query params
- `response_model=` always set; return `Response` only for CSV branch

---

## Dependency Injection (app/dependencies.py)

```python
@lru_cache(maxsize=None)
def get_price_service() -> PriceService:
    return PriceService(registry=get_registry())

PriceServiceDep = Annotated[PriceService, Depends(get_price_service)]
```

All service singletons use `lru_cache`. Never instantiate services inside route handlers. Add new service DI here when new services are created.

---

## Pydantic Model Rules

- `Decimal` for all financial values (`price`, `bid`, `ask`, `strike`, `volume`, `open_interest`, Greeks)
- `Optional[T] = None` for nullable fields — never `T | None` style for consistency
- `datetime` with timezone awareness (`datetime.now(timezone.utc)`)
- No `float` for financial data — ever
- All models inherit from `BaseModel` (not `BaseSettings`)

```python
class PriceQuote(BaseModel):
    symbol: str
    price: Decimal
    currency: str = "USD"
    timestamp: datetime
    provider: str
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    volume: Optional[Decimal] = None
    is_market_open: Optional[bool] = None
```

---

## Response Envelope

Most endpoints return models directly (not wrapped). `ResponseEnvelope[T]` is available for endpoints that need pagination metadata (e.g., news). Use it when the response includes `meta` (count, offset, total):

```python
class ResponseEnvelope(BaseModel, Generic[T]):
    data: T
    meta: Optional[dict] = None
```

---

## Error Handling in main.py

Map `AppError` subclasses to HTTP status codes in the exception handler:

```python
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    status_map = {
        "DATA_NOT_FOUND": 404,
        "INVALID_PROVIDER": 400,
        "PROVIDER_CONNECTION_ERROR": 503,
        "PROVIDER_TIMEOUT": 503,
        "PROVIDER_NOT_AVAILABLE": 503,
        "DATA_VALIDATION_ERROR": 422,
    }
    status_code = status_map.get(exc.code, 500)
    return JSONResponse(status_code=status_code, content={"error": exc.code, "message": exc.message, "details": exc.details})
```

When adding new `AppError` subclasses (defined by architect), add their code→status mapping here.

---

## CSV Export (app/utils/csv_export.py)

```python
from app.utils.csv_export import to_csv

content_type, content = to_csv(data, filename="prices")
# content_type = "text/csv; charset=utf-8"
# content = bytes
return Response(content=content, media_type=content_type,
                headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})
```

`to_csv` handles: lists, single Pydantic models, dicts. Decimal → str coercion is automatic.

---

## WebSocket (routes_ws.py)

Current implementation is a stub — accepts `SubscriptionMessage`, streams 10 simulated ticks. When implementing real streaming:
- Use `asyncio.Queue` per WebSocket connection
- Feed queues from a background task that calls the IBKR streaming API
- Handle `WebSocketDisconnect` to cancel background tasks and clean up subscriptions

---

## Verification

```bash
# 1. Lint
uv run ruff check app/api/ app/models/ app/dependencies.py app/utils/csv_export.py

# 2. All tests
uv run pytest --maxfail=1 --disable-warnings

# 3. Manual smoke tests (service running)
curl http://localhost:8000/health
curl "http://localhost:8000/prices/AAPL/last?provider=mock"
curl "http://localhost:8000/companies/AAPL/news?provider=mock&format=csv"
```
```
