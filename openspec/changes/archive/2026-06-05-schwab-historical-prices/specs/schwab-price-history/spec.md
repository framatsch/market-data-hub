## ADDED Requirements

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
The system SHALL catch all `schwab-py` authentication and token-related errors and re-raise them as `ProviderConnectionError` with a human-readable hint.

#### Scenario: Expired token triggers actionable error
- **WHEN** the Schwab token is older than 7 days and an API call is attempted
- **THEN** `ProviderConnectionError` is raised with a message instructing the user to run `schwab-generate-token.py`

#### Scenario: Missing token file triggers actionable error
- **WHEN** `SCHWAB_TOKEN_PATH` points to a nonexistent file
- **THEN** `ProviderConnectionError` is raised with `token_path` included in the error details
