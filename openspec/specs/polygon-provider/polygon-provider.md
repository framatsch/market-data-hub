# OpenSpec: Polygon.io Provider Integration

## Status
- **Type**: New Provider Implementation
- **Status**: Proposed
- **Author**: Gemini CLI
- **Date**: 2026-05-30

## Context & Problem
Currently, the Market Data Hub uses IBKR, LSEG, and Schwab for market data. Adding **Polygon.io** (massive.com/docs) as a provider offers a high-performance alternative for US Stocks and Options with a clean REST API and reliable OPRA/NBBO data.

## Proposed Change
Implement a new `PolygonProvider` in `app/providers/polygon.py` that implements the `BasePriceProvider` and `BaseOptionsProvider` interfaces.

### Requirements
1. **Security Types**: Support `stock` and `option`.
2. **Endpoints**:
    - `get_last_price`: Use `/v2/last/nbbo/{ticker}`.
    - `get_historical_prices`: Use `/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`.
    - `get_option_chain`: Use `/v3/snapshot/options/{underlying}`.
    - `get_option_quote`: Use `/v2/last/nbbo/{option_ticker}`.
3. **Symbology**: Automatically handle Polygon's option ticker format `O:SYMBOLYYMMDD[C/P]STRIKE`.
4. **Authentication**: Use API Key via `POLYGON_API_KEY` environment variable.

## Technical Design

### 1. Configuration (`app/config.py`)
Add Polygon-specific settings.

```python
class Settings(BaseSettings):
    # ...
    POLYGON_API_KEY: SecretStr = SecretStr("")
    POLYGON_BASE_URL: str = "https://api.polygon.io"
```

### 2. Provider Implementation (`app/providers/polygon.py`)
Create the `PolygonProvider` class.

```python
class PolygonProvider(BasePriceProvider, BaseOptionsProvider):
    def __init__(self):
        self.api_key = unwrap_secret(settings.POLYGON_API_KEY)
        self.client = httpx.AsyncClient(base_url=settings.POLYGON_BASE_URL)

    async def get_last_price(self, symbol: str, sec_type: str = "stock") -> PriceQuote:
        ticker = self._format_ticker(symbol, sec_type)
        resp = await self.client.get(f"/v2/last/nbbo/{ticker}", params={"apiKey": self.api_key})
        # Map Polygon NBBO response to PriceQuote model
        ...

    async def get_historical_prices(self, symbol: str, interval: str, start: datetime, end: datetime, sec_type: str = "stock") -> List[PriceBar]:
        ticker = self._format_ticker(symbol, sec_type)
        # Map MDH intervals (1d, 1h) to Polygon multiplier/timespan
        ...

    async def get_option_chain(self, symbol: str, expiry: date) -> OptionChain:
        # Use Polygon's Snapshot API for options
        ...

    def _format_ticker(self, symbol: str, sec_type: str) -> str:
        if sec_type == "option" and not symbol.startswith("O:"):
            return f"O:{symbol}"
        return symbol
```

### 3. Registry Integration (`app/providers/registry.py`)
Add `PolygonProvider` to the `ProviderRegistry`.

```python
from app.providers.polygon import PolygonProvider

class ProviderRegistry:
    def _initialize_providers(self):
        all_available = {
            # ...
            "polygon": PolygonProvider,
        }
        # ...
```

## Symbology Mapping
Polygon uses a very specific 8-digit padding for strikes in options.
Example strike $150.00 -> `00150000`.
The implementation must handle the conversion from standard MDH option IDs or parameters to this format.

## Verification Plan
1. **Unit Tests**: Mock Polygon API responses and verify correct mapping to MDH models.
2. **Integration Tests**: Create `tests/integration/test_polygon_prices.py` (requires valid API key).
3. **MCP Test**: Verify that `get_last_price` with `provider="polygon"` works via the MCP tool.
