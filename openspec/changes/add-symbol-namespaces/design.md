## Context

Symbols reach the hub through:
- 9 REST routes (prices, options, companies, volatility)
- 10 MCP tools (`app/api/mcp.py`)
- the WebSocket subscription (`routes_ws.py`)

There is no shared normalization. Instead:
- Routes and MCP handlers call `.upper()` inline.
- Volatility providers strip `^`/`.` (`lstrip("^.")` in `lseg._volatility_instrument` and `ibkr._volatility_contract`). `ibkr._create_contract` strips `^` only for indices.
- `sec_type` comes in different flavors:
  - volatility: a case-sensitive `Literal["stock","etf","index","future"]`
  - prices: a free-form string, lower-cased in REST but not in MCP
  - default: `"stock"` in latest-price paths, `"STK"` in historical paths
- Only IBKR (prices) and LSEG/IBKR (volatility) actually act on `sec_type`. Polygon, Schwab and Prixe ignore it.
- Cache keys (`app/cache.py`) embed the upper-cased raw path symbol. `_key_parts` splits the key on `:` to recover the route for TTL resolution, so any `:` in a symbol would corrupt it.

## Goals / Non-Goals

**Goals:**
- One self-describing symbol notation that works on every interface and resolves ambiguity (`ES` stock vs `F:ES` future).
- One parser and one `sec_type` vocabulary. All inline normalization goes away.
- Backward compatibility for requests: bare symbols and `sec_type` keep working.
- Identical cache entries for equivalent requests (`ES?sec_type=future` and `F:ES`).
- Every provider either serves a namespaced symbol correctly (native translation) or says clearly why not. A 501 means the hub has no implementation. A 403 means the subscription does not cover it.
- No hard-coded knowledge about user subscriptions.

**Non-Goals:**
- Crypto/FX namespaces (`X:`, `C:`). The grammar leaves room for them but they are not implemented.
- Specific futures contracts (`F:ESZ6`) and back-adjusted continuous series.
- Polygon futures (a separate product with different endpoints) and automatic fallback to another provider when one cannot serve a type.
- Batch or watchlist endpoints.
- Changing provider method signatures in `app/providers/base.py`.

## Decisions

### D1: Colon-prefixed namespaces, Polygon-compatible where possible
Prefixes are `F:`, `I:` and `O:`, with no prefix meaning stock/ETF. The colon never appears in equity tickers. It is a legal URL path character, so `/volatility/F:ES/stats` routes without encoding, and the same notation works in path, query, MCP and WebSocket. `I:` and `O:` match Polygon's own conventions. `F:` is our own.
- *Alternatives:* `F_ES`/`IDX_SPX` (underscores collide with real share-class tickers such as `BRK_B`). `/ES` as the canonical form (breaks REST path routing).
- *No `E:` for ETFs:* ETFs behave like stocks in every provider. Only volatility echoes `etf` in `sec_type`, which stays possible via `sec_type=etf`.

### D2: `^` and `/` as input-only aliases
`^SPX` is already used in docs and client habits. `/ES` is the common futures notation in brokers. Both parse to the canonical form and are never emitted. `/` only works where the symbol is not a URL path segment.

Provider-native forms (`.SPX` from LSEG, `$SPX` from Schwab) are **rejected** with a 422 that suggests `I:SPX`. Accepting one provider's native syntax would invite accepting all of them (`ESc1`, `^GSPC`, ...), which is exactly the ambiguity this change removes. The translation direction is always canonical to native, inside the provider. The `ric` override stays as the explicit escape hatch. This slightly breaks `/volatility/.SPX`, which worked only because LSEG/IBKR stripped the dot.

