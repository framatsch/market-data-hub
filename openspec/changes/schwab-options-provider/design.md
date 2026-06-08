## Context

`SchwabProvider` (`app/providers/schwab.py`) implements `BasePriceProvider` only. The `BaseOptionsProvider` interface defines two abstract methods: `get_option_chain` and `get_option_quote`. The schwab-py library exposes `client.get_option_chain()` returning a nested JSON structure (`callExpDateMap`/`putExpDateMap`) and `client.get_quotes()` which accepts OCC option symbols for single-contract lookups.

Key response structure gotchas:
- Map keys: `"2024-04-05:7"` (ISO date + colon + DTE) → strip DTE with `split(":")[0]`
- IV field: `"volatility"` (NOT `"impliedVolatility"`) — a float like `22.3` meaning ~22.3% annualised IV
- Price: `"last"` field — fallback to `"mark"` when `last == 0` or absent
- Strike: `contract["strikePrice"]` (float inside object) — wrap with `Decimal(str(...))`
- List per strike: always a single-element list for `SINGLE` strategy — access `contracts[0]`

## Goals / Non-Goals

**Goals:**
- `SchwabProvider` satisfies `isinstance(provider, BaseOptionsProvider)` check in the registry
- `get_option_chain()` returns a correctly populated `OptionChain` with full greeks for all contracts in the requested expiry
- `get_option_quote()` returns a single `OptionQuote` for an OCC symbol
- Strike range filtering (`min_strike`/`max_strike`) applied client-side after parsing
- `right` parameter maps to `Client.Options.ContractType.{ALL,CALL,PUT}`
- Unit tests cover: normal flow, strike filter, right filter, IV field mapping, `last=0→mark` fallback, HTTP error → `AppError`

**Non-Goals:**
- Multi-expiry chain (only the single requested expiry is returned — Schwab returns all expirations in one call, we filter to `expiry`)
- Underlying quote data from the chain response (not part of `OptionChain` model)
- `get_market_status` for Schwab (separate concern)

## Decisions

### D1: `get_option_quote` via `get_quotes()`, not narrowed chain

`client.get_quotes([option_id])` accepts OCC symbols directly (e.g. `"AAPL  231215C00190000"`). This is a single lightweight request. The chain call would return far more data than needed for one contract. Use `get_quotes` as primary path; if greeks are absent in the quote response (Schwab does not guarantee greeks in quote-only calls), fall back to a narrowed chain call with the strike and expiry parsed from the OCC symbol.

### D2: `_parse_option_chain` as a private instance method

The parser needs no external state but receives `self` to access `provider="schwab"` consistently. It takes `(symbol, data, expiry, min_strike, max_strike)` and returns `List[OptionQuote]`. The `expiry` parameter is used to filter the map keys — even though `from_date==to_date` in the chain call, Schwab may still return adjacent expirations.

### D3: Decimal wrapping for all financial values

Consistent with the rest of the codebase: `Decimal(str(float_val))` for `strike`, `bid`, `ask`, `price`. Greeks remain `float` as defined on `OptionQuote` (the model uses `float` for greeks intentionally).

### D4: Error mapping

HTTP errors from schwab-py follow the existing pattern in `get_last_price` and `get_historical_prices`: check `resp.status_code` against `httpx.codes.OK`, raise `AppError` with appropriate HTTP status (401→401, 403→403, 429→429, others→502).

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Schwab `get_quotes` may not return greeks for options | Fallback to narrowed chain call; tested explicitly |
| OCC symbol parsing for fallback path is fragile | Use regex `^(\w+)\s+(\d{6})([CP])(\d{8})$`; raise `AppError(400)` on parse failure |
| `"volatility"` field name confusion with future Schwab API changes | Documented in code comment; single parse point in `_parse_option_chain` |
| IV value is a percentage-float (22.3 not 0.223) | Stored as-is matching the `OptionQuote.implied_volatility: float` field — consistent with IBKR |
