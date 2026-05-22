## 1. Dependency & Config Setup

- [ ] 1.1 Add `schwab-py` to `pyproject.toml` under `[project.dependencies]` and run `uv sync --frozen` to update `uv.lock`
- [ ] 1.2 Add `SCHWAB_API_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_CALLBACK_URL`, `SCHWAB_TOKEN_PATH`, `SCHWAB_TIMEOUT_SECONDS`, `SCHWAB_RATE_LIMIT_PER_SEC`, and `SCHWAB_ASYNCIO` to `app/config.py` Settings class with safe defaults
- [ ] 1.3 Document all `SCHWAB_*` keys in `.env.example` with inline comments explaining each value

## 2. Provider Implementation

- [ ] 2.1 Create `app/providers/schwab.py` with `SchwabProvider` class skeleton inheriting `BasePriceProvider`
- [ ] 2.2 Implement `_get_client()` — lazy async init using `easy_client()` wrapped in `asyncio.to_thread`; raise `ProviderConnectionError` on missing token file or auth failure
- [ ] 2.3 Implement `_check_rate_limit()` — sliding-window deque, raises `ProviderTimeoutError` on 429 or limit exceeded
- [ ] 2.4 Implement `_INTERVAL_METHODS` dispatch dict mapping interval strings (`1m`, `5m`, `10m`, `15m`, `30m`, `1d`, `1w`) to `schwab-py` convenience method names
- [ ] 2.5 Implement `_period_to_start(period: str) -> datetime` — converts period strings (`1d`, `5d`, `1m`, `3m`, `6m`, `1y`, `2y`, `5y`, `10y`) to UTC `datetime` start values; raises `DataValidationError` for unknown periods
- [ ] 2.6 Implement `_parse_ohlcv(data: dict, symbol: str) -> list[PriceBar]` — defensively parse `data["candles"]`; convert `datetime` field (ms epoch) to UTC `datetime`; all prices to `Decimal(str(...))`
- [ ] 2.7 Implement `get_historical_prices(symbol, interval, period, ...)` — look up method from `_INTERVAL_METHODS`, compute `start_datetime` via `_period_to_start`, call method, assert 200, parse via `_parse_ohlcv`; raise `DataNotFoundError` on empty candles
- [ ] 2.8 Implement `_parse_quote(symbol: str, data: dict) -> PriceQuote` — safely extract `lastPrice`, `bidPrice`, `askPrice`, `totalVolume` from `data[symbol]["quote"]`; all prices to `Decimal`
- [ ] 2.9 Implement `get_last_price(symbol, ...)` — call `client.get_quotes([symbol])`, assert 200, parse via `_parse_quote`; raise `DataNotFoundError` if symbol absent in response
- [ ] 2.10 Implement `close()` coroutine — clean shutdown hook (no-op if client not created)

## 3. Provider Registration

- [ ] 3.1 Import `SchwabProvider` in `app/providers/registry.py` and instantiate it as `self.schwab = SchwabProvider()`
- [ ] 3.2 Add `"schwab"` as a selectable option in the `get_price_provider()` factory function in `registry.py`
- [ ] 3.3 Add `"schwab"` to the comment/enum of valid provider names in `app/config.py` `DEFAULT_PRICE_PROVIDER`

## 4. Unit Tests

- [ ] 4.1 Create `tests/unit/test_schwab_provider.py` with pytest fixtures that mock `schwab-py` client using `unittest.mock.AsyncMock`
- [ ] 4.2 Write test: `test_get_historical_prices_daily_success` — mock client returns a valid candles JSON; assert `PriceBar` list length, types, and `Decimal` values
- [ ] 4.3 Write test: `test_get_historical_prices_intraday_success` — use `interval="1m"` and verify correct method (`get_price_history_every_minute`) is called
- [ ] 4.4 Write test: `test_get_historical_prices_unsupported_interval` — assert `DataValidationError` raised for `interval="2h"`
- [ ] 4.5 Write test: `test_get_last_price_success` — mock `get_quotes` response; assert `PriceQuote.last_price` is `Decimal`
- [ ] 4.6 Write test: `test_get_last_price_unknown_symbol` — mock empty/missing symbol in response; assert `DataNotFoundError`
- [ ] 4.7 Write test: `test_provider_disabled_when_no_api_key` — set `SCHWAB_API_KEY=""` and assert `ProviderConnectionError` on any public method call
- [ ] 4.8 Write test: `test_missing_token_file_raises_connection_error` — mock `easy_client` raising `FileNotFoundError`; assert `ProviderConnectionError` with `token_path` in details
- [ ] 4.9 Write test: `test_decimal_conversion_from_float` — verify `Decimal(str(182.63))` round-trip in `_parse_ohlcv`

## 5. Diagnostic Script

- [ ] 5.1 Create `scripts/diagnostics/test_schwab_connection.py` — imports `SchwabProvider`, calls `get_last_price("AAPL")`, prints result; requires live token in `SCHWAB_TOKEN_PATH`

## 6. Verification & Cleanup

- [ ] 6.1 Run `uv run ruff check app/providers/schwab.py` and fix any lint errors
- [ ] 6.2 Run `uv run pytest tests/unit/test_schwab_provider.py -v --disable-warnings` — all tests pass
- [ ] 6.3 Run `uv run pytest --maxfail=1 --disable-warnings` — full suite still green (no regressions)
- [ ] 6.4 Verify `curl http://localhost:8000/providers | python -m json.tool` shows `"schwab"` in the provider list (requires running server with `SCHWAB_API_KEY` set)