### D3: Parser in `app/utils/symbols.py`, applied at the edge
```python
SecType = Literal["stock", "etf", "index", "future", "option"]

@dataclass(frozen=True, slots=True)
class ParsedSymbol:
    root: str
    sec_type: SecType
    @property
    def canonical(self) -> str: ...   # "F:ES", "I:SPX", "O:...", "AAPL"

def parse_symbol(raw: str, sec_type: str | None = None,
                 *, allowed: frozenset[SecType] | None = None) -> ParsedSymbol
```
- `parse_symbol` normalizes `sec_type` (lower-case, `STK` becomes `stock`), checks prefix vs `sec_type` conflicts, and enforces `allowed`. Every failure raises `DataValidationError` (HTTP 422).
- **Where it is called:** REST routes and MCP handlers call it, so per-endpoint `allowed` sets live next to the interface definition, and the cache key builder calls it with the same inputs. Services receive the `ParsedSymbol` and pass `root` and `sec_type` to providers, then set the canonical symbol on results.
- *Alternative considered:* parsing only inside services. Rejected because the REST cache key is built by `mdh_key_builder` *before* the handler runs. It must parse too, and duplicate parsing in route and service would invite drift.
- REST: a small FastAPI dependency per route family (e.g. `price_symbol = Depends(symbol_param(PRICE_TYPES))`) reads `symbol` and `sec_type` and returns `ParsedSymbol`. The `sec_type` query parameter is declared as an optional `str`, so the parser, not FastAPI's enum validation, produces the uniform error.

### D4: Services take `ParsedSymbol`
Service methods change from `(symbol: str, ..., sec_type: str)` to `(symbol: ParsedSymbol, ...)`:
- `PriceService`, `VolatilityService`, `OptionsService` (underlying), `CompanyService`, `NewsService`
- This removes the `"stock"`/`"STK"` default split in one place.
- `VolatilityService._check_support` keeps its provider capability check but no longer validates the vocabulary, since the parser already has.
- Services overwrite `symbol` (and `underlying_symbol`) on returned models with `parsed.canonical`. Provider method signatures stay unchanged. Providers only gain internal native-symbol translation (D9).

### D5: Cache keys use percent-encoded canonical symbols
- `_compose_key(route_key, symbol, params)` gets a `ParsedSymbol` (or `None` for symbol-less routes).
- The symbol segment is `quote(parsed.canonical, safe="")`, so `F:ES` becomes `F%3AES`.
- `sec_type` is removed from params unless it is `etf`.
- `_key_parts` keeps working unchanged because no raw `:` remains in the symbol segment. A regression test covers `I%3ASPX`.
- `mdh_key_builder` parses `request.path_params["symbol"]` with the route's `sec_type` query value. MCP `cached_call` receives the `ParsedSymbol` from the handler.
- If parsing fails inside the key builder, it must not mask the 422. The builder re-raises `DataValidationError` so the normal handler responds and nothing is cached.
- *Alternative:* keep the raw symbol and teach `_key_parts` to parse from known route keys. Rejected as more fragile, and it would not unify equivalent requests.

### D6: Canonical `symbol` in responses (breaking for index/future)
Clients get a value they can feed back into any endpoint. Stocks and ETFs are unaffected, so the blast radius is limited to index and future consumers. `source_instrument`, `underlying` and `option_id` keep provider values for traceability.

### D7: Option ids
`O:` is accepted on `option_id` (stripped before the provider call) so watchlists can store options uniformly. Underlying `{symbol}` on option routes must not be `option` or `future`. The `O:` canonical form is only emitted where a field is defined as a canonical symbol. `OptionQuote.symbol` stays the provider's contract symbol, and `underlying_symbol` becomes canonical.

### D8: Two separate gates, implementation vs entitlement
| Question | Decided by | Answer when "no" |
|---|---|---|
| Has the hub implemented this type for this provider? | Code: `price_sec_types`, `price_history_sec_types`, `option_underlying_sec_types`, `volatility_*_sec_types` | 501 `CAPABILITY_NOT_SUPPORTED` before any provider call |
| Does the user's subscription cover it? | Provider response at runtime | 403 `PROVIDER_NOT_ENTITLED` |

- Support sets are static because they describe code: is there a translation, and does the provider API have the endpoint at all. They change only when the hub changes.
- Subscriptions change without deploys, so they are never encoded. Errors are never cached (existing `response-caching` requirement), so an upgrade works on the next request.
- *Alternative considered:* an admin-configurable per-provider allow-list of types to skip known-unsubscribed calls. Not needed for correctness, so it is left out (possible later as a pure optimisation).
- *Alternative considered:* keeping 503 `PROVIDER_NOT_AVAILABLE` with `reason=not_entitled`. Rejected because 503 signals a transient outage and invites retries, while a missing subscription is permanent until the user acts. 403 plus a dedicated code is unambiguous. The code distinguishes it from hub API-key auth failures, which are 401.

