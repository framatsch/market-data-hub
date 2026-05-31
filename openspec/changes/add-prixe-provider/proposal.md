## Why

The system needs to integrate with the Prixe Stock API (https://prixe.io) to expand market data coverage and add a cost-effective, developer-friendly source for current stock prices, historical data, and real-time news.

## What Changes

- Add a new financial data provider implementation for Prixe.
- Integrate the Prixe API endpoints (`/api/last_sold`, historical prices, news, SEC filings) into the internal hub models.
- Update configuration to toggle Prixe via environment variables (e.g., `PRIXE_API_KEY`).

## Capabilities

### New Capabilities
- `prixe-provider`: Full integration with the Prixe API for fetching real-time quotes, historical stock prices, real-time news, and SEC forms data.

### Modified Capabilities

## Impact

- **Code**: Addition of `app/providers/prixe.py` and potentially updates to `app/config.py` and `app/providers/registry.py`.
- **Environment**: Addition of new environment variable `PRIXE_API_KEY`.
- **Dependencies**: Uses the existing pinned `httpx` dependency for async API requests.
