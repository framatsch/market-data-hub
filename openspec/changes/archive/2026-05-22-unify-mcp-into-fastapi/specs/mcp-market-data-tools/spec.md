## ADDED Requirements

### Requirement: Get last price tool
The system SHALL expose a `get_last_price` MCP tool that returns the current price for a symbol.

#### Scenario: Valid symbol
- **WHEN** `tools/call` with `name=get_last_price` and `arguments={"symbol":"AAPL"}`
- **THEN** the response content contains the last trade price as a JSON text block via the default price provider

### Requirement: Get historical prices tool
The system SHALL expose a `get_historical_prices` MCP tool that returns OHLCV history.

#### Scenario: Valid symbol and date range
- **WHEN** `tools/call` with `name=get_historical_prices` and `arguments={"symbol":"AAPL","start_date":"2024-01-01","end_date":"2024-01-31"}`
- **THEN** the response content contains a JSON list of OHLCV records

### Requirement: Get option chain tool
The system SHALL expose a `get_option_chain` MCP tool that returns all option contracts for a symbol.

#### Scenario: Valid underlying symbol
- **WHEN** `tools/call` with `name=get_option_chain` and `arguments={"symbol":"AAPL"}`
- **THEN** the response content contains a JSON list of option contract objects via the default options provider

### Requirement: Get option quote tool
The system SHALL expose a `get_option_quote` MCP tool that returns a single option contract quote.

#### Scenario: Valid option ID
- **WHEN** `tools/call` with `name=get_option_quote` and `arguments={"symbol":"AAPL","option_id":"AAPL240119C00150000"}`
- **THEN** the response content contains the option quote as a JSON text block

### Requirement: Get company profile tool
The system SHALL expose a `get_company_profile` MCP tool that returns fundamental company data.

#### Scenario: Valid ticker
- **WHEN** `tools/call` with `name=get_company_profile` and `arguments={"symbol":"AAPL"}`
- **THEN** the response content contains company profile JSON via the default company provider

### Requirement: Search companies tool
The system SHALL expose a `search_companies` MCP tool that returns a list of matching companies.

#### Scenario: Text query
- **WHEN** `tools/call` with `name=search_companies` and `arguments={"query":"Apple"}`
- **THEN** the response content contains a JSON list of matching company results

### Requirement: Get company news tool
The system SHALL expose a `get_company_news` MCP tool that returns recent news articles.

#### Scenario: Valid symbol
- **WHEN** `tools/call` with `name=get_company_news` and `arguments={"symbol":"AAPL"}`
- **THEN** the response content contains a JSON list of news articles via the default news provider

### Requirement: Tool error response
The system SHALL return a structured error when a tool handler raises an exception.

#### Scenario: Provider error
- **WHEN** a tool handler raises an `AppError` or any exception
- **THEN** the SSE response MUST contain `{"error": {"message": "<description>"}}` instead of crashing the stream