### D9: Translation lives in the provider, tables per provider
Each provider gets a small `_native_symbol(root, sec_type) -> str` (IBKR: `_contract_for(...)`) plus a `_ROOT_OVERRIDES: dict[tuple[sec_type, root], str]` for deviations. Unknown roots pass through with the type decoration, so new indices and futures work without code changes when the provider uses the standard symbol. Canonical roots are the primary listing symbols (index publisher tickers, CME Globex roots) because they are the most widely recognised and match IBKR and Polygon in most cases.

Initial deviation tables (to be verified per provider during implementation, see tasks):
- IBKR index: `DJI` → `INDU`
- LSEG futures: `ZC` → `C`, `ZW` → `W`, `ZS` → `S`, `ZN` → `TY`, `ZB` → `US`

Services stay provider-agnostic: they pass `root` and `sec_type` and overwrite `symbol` with the canonical form.

### D10: Futures = front month, transparent about the contract
- Last price uses the nearest non-expired contract. IBKR reuses the selection in `_volatility_contract` (exchange table `_FUTURES_EXCHANGES`, ambiguity → 422).
- History uses the provider's own continuous series (IBKR `ContFuture`, LSEG `c1`, Schwab `/ROOT`). Rolls therefore differ slightly between providers.
- `source_instrument` on `PriceQuote` and `PriceBar` makes the actually queried instrument visible (an optional field, non-breaking).
- Back-adjustment and explicit contracts are out of scope.

### D11: Entitlement detection per provider
- A shared helper in `app/utils/errors.py` builds `ProviderNotEntitledError`.
- `map_httpx_http_error` keeps 401 → `PROVIDER_NOT_AVAILABLE`. For 403, providers pass a classifier, because Schwab can answer 403 for token problems and must keep its client-reset behaviour.
- LSEG reuses the token list already in `_fetch_volatility_data` and applies it to price fetches too.
- IBKR maps 354/10089 (and 10091 without fallback) in both the price and volatility paths, replacing the current `not_entitled` 503.

## Risks / Trade-offs

- [Breaking `symbol` value for index/future responses] → Called out in the proposal and README. Stock responses (the majority of traffic) are unchanged.
- [Cache entries invalidated on deploy] → Old keys simply age out via TTL. Optionally run admin "clear cache" after deploy.
- [`^` in URLs must be percent-encoded by strict clients] → Starlette decodes `%5E`. `I:` is the documented path form.
- [Native symbol formats assumed from documentation may be wrong (Schwab futures history, Prixe indices, LSEG futures roots)] → A type is only added to a provider's support set after verification against docs or a live call. Unverified combinations return 501 instead of wrong data.
- [Continuous futures series differ by provider roll convention] → Documented, and `source_instrument` is exposed. Explicit contracts can be added later.
- [Breaking: volatility not-entitled moves from 503 to 403, and stock-like data for `I:`/`F:` at unsupported providers becomes 501] → Called out in the proposal. Clients that retried on 503 stop retrying a permanent condition, which is the intent.
- [Schwab 403 ambiguity (token vs entitlement)] → Provider-specific classifier. When unsure, keep `PROVIDER_NOT_AVAILABLE`.
- [Path-level routing with `:`] → Starlette's default `str` convertor matches `[^/]+`, so colons are fine. A route test for `/volatility/F:ES/stats` guards it.
- [Large mechanical diff across routes, MCP and services] → Implemented per interface family with tests after each step. The parser lands first with exhaustive unit tests.

## Migration Plan

1. Deploy. No config or data migration is needed.
2. Optionally clear the response cache via the Admin UI to free orphaned keys immediately.
3. Clients may switch to `F:`/`I:` at their own pace. `sec_type` remains supported.
4. Rollback: redeploy the previous image. New-format cache keys are ignored by the old version and expire.

## Open Questions

