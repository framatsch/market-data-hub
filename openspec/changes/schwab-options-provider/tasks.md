## 1. Backend — Provider Class Extension

- [x] 1.1 In `app/providers/schwab.py` line 67, change `class SchwabProvider(BasePriceProvider)` to `class SchwabProvider(BasePriceProvider, BaseOptionsProvider)`
- [x] 1.2 Add imports: `BaseOptionsProvider` from `app/providers/base`, `OptionChain`, `OptionQuote` from `app/models/options`, `date` from `datetime`, `Literal` from `typing` (already imported — verify)

## 2. Backend — `_parse_option_chain` Helper

- [x] 2.1 Add private method `_parse_option_chain(self, symbol: str, data: dict, expiry: date, min_strike: Optional[Decimal], max_strike: Optional[Decimal]) -> List[OptionQuote]`
- [x] 2.2 Iterate `callExpDateMap` (type `"call"`) and `putExpDateMap` (type `"put"`) — skip missing keys
- [x] 2.3 For each `exp_date_key`: split on `":"` to get ISO date string, parse with `date.fromisoformat()`, skip if not equal to `expiry` param
- [x] 2.4 For each strike key and `contracts[0]`: extract `strikePrice` as `Decimal(str(...))`, apply `min_strike`/`max_strike` filter
- [x] 2.5 Extract price: use `contract.get("last")` → fallback to `contract.get("mark")` when `last` is `0` or falsy
- [x] 2.6 Extract greeks: `delta`, `gamma`, `theta`, `vega` directly from contract dict (may be `None`)
- [x] 2.7 Extract IV from `contract.get("volatility")` — **not** `"impliedVolatility"` — add inline comment explaining the field name
- [x] 2.8 Wrap `bid`, `ask`, `price`, `strike` with `Decimal(str(...))` — leave greeks as `float | None`
- [x] 2.9 Return `List[OptionQuote]` sorted by `(type, strike)`

## 3. Backend — `get_option_chain`

- [x] 3.1 Implement `async def get_option_chain(self, symbol, expiry, min_strike=None, max_strike=None, right=None, market_data_type=None) -> OptionChain` matching the abstract signature in `base.py`
- [x] 3.2 Map `right` to `Client.Options.ContractType`: `"call"→CALL`, `"put"→PUT`, `None→ALL`
- [x] 3.3 Call `await asyncio.to_thread(client.get_option_chain, symbol, contract_type=..., from_date=expiry, to_date=expiry)` (schwab-py client is sync — wrap with `asyncio.to_thread` consistent with the rest of `schwab.py`)
- [x] 3.4 Check `resp.status_code` — map 401→AppError(401), 403→AppError(403), 429→AppError(429), other non-200→AppError(502)
- [x] 3.5 Call `self._parse_option_chain(symbol, resp.json(), expiry, min_strike, max_strike)` → get `options: List[OptionQuote]`
- [x] 3.6 Return `OptionChain(underlying_symbol=symbol, expiry=expiry, options=options, provider="schwab")`

## 4. Backend — `get_option_quote`

- [x] 4.1 Implement `async def get_option_quote(self, symbol, option_id, market_data_type=None) -> OptionQuote`
- [x] 4.2 Call `await asyncio.to_thread(client.get_quotes, [option_id])` — same HTTP error handling as 3.4
- [x] 4.3 Extract the contract entry from the response dict (keyed by `option_id`)
- [x] 4.4 If greeks (`delta`, `gamma`, etc.) are absent or all `None` in the quote response: parse the OCC symbol `option_id` to extract underlying, expiry, right, strike (regex: `^([A-Z]+)\s+(\d{6})([CP])(\d{8})$`); call `get_option_chain()` narrowed to that expiry + strike range ±0; return the single matching `OptionQuote`
- [x] 4.5 If OCC symbol parse fails: raise `AppError(400, f"Invalid option symbol: {option_id}")`
- [x] 4.6 Construct and return `OptionQuote` with all available fields; `provider="schwab"`

## 5. Tests

- [x] 5.1 In `tests/unit/test_schwab_provider.py`, add fixture `option_chain_response()` — inline dict with `callExpDateMap` + `putExpDateMap`, 2 strikes (185.0, 190.0), both call and put sides, all greek fields populated
- [x] 5.2 Test `get_option_chain` normal case: mock `client.get_option_chain` returning the fixture → assert `OptionChain.provider == "schwab"`, correct number of `OptionQuote` objects, `strike == Decimal("185.0")`
- [x] 5.3 Test `get_option_chain` with `min_strike=187.0` → only strike 190.0 contracts returned
- [x] 5.4 Test `get_option_chain` with `right="call"` → only call-side contracts returned
- [x] 5.5 Test IV field mapping: `contract["volatility"] = 22.345` → `OptionQuote.implied_volatility == 22.345`
- [x] 5.6 Test `last=0` fallback: `contract["last"] = 0`, `contract["mark"] = 4.45` → `OptionQuote.price == Decimal("4.45")`
- [x] 5.7 Test HTTP 429 from `get_option_chain` → `AppError` with status 429
- [x] 5.8 Test `get_option_quote` normal case: mock `client.get_quotes` returning single contract with greeks → correct `OptionQuote`
- [x] 5.9 Test `get_option_quote` invalid OCC symbol → `AppError(400)`
- [x] 5.10 Verify `SchwabProvider` is instance of `BaseOptionsProvider` in a unit test (registry isinstance check)

## 6. Verification

- [x] 6.1 Run `uv run ruff check app/` — no lint errors
- [x] 6.2 Run `uv run pytest tests/unit/test_schwab_provider.py --maxfail=1 --disable-warnings` — all tests pass
- [ ] 6.3 Run full test suite `uv run pytest --maxfail=1 --disable-warnings` — no regressions
