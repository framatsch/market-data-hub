## 1. Central parser

- [x] 1.1 Create `app/utils/symbols.py` with `SecType`, `ParsedSymbol` (`root`, `sec_type`, `canonical`), `parse_symbol(raw, sec_type=None, *, allowed=None)` and per-endpoint type sets (`PRICE_TYPES`, `VOLATILITY_TYPES`, `OPTION_UNDERLYING_TYPES`, `COMPANY_TYPES`, `STREAM_TYPES`)
- [x] 1.2 Implement the grammar:
  - `F:`/`I:`/`O:` prefixes, `^` and `/` aliases, whitespace trimming, upper-casing
  - rejection of unknown prefixes, empty roots and `:` in roots
  - rejection of provider-native `.`/`$` notations with a canonical suggestion (`DataValidationError`)
- [x] 1.3 Implement the `sec_type` vocabulary:
  - case-insensitive, `STK` becomes `stock`
  - prefix/`sec_type` conflict detection, `etf` only on bare symbols
  - `allowed` enforcement, with the parsed and supported types in details
- [x] 1.4 Add `strip_option_prefix(option_id)` for `O:` on option ids
- [x] 1.5 Add `tests/unit/test_symbols.py` covering every `symbol-namespaces` grammar, vocabulary and resolution scenario
- [x] 1.6 Add a FastAPI dependency factory `symbol_param(allowed)` that reads path `symbol` and optional query `sec_type: str | None` and returns `ParsedSymbol`

## 2. Errors

- [x] 2.1 Add `ProviderNotEntitledError` (`PROVIDER_NOT_ENTITLED`, HTTP 403, details `provider`/`symbol`/`instrument`/`provider_message` ≤ 500 chars) to `app/utils/errors.py` and the exception handler mapping in `app/main.py`
- [x] 2.2 Extend `map_httpx_http_error` with an optional 403 classifier. 401 stays `PROVIDER_NOT_AVAILABLE`, and the default behaviour is unchanged for callers without a classifier
- [x] 2.3 Make MCP error serialization pass `PROVIDER_NOT_ENTITLED` through, and add a test in `test_mcp_errors.py`

## 3. Cache keys

- [x] 3.1 Change `_compose_key` to take `ParsedSymbol | None`, emit `quote(canonical, safe="")` as the symbol segment, and drop `sec_type` from params unless it is `etf`
- [x] 3.2 Update `mdh_key_builder` to parse `path_params["symbol"]` with the request's `sec_type`, re-raise `DataValidationError` so nothing is cached, and keep symbol-less routes working
- [x] 3.3 Update `cached_call` to accept `ParsedSymbol`
- [x] 3.4 Extend `tests/unit/test_cache.py`:
  - namespaced key
  - legacy `sec_type` and alias sharing an entry
  - ETF key
  - `_key_parts` route derivation for `I%3ASPX`
  - updated existing expectations

## 4. Provider support sets and models

- [x] 4.1 `base.py`: add `price_sec_types`, `price_history_sec_types` (default `{stock, etf}`) and `option_underlying_sec_types` (default `{stock, etf}`)
- [x] 4.2 Add optional `source_instrument` to `PriceQuote` and `PriceBar`, and include it in the CSV exports
- [x] 4.3 `routes_admin.py`: expose `price_support` and `options_support` next to `volatility_support`; update `admin/src/types.ts` and the provider details view
- [x] 4.4 Admin API/UI tests for the new support fields

## 5. Services

- [x] 5.1 `PriceService`:
  - take `ParsedSymbol`
  - check `price_sec_types`/`price_history_sec_types` (raise 501 `CapabilityNotSupportedError` otherwise)
  - pass `root`/`sec_type` to providers (removing the `"STK"` default)
  - set canonical `symbol` on results
- [x] 5.2 `VolatilityService`: take `ParsedSymbol`, drop the vocabulary check from `_check_support` (keep provider capability checks), and set canonical `symbol` on results
- [x] 5.3 `OptionsService`: take `ParsedSymbol` for the underlying, check `option_underlying_sec_types`, pass `root`/`sec_type`, and set canonical `underlying_symbol`
- [x] 5.4 `CompanyService` and `NewsService`: take `ParsedSymbol` and forward `root`
- [x] 5.5 Update `tests/unit/test_services.py` and `tests/unit/test_volatility_service.py` (501 before any provider call, canonical symbols)

## 6. Provider native mapping

- [x] 6.1 IBKR:
  - `_contract_for(root, sec_type)` with index table (`DJI` → `INDU`) and exchange lookup
  - futures front month via the `_volatility_contract` selection for last price, `ContFuture` for history
  - set `source_instrument`
  - fix the last-price fallback to reuse the resolved contract/`sec_type`
  - declare `{stock, etf, index, future}` for prices
  - option underlyings: keep `{stock, etf}` unless index chains are implemented
