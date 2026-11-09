## MODIFIED Requirements

### Requirement: Transparent cache key naming
Cache keys SHALL follow `mdh:{route_path}:{symbol}:{query_params}` where:
- `route_path` is the route template without path parameters joined by `:`, unless the route declares an explicit route key (`companies:profile` for `GET /companies/{symbol}`).
- `symbol` is the canonical symbol produced by the central symbol parser, percent-encoded so it contains no `:` (`F:ES` becomes `F%3AES`). It is empty when the route has no symbol.
- `query_params` is the URL-encoded, alphabetically sorted list of declared, non-empty query parameters (`-` when none).

`sec_type` SHALL NOT appear in `query_params` unless it is `etf`, because the canonical symbol already encodes the type. `provider` and `format` values SHALL be lower-cased to mirror route normalization. The company search `q` value SHALL be trimmed, whitespace-collapsed and lower-cased. Undeclared query parameters SHALL NOT influence the key.

#### Scenario: Option chain key
- **WHEN** `GET /options/spx/chain?provider=Schwab` is requested
- **THEN** the cache key is `mdh:options:chain:SPX:provider=schwab`

#### Scenario: Explicit route key
- **WHEN** `GET /companies/aapl?provider=finnhub` is requested
- **THEN** the cache key is `mdh:companies:profile:AAPL:provider=finnhub`

#### Scenario: Route without symbol
- **WHEN** `GET /market-status?provider=polygon` is requested
- **THEN** the cache key is `mdh:market-status::provider=polygon`

#### Scenario: Namespaced symbol key
- **WHEN** `GET /volatility/F:ES/stats?provider=lseg` is requested
- **THEN** the cache key is `mdh:volatility:stats:F%3AES:provider=lseg`

#### Scenario: Legacy sec_type shares the entry
- **WHEN** `GET /volatility/ES/stats?sec_type=future&provider=lseg` and `GET /volatility/F:ES/stats?provider=lseg` are requested
- **THEN** both requests use the cache key `mdh:volatility:stats:F%3AES:provider=lseg`

#### Scenario: Alias shares the entry
- **WHEN** `GET /prices/^SPX/history?provider=ibkr` and `GET /prices/I:SPX/history?provider=ibkr` are requested
- **THEN** both requests use the same cache entry

#### Scenario: ETF keeps sec_type
- **WHEN** `GET /volatility/SPY?sec_type=etf&provider=lseg` is requested
- **THEN** the cache key is `mdh:volatility:snapshot:SPY:provider=lseg&sec_type=etf`

#### Scenario: Route key parsing with namespaced symbol
- **WHEN** the cache backend derives the route of the key `mdh:prices:history:I%3ASPX:interval=1d&provider=ibkr` to resolve its TTL
- **THEN** the derived route is `prices:history`
