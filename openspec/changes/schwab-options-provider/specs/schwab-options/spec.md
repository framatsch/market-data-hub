## ADDED Requirements

### Requirement: Schwab Options Chain
`SchwabProvider` SHALL implement `BaseOptionsProvider` and return a populated `OptionChain` for a given symbol and expiry date.

#### Scenario: get_option_chain returns all contracts for expiry
- **WHEN** `get_option_chain(symbol="AAPL", expiry=date(2024,4,5))` is called
- **THEN** the result SHALL be an `OptionChain` with `provider="schwab"`, `underlying_symbol="AAPL"`, and `options` containing both call and put `OptionQuote` objects for that expiry

#### Scenario: Strike range filter applied
- **WHEN** `get_option_chain(..., min_strike=Decimal("187"), max_strike=Decimal("195"))` is called
- **THEN** only contracts with `strike` in `[187, 195]` SHALL be returned

#### Scenario: Right filter (call/put)
- **WHEN** `get_option_chain(..., right="call")` is called
- **THEN** only call contracts SHALL be in the result

### Requirement: Schwab Option Quote
`SchwabProvider` SHALL return a single `OptionQuote` for a given OCC option symbol.

#### Scenario: get_option_quote by OCC symbol
- **WHEN** `get_option_quote(symbol="AAPL", option_id="AAPL  240405C00185000")` is called
- **THEN** the result SHALL be an `OptionQuote` with correct strike, expiry, type, price, and greeks

#### Scenario: Invalid OCC symbol
- **WHEN** `get_option_quote` is called with a malformed `option_id`
- **THEN** `AppError(400)` SHALL be raised