- Prixe: resolved from the documentation. The API documents stock tickers (plus a separate crypto product) and no index/futures notation, so the support sets stay `{stock, etf}`.
- Schwab: resolved from the documentation. schwab-py states that price history exists only for equities and ETFs (index history `$SPX` is used in practice), and that futures are quote-only (`get_quotes(["/ES"])`). Declared: `price_sec_types` `{stock, etf, index, future}`, `price_history_sec_types` and `option_underlying_sec_types` `{stock, etf, index}`.

### Declared support sets (live checks below, task 10.4)

| Provider | `price_sec_types` | `price_history_sec_types` | `option_underlying_sec_types` |
|---|---|---|---|
| IBKR | stock, etf, index, future | stock, etf, index, future | stock, etf |
| LSEG | stock, etf, index, future (`.SPX`, `ESc1` are documented RICs) | same | – |
| Schwab | stock, etf, index, future | stock, etf, index | stock, etf, index |
| Polygon | stock, etf, index (`I:` snapshot / aggregates) | stock, etf, index | stock, etf, index |
| Prixe | stock, etf | stock, etf | – |

Polygon index last price uses `/v3/snapshot/indices` (NBBO is an equities endpoint) and falls back to previous close. Schwab and Prixe classify a 403 as `PROVIDER_NOT_ENTITLED` only when the body names a plan/entitlement and not a token or key; unclear cases stay `PROVIDER_NOT_AVAILABLE`.

### Live smoke test: 2026-11-09

Tested the user's Compose service at `localhost:9000` with the enabled providers
LSEG, Polygon and Schwab. History requests used `Cache-Control: no-store`, interval
`1d`, and dates `2026-10-26` to `2026-11-09`. IBKR and Prixe were disabled and were
not live-verified. Denied requests prove the reported denial, not successful data
access or support for every root of that type. Subscription results below are
observations for this account, not hard-coded provider capabilities.

| Provider | `I:SPX` last / history | `F:ES` last / history |
|---|---|---|
| LSEG | 403 / 403, `.SPX`: `TSCC.QS.UserNotPermission` | 200 / 200, `ESc1` (9 daily bars) |
| Polygon | 403 / 403, `I:SPX`: explicit subscription denial, including previous-close fallback | 501 / 501, no implementation |
| Schwab | 200 / 200, `$SPX` (10 daily bars) | 200, `/ESZ26` / 501, no futures history implementation |

Two adapter defects were reproduced and fixed before repeating the live calls:

- **Schwab futures quotes:** `/ES` returns a response keyed by the active contract
  `/ESZ26`, not `/ES`. Resolve by `assetMainType=FUTURE`, exact `reference.product`,
  and `futureIsActive=true`; reject missing/ambiguous matches and return the
  contract key in `source_instrument`. Also verified `F:NQ` → `/NQZ26` and legacy
  `ES?sec_type=future` → `F:ES`, all HTTP 200.
- **LSEG index IV:** `SPXATMIV.U` and `NDXATMIV.U` provide valid IV but can omit
  `GN_TXT16_5`. Permit a missing market only for an index whose returned `Instrument`
  and cash-index `UNDERLYING` exactly match the request. Preserve `market=null`;
  do not infer a market or ignore explicit conflicting metadata. This fixes both
  snapshot validation and the history precheck. Snapshot, history and stats now
  return 200 for `I:SPX`, `I:NDX` and `F:ES`. SPX/NDX histories contained 249/247
  points over the default year; all three stats requests contained 252 points.
  Legacy `SPX?sec_type=INDEX`, `^SPX` and `ES?sec_type=future` were also verified.

The bare price requests are not equivalent to explicit namespaces: service logs
showed `SPX` resolving to `SPX.L` and `ES` to `ESv1` via the existing equity search.
Their HTTP 200 responses do not establish entitlement for `.SPX`. The central
parser correctly resolves all explicit namespace and legacy-parameter requests.

Regression evidence: 8 cases failed before the fixes; the targeted suite passed
81 tests afterwards. Full suite: **940 passed, 21 skipped**; `ruff check app/ tests/`
passed. The Compose application was restarted to load the fixes and live calls
were repeated successfully.
