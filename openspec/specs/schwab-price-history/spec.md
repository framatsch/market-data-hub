## Purpose
Define expected Schwab provider behavior for historical price bars, latest quotes, provider selection, data type safety, and auth/token error handling.
## Requirements
### Requirement: Fetch historical OHLCV bars for a US equity symbol via Schwab
The system SHALL retrieve OHLCV price bars for a given US equity or ETF ticker symbol using the Schwab Individual Trader API via the `schwab-py` library. The response SHALL be a list of `PriceBar` objects with open, high, low, close (as `Decimal`), volume (as `int`), and UTC timestamp.

#### Scenario: Successful daily history fetch
- **WHEN** `get_historical_prices(symbol="AAPL", interval="1d", period="1y")` is called with valid Schwab credentials
- **THEN** the provider returns a non-empty list of `PriceBar` objects covering approximately one year of daily OHLCV data

#### Scenario: Successful intraday history fetch (1-minute)
- **WHEN** `get_historical_prices(symbol="AAPL", interval="1m", period="5d")` is called
- **THEN** the provider returns per-minute bars covering up to 5 trading days (subject to Schwab's ~48-day 1m lookback limit)

#### Scenario: Unsupported interval raises DataValidationError
- **WHEN** `get_historical_prices(symbol="AAPL", interval="2h", period="1m")` is called with an interval not in the supported set
- **THEN** the provider raises `DataValidationError` with a message listing valid intervals

#### Scenario: Futures symbol raises DataNotFoundError
- **WHEN** `get_historical_prices(symbol="/ES", interval="1d", period="1m")` is called
- **THEN** the provider raises `DataNotFoundError` because Schwab does not provide futures price history

#### Scenario: Provider disabled when SCHWAB_API_KEY is empty
- **WHEN** `SCHWAB_API_KEY` is not configured and `get_historical_prices` is called
- **THEN** the provider raises `ProviderConnectionError` with a message indicating the provider is not configured

### Requirement: Fetch current quote for a US equity symbol via Schwab
The system SHALL retrieve the latest price quote for a given US equity or ETF ticker symbol. The response SHALL be a `PriceQuote` object including last price, bid, ask, and volume (all as `Decimal` where applicable).

#### Scenario: Successful quote fetch
- **WHEN** `get_last_price(symbol="AAPL")` is called with valid credentials during market hours
- **THEN** the provider returns a `PriceQuote` with a non-null `last_price` and UTC timestamp

#### Scenario: Unknown symbol raises DataNotFoundError
- **WHEN** `get_last_price(symbol="XXXXXXX")` is called for a symbol that does not exist
- **THEN** the provider raises `DataNotFoundError("Symbol", "XXXXXXX")`

### Requirement: Schwab provider is registered and selectable
The system SHALL make the Schwab provider available under the key `"schwab"` via the provider registry, selectable via the `provider` query parameter on existing price endpoints.

#### Scenario: Provider selected via query parameter
- **WHEN** `GET /prices/history/AAPL?interval=1d&period=1y&provider=schwab` is requested
- **THEN** the API delegates to `SchwabProvider.get_historical_prices` and returns a valid response

#### Scenario: Provider absent when not configured
- **WHEN** `SCHWAB_API_KEY` is empty and `GET /prices/history/AAPL?provider=schwab` is requested
- **THEN** the API returns HTTP 503 with a provider-not-configured error message

### Requirement: Historical interval mapping covers all supported granularities
The system SHALL support the following interval strings mapped to the corresponding Schwab API calls:

| Interval | Schwab method | Lookback |
|----------|--------------|---------|
| `1m` | `get_price_history_every_minute` | ~48 days |
| `5m` | `get_price_history_every_five_minutes` | ~9 months |
| `10m` | `get_price_history_every_ten_minutes` | ~9 months |
| `15m` | `get_price_history_every_fifteen_minutes` | ~9 months |
| `30m` | `get_price_history_every_thirty_minutes` | ~9 months |
| `1d` | `get_price_history_every_day` | back to 1985 |
| `1w` | `get_price_history_every_week` | back to 1985 |

#### Scenario: Each supported interval returns data
- **WHEN** `get_historical_prices` is called with any interval from the table above and a compatible period
- **THEN** the provider returns a non-empty list of `PriceBar` objects without raising an error

#### Scenario: Period string converts to start_datetime correctly
- **WHEN** period `"1y"` is passed
- **THEN** `start_datetime` is computed as `now(UTC) - 365 days` before calling the Schwab API

### Requirement: All financial values stored as Decimal, never float
The system SHALL convert all price and volume values from the raw Schwab JSON response (which uses JSON number / float) to `Decimal` via `Decimal(str(value))` before constructing `PriceBar` or `PriceQuote` objects.

#### Scenario: Float-to-Decimal conversion on bar parse
- **WHEN** Schwab returns `{"close": 182.63}` in a candle
- **THEN** the resulting `PriceBar.close` is `Decimal("182.63")`, not the float `182.63`

### Requirement: Token management errors surface as ProviderConnectionError
The system SHALL catch all `schwab-py` authentication and token-related errors and re-raise them as `ProviderConnectionError` with a human-readable hint. When a 401 or 403 response is received AND the client was previously initialized (indicating a refresh token expiry rather than initial misconfiguration), the provider SHALL additionally set `_paused = True` and fire an async webhook notification before raising. When `_paused` is `True`, the provider SHALL raise `ProviderConnectionError` immediately on any subsequent call without attempting any network request.

#### Scenario: Initial auth failure (client was None)
- **WHEN** `SCHWAB_API_KEY` is set but credentials are invalid and client has never been initialized
- **THEN** `ProviderConnectionError` is raised with message indicating auth failure; `_paused` remains `False`

#### Scenario: Refresh token expiry (client was not None) — pauses provider
- **WHEN** a live request returns 401 after the provider was previously working (client was not None)
- **THEN** `_paused = True`, `_client = None`, `ProviderConnectionError` is raised, and webhook is fired if `SCHWAB_ALERT_WEBHOOK_URL` is set

#### Scenario: Paused provider rejects calls immediately
- **WHEN** `SchwabProvider._paused = True` and any price method is called
- **THEN** `ProviderConnectionError` is raised immediately without any HTTP call to Schwab

#### Scenario: Provider unpaused after re-auth
- **WHEN** `POST /api/admin/schwab/auth/callback` successfully completes
- **THEN** `_paused = False`, `_client = None`, and the next call to any price method proceeds normally via `_get_client()`

#### Scenario: Rate limit error surfaces as ProviderTimeoutError
- **WHEN** Schwab returns HTTP 429
- **THEN** `ProviderTimeoutError` is raised (unchanged from existing behavior)