- [x] 6.2 LSEG prices:
  - index → `.` + root
  - future → root' + `c1` with deviation table (`ZC`→`C`, `ZW`→`W`, `ZS`→`S`, `ZN`→`TY`, `ZB`→`US`)
  - bypass the equity RIC search for both
  - set `source_instrument`
  - verify RICs against LSEG docs/live, then declare the verified types
- [x] 6.3 Schwab:
  - index → `$` + root, future → `/` + root for quotes, history and option-chain underlyings
  - verify each against the Schwab docs and declare only verified types in `price_sec_types`, `price_history_sec_types` and `option_underlying_sec_types`
- [x] 6.4 Polygon:
  - index → `I:` + root (last price and aggregates); futures not declared
  - check `I:` for option-chain underlyings and declare it if supported
- [x] 6.5 Prixe: check the API docs for index/future support. If absent, keep the defaults and document this in the provider docstring
- [x] 6.6 Provider unit tests per mapping scenario in `provider-symbol-mapping` (native identifier sent, `source_instrument`, unknown-root pass-through)

## 7. Entitlement detection

- [x] 7.1 Polygon: 403 / `NOT_AUTHORIZED` raises `ProviderNotEntitledError` after the existing previous-close fallback has been tried
- [x] 7.2 LSEG: apply the permission-token classifier to price and volatility fetches and raise `ProviderNotEntitledError`, replacing `PROVIDER_NOT_AVAILABLE`/`not_entitled`
- [x] 7.3 IBKR: map 354/10089 (and 10091 without fallback) to `ProviderNotEntitledError` in the price, options and volatility paths; keep the `IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR` behaviour
- [x] 7.4 Schwab/Prixe: a 403 classifier that keeps token/credential failures as `PROVIDER_NOT_AVAILABLE` (Schwab client reset preserved)
- [x] 7.5 Tests per provider: entitlement error, credential failure unaffected, fallback precedence, and errors not cached

## 8. REST routes

- [x] 8.1 `routes_prices.py`:
  - use `symbol_param(PRICE_TYPES)` and remove inline `.upper()`/`.lower()`
  - update docstrings (`I:SPX`, `F:ES`, `^` alias, 403/501 semantics)
  - URL-encode the canonical symbol in CSV filenames
- [x] 8.2 `routes_volatility.py`: use `symbol_param(VOLATILITY_TYPES)`, change `sec_type` to an optional case-insensitive string, and update docstrings
- [x] 8.3 `routes_options.py`: underlying via `symbol_param(OPTION_UNDERLYING_TYPES)` and `option_id` via `strip_option_prefix`
- [x] 8.4 `routes_companies.py`: profile and news via `symbol_param(COMPANY_TYPES)`; leave search `q` untouched
- [x] 8.5 `routes_ws.py`: parse subscribed symbols with `STREAM_TYPES` (the `/` alias is allowed) and echo the canonical symbol
- [x] 8.6 Route tests:
  - `/volatility/F:ES/stats` matches
  - contradicting `sec_type` gives 422
  - `.SPX` gives 422 with a suggestion
  - `/companies/F:ES` gives 422 without a provider call
  - `^SPX` gives `I:SPX` in the response
  - `sec_type=INDEX` is accepted
  - `F:ES` at Polygon gives 501

## 9. MCP

- [x] 9.1 Replace `args["symbol"].upper()` in all symbol-taking handlers with `parse_symbol(args["symbol"], args.get("sec_type"), allowed=...)` and pass the `ParsedSymbol` to services and `cached_call`
- [x] 9.2 Update the tool schemas: unified `sec_type` enum, and symbol descriptions documenting `F:ES`, `I:SPX`, `^SPX`, `/ES` and the 403/501 meanings
- [x] 9.3 Make `get_company_news` go through `NewsService` instead of calling the provider directly
- [x] 9.4 Update `tests/unit/test_mcp_tools.py` and `tests/unit/test_mcp_volatility.py` (the `/ES` alias, REST/MCP parity, not-entitled error code)

## 10. Specs, docs and verification

- [x] 10.1 Update `README.md`, `doc/mcp-guide.md` and `.github/copilot-instructions.md`:
  - symbol notation and the provider translation table
  - 501 vs 403 semantics
  - breaking changes
- [x] 10.2 Run `uv run ruff check app/`, `python skills/lint_check.py --all` and `uv run pytest --maxfail=1 --disable-warnings`, then fix fallout
- [x] 10.3 Run `openspec validate add-symbol-namespaces --strict`
- [x] 10.4 Live smoke test (manual, with the user's credentials): `I:SPX` and `F:ES` last price and history per configured provider; record verified support sets in the design
  - 2026-11-09: exercised enabled LSEG, Polygon and Schwab on localhost:9000; results and live adapter fixes recorded in `design.md`. IBKR/Prixe disabled; entitlement-denied combinations are not claimed as successful data access.
