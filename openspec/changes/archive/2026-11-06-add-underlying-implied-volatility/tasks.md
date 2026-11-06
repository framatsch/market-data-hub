## 0. Spikes (live, before coding)

- [x] 0.1 Probe entitlement and access paths: `TR.*` datagrid ❌, REST pricing snapshot ❌, streaming `rd.get_data` FIDs ✅, `historical_pricing` ✅ (see design.md → Spike Findings)
- [x] 0.2 Probe history shape: `historical_pricing.summaries` daily with explicit FIDs → `Date` index, `Float64` columns, > 2 years depth
- [x] 0.3 Probe unknown instruments and entitlement errors: unknown RIC → NaN row (no exception); `Insufficient scope …` / `UserNotPermission` messages recorded
- [x] 0.4 Realized volatility `TR.Volatility*` → not entitled → dropped from scope
- [x] 0.5 Verify naming across asset classes (OPRA `.U`, futures no suffix, Eurex `.EX`) and detect ticker collisions (`ESATMIV.U` = Eversource, `CLATMIV.U` = Colgate)
- [x] 0.7 IBKR spike (`tmp/ibkr_iv_spike.py`, design → IBKR Spike Findings):
  - tick 106 works with delayed data (incl. CL; GC → None)
  - `OPTION_IMPLIED_VOLATILITY` history is OK for STK/ETF/IND (2 years) and unusable for futures
- [x] 0.8 Polygon spike (`tmp/polygon_iv_spike.py`): the key is valid, but `/v3/snapshot/options/*` returns 403 `NOT_AUTHORIZED` for all underlyings incl. `SPX`/`I:SPX`. Polygon has no IV history at any plan → **Polygon dropped from scope**
- [x] 0.6 Copy the relevant spike CSVs from `tmp/lseg_iv_spike_out/` into `tests/fixtures/lseg_volatility/`: AAPL/SPY/SPX/ES snapshot rows, the R6 underlying check, the batch with an unknown RIC, the AAPL daily history and the error messages

## 1. Models & Base Capability

- [x] 1.1 Create `app/models/volatility.py` with `ImpliedVolatilityTenor`, `VolatilitySnapshot` (incl. `underlying`, `underlying_name`, `market`, `as_of`), `VolatilityPoint`, `VolatilityHistory` and `VolatilityStats` (design D8). Use Decimal fractions and `sec_type: Literal["stock","etf","index","future"]`
- [x] 1.2 Add helpers, with unit tests:
  - `quantize_iv(value) -> Decimal | None` (4 dp, `ROUND_HALF_UP`, None for NaN/≤0)
  - `combine_iv(call, put, combined=None)` (mean / single / combined / None)
  - `uniform_tenors(dict[int, tenor]) -> list` (always 30/60/90 in order, missing → all null)
- [x] 1.3 Add `BaseVolatilityProvider` to `app/providers/base.py`:
  - abstract `get_implied_volatility`, `get_implied_volatility_history` and `test_connection`, plus the shared `configure()` pattern
  - class attributes `volatility_sec_types`, `volatility_history_sec_types` and `volatility_tenors`
- [x] 1.4 Add `CapabilityNotSupportedError` (code `CAPABILITY_NOT_SUPPORTED`) to `app/utils/errors.py` and map it to 501 in `app_error_handler`
- [x] 1.5 Add the `method` field (`provider_atm_index` | `provider_model_30d`) to `VolatilitySnapshot`

## 2. Registry & System Defaults

- [x] 2.1 Add `default_volatility_provider` to `SETTINGS_ALLOWLIST` in `app/admin/settings_repository.py`
- [x] 2.2 Extend `app/providers/registry.py` with `default_volatility_provider`:
  - add it to `DEFAULT_PROVIDER_FALLBACKS`
  - add the instance attribute
  - resolve it in `_apply_default_settings` against `BaseVolatilityProvider`
  - add it to the reload key list
  - add `get_volatility_provider` / `use_volatility_provider`, mirroring the options variants
- [x] 2.3 Extend `app/api/routes_admin.py`:
  - `SystemDefaultsUpdate` and `_system_defaults()`
  - `_provider_capabilities()` (`"volatility"`)
  - `PROVIDER_CAPABILITIES["lseg"|"ibkr"]` += `volatility`
  - the `/settings/capabilities` category map
  - `volatility_support` (the three D1 sets) in `GET /api/admin/providers`
- [x] 2.4 In `app/api/routes_meta.py`, add `volatility` to `defaults` and `available`
- [x] 2.5 Unit tests:
  - the settings repo accepts the new key
  - the registry resolves or rejects the default by capability
  - admin defaults GET/PUT round-trip
  - capabilities include `volatility` for LSEG

## 3. LSEG Implementation

- [x] 3.1 Make `LSEGProvider` inherit `BaseVolatilityProvider`
- [x] 3.2 Implement the pure function `_volatility_instrument(symbol, sec_type, ric)`, with unit tests:
  - stock/etf/index → `{SYM}ATMIV.U`
  - future → `{ROOT}ATMIV`
  - `ric` → verbatim
  - upper-case the symbol and strip a leading `^`/`.`
- [x] 3.3 Implement `_get_implied_volatility_sync`:
  - use `rd.get_data(ric, IV_FIDS + META_FIDS)` (streaming path; no `TR.*`, no `pricing.Definition().get_data()`)
  - go through session, throttle and retry
  - convert percent to fractions and handle NaN
  - set `as_of` from `TRADE_DATE`, and map `underlying`/`underlying_name`/`market` from `UNDERLYING`/`INST_DESC`/`GN_TXT16_5` (stripped)
  - no provider-level cache (Redis response cache, design D9)
- [x] 3.4 Implement market validation per design D3 (stock/etf/index → `OPRA`; future → `COMFUT`|`CMEG`; skipped when `ric` is given) and raise `DataValidationError` with the expected and actual market and `underlying_name`
- [x] 3.5 Implement `_get_implied_volatility_history_sync`:
  - `historical_pricing.summaries` at DAILY interval with `start`/`end` and explicit `fields` for the tenor
  - drop all-NaN rows and sort ascending
- [x] 3.6 Implement the error mapping per design D5:
  - all-NaN snapshot → `no_iv_data`
  - empty history → `no_iv_history`
  - `UserNotPermission` / `Insufficient scope` → `PROVIDER_NOT_AVAILABLE` with `not_entitled`
  - add `"user has no permission"` / `"insufficient scope"` to the non-retryable keywords in `_is_retryable_error`
- [x] 3.7 Add async wrappers `get_implied_volatility` / `get_implied_volatility_history` via `asyncio.to_thread`
- [x] 3.8 Write unit tests with mocked `rd.get_data` / `historical_pricing` using the spike fixtures. Cover:
  - each sec_type: stock, ETF, index, future (`ESATMIV`)
  - the Eurex override (`GDAXATMIV.EX`)
  - unit conversion; two direct provider calls issue two upstream requests (no provider cache)
  - history parsing (drop NaN rows, sort ascending)
  - market mismatch (`ESATMIV.U` requested as a future → 422)
  - every error path
- [x] 3.9 Correct the LSEG comment in `app/config.py`: streaming pricing works; REST pricing snapshots and `TR.*` datagrid fields are not entitled

## 3b. IBKR Implementation (design D10)

- [x] 3b.1 Make `IBKRProvider` inherit `BaseVolatilityProvider` with support sets {stock, etf, index, future} / {stock, etf, index} / {30}
- [x] 3b.2 Fix `_get_index_exchange` (`RUT` → `RUSSELL`; verify NDX/SPX/VIX) and check that existing `get_last_price(sec_type="index")` for RUT still works
- [x] 3b.3 Add the futures root → exchange map and front-month resolution (`reqContractDetailsAsync`, nearest with last trade ≥ today + 7 d; unknown root resolves only when unambiguous, else 422)
- [x] 3b.4 Implement `get_implied_volatility`:
  - streaming `reqMktData(c, "106", False, False)` with a wait loop up to `IBKR_IV_TIMEOUT_SECONDS` (new setting, default 10), and `cancelMktData` in `finally`
  - configured market data type, with a delayed fallback on 354/10089
  - fill tenor 30 `iv` (4 dp) with call/put null and tenors 60/90 null
  - set `method`, `source_instrument`, `underlying_name` (longName) and `market`
- [x] 3b.5 Implement `get_implied_volatility_history`:
  - `OPTION_IMPLIED_VOLATILITY` daily, RTH only
  - `endDateTime`/`durationStr` computed from start/end, then filter to the range
  - drop bars with close ≤ 0 and sort ascending
  - "HMDS query returned no data" → 404 `no_iv_history`
- [x] 3b.6 Reject `ric` with 422; follow the `_ensure_connection()` / `_disconnect()` pattern
- [x] 3b.7 Copy spike fixtures from `tmp/ibkr_iv_spike_out/` (AAPL/SPX history CSV, mdt3 live values) into `tests/fixtures/ibkr_volatility/`
- [x] 3b.8 Unit tests with mocked `ib_async` (no live TWS), covering:
  - each sec_type: stock, ETF, index (RUSSELL), future (front-month selection incl. the 7-day rule)
  - tick timeout → 404 with cancel called; delayed fallback
  - history duration strings (`30 D`, `365 D`, `2 Y`) and filtering
  - futures history → 501, `tenor_days=60` → 501, `ric` → 422

## 3d. Unit Consistency for Option Contracts (BREAKING, design D2)

- [x] 3d.0 Verify the unit on one live Schwab chain (e.g. SPY near-ATM, expected roughly 10–40 → percent) and record a real contract as a fixture. The user confirmed that Schwab delivers per-contract IV (but no underlying IV)
  - Additional live verification and fixture explicitly waived by the user on 2026-11-06; accepted based on the user's existing Schwab API confirmation. No new live check was performed.
- [x] 3d.1 In `app/providers/schwab.py`, normalize `implied_volatility` in `_parse_option_chain` and `get_option_quote` to fractions (`÷ 100`), mapping null/NaN/negative sentinels (`-999`) to `None`
- [x] 3d.2 Update `tests/unit/test_schwab_provider.py` (`22.345` → `0.22345`) and add a sentinel test
- [x] 3d.3 Check IBKR (`impliedVol` is already a fraction) and Polygon (fraction) option IV for consistency, and add a cross-provider unit test asserting `0 < iv < 5` for the fixtures
- [x] 3d.4 Add a CHANGELOG entry under **BREAKING**: Schwab option IV is now a fraction; all IV values in the hub are fractions

## 4. Service, REST & MCP

- [x] 4.1 Create `app/services/volatility_service.py` (`VolatilityService` using `registry.use_volatility_provider`, with structlog provider binding) and register `VolatilityServiceDep` in `app/dependencies.py`. The service checks the D1 support sets before calling the provider and raises `CapabilityNotSupportedError`; unit tests cover each provider's rejections
- [x] 4.2 Create `app/api/routes_volatility.py` with `GET /volatility/{symbol}` and `GET /volatility/{symbol}/history`:
  - query params per design D7
  - `history` defaults to the last 365 days
  - restrict `tenor_days` to 30/60/90 and validate start ≤ end
  - CSV export via `to_csv`
  - docstrings must state decimal-fraction units, end-of-day data and the `.U` vs. futures semantics
- [x] 4.3 Include the router in `app/main.py` and map `DATA_VALIDATION_ERROR` → 422 in `app_error_handler`
- [x] 4.3a Implement `VolatilityService.get_implied_volatility_stats(symbol, window, tenor_days, sec_type, ric, provider_name)` per design D8:
  - history start = end − ceil(window × 365/252) − 14 days; take the last `window` points
  - IVR/IVP formulas with `ROUND_HALF_UP` to 2 decimals (0–100); `current`/`min`/`max` as 4-dp fractions; `iv_rank=None` when max == min
  - check `volatility_history_sec_types` and tenor support first → 501
  - fewer than 20 points → `insufficient_history`
  - unit tests, including the spec example (0.20, 0.10, 0.30, 0.25 → IVR 75.00, IVP 66.67), the flat window and insufficient history
- [x] 4.3b Add `GET /volatility/{symbol}/stats` to `app/api/routes_volatility.py` (`window` 20–756, default 252; `tenor_days`; CSV). The docstring notes that IVR is sensitive to single outlier days and IVP is robust
- [x] 4.4 Add the MCP tools `get_implied_volatility`, `get_implied_volatility_history` and `get_implied_volatility_stats` in `app/api/mcp.py`: handlers, JSON schemas (incl. `sec_type` enum with `index`) and dispatch table
- [x] 4.5 Write route tests (TestClient, mocked service/provider). Cover:
  - 200 snapshot, 200 history, default 365-day window, CSV
  - 200 stats, and 422 for `window` out of range
  - 422 for an invalid tenor, an invalid range or a market mismatch
  - 400 for a provider without the volatility capability
  - 501 `CAPABILITY_NOT_SUPPORTED` (IBKR futures history, IBKR `tenor_days=60`), never cached
  - 422 for `ric` with ibkr
  - 404 and 503 mapping
  - same response shape for lseg/ibkr (field set, 3 tenors, 4-dp fractions)
  - no-default behavior
- [x] 4.6 Write MCP tool tests for all three tools

## 4b. Response Caching (design D9)

- [x] 4b.1 Add `CACHE_TTL_VOLATILITY_SECONDS: int = 900` to `app/config.py` and `.env.example`; add `cache_ttl_volatility_seconds` to the settings allowlist
- [x] 4b.2 Extend `app/cache.py`:
  - `CachePolicyValues` / `CachePolicyUpdate` / `policy_defaults()` get `volatility_seconds`
  - `CacheScope` and `_PATTERNS` get `volatility` → `mdh:volatility:*`
  - `cache_status()` counts it
  - `_compose_key` provider-default map: `volatility:snapshot|history|stats` → `registry.default_volatility_provider`
- [x] 4b.3 Extend `CachePolicy.resolve()` and place the branches before the market-closed extension:
  - `volatility:snapshot` and `volatility:stats` → `volatility_seconds`
  - `volatility:history` with `end` before yesterday 00:00 ET → `historical_closed_seconds`, otherwise `volatility_seconds`
  - never apply the extension to volatility routes
- [x] 4b.4 Decorate the three routes in `app/api/routes_volatility.py` with `@cache(expire=settings.CACHE_TTL_VOLATILITY_SECONDS, key="volatility:snapshot|history|stats")`. CSV must be a concrete `Response`, not a `StreamingResponse`
- [x] 4b.5 Route the three MCP tools through `cached_call("volatility:…", symbol, params, loader, refresh=…)` and add the `refresh` boolean to their JSON schemas
- [x] 4b.6 Add an "Implied volatility" TTL field and the `volatility` scope to `admin/src/components/CacheCard.tsx`, and the new field/scope to `admin/src/types.ts`. The extension-switch note says it does not apply to implied volatility
- [x] 4b.7 Write tests (extend `tests/unit/test_cache.py` / `test_cache_coverage.py` / `test_admin_cache_routes.py`):
  - key format incl. implicit `default_volatility_provider`
  - snapshot HIT on the second call
  - closed vs. open history TTL
  - no extension at 16:35 ET or on weekends
  - `volatility_seconds=0` serves live, while closed history is still cached
  - `ric` and `window` isolate keys
  - MCP key with `channel=mcp` and `refresh`
  - clear scope `volatility` with a provider filter
  - status key count
  - policy PUT round-trip with ten fields

## 5. Admin UI

- [x] 5.1 Add `default_volatility_provider?: string` to `admin/src/types.ts`
- [x] 5.2 Add a "Default Volatility Provider" dropdown to `admin/src/pages/SettingsPage.tsx`: initialize the state, load it from defaults, fill the options from `capabilities.volatility` and include it in the save payload
- [x] 5.3 Verify the `Volatility` chip renders on the Providers and Dashboard pages (via the existing `capabilityLabel`)
  - Browser verified two chips on the current provider-management Dashboard (`/admin`); `/admin/providers` is an existing legacy redirect there. Both component label helpers return `Volatility`; no routing changes were made.
- [x] 5.4 Build the admin UI and check the settings page manually
  - TypeScript/Vite build passed; browser save/reload persisted LSEG and displayed the 900-second IV policy in an isolated verification runtime. Screenshot: `tmp/mdh-iv-admin-settings.png`.

## 6. Docs & Verification

- [x] 6.1 Document the new endpoints in `README.md` and `.github/copilot-instructions.md` (LSEG section):
  - units (fractions, 4 dp; IVR/IVP 0–100), `sec_type`/`ric` semantics and the verified coverage table per provider (LSEG/IBKR incl. the support sets and `method`); note that Polygon is not supported (plan not entitled)
  - ETF proxies for energy/metals (USO, UNG, GLD, SLV)
  - end-of-day nature of the data
  - the `/stats` semantics (IVR vs. IVP, window, outlier sensitivity)
  - the LSEG futures caveat (ES/NQ ATMIV below cash-index IV; prefer `sec_type=index`)
  - caching: the TTLs per volatility route, why the market-closed extension does not apply, and `Cache-Control: no-cache` / MCP `refresh`
  - update the README cache section and its TTL table
- [x] 6.2 `uv run ruff check app/` and `python skills/lint_check.py --all` are clean
- [x] 6.3 `uv run pytest --maxfail=1 --disable-warnings` is green
  - Full current-worktree suite after the inclusive-start fix: 707 passed, 21 skipped (2026-11-06).
- [x] 6.4 Manual end-to-end test:
  - Verification server: `http://localhost:1900/`, Redis disabled, isolated test database. User approved switching IBKR from 4001 to the working Paper port `localhost:4002` after `TRADING_MODE=paper` was confirmed. Saved LSEG credentials remain intact.
  - Initial authentication/connection failures were resolved by corrected LSEG credentials and the IBKR Paper-port selection; initial sanitized evidence remains in `tmp/mdh-iv-live-check-20261106.json`.
  - Passed 17 LSEG and 13 IBKR live checks: snapshots, history, independent IVR/IVP arithmetic, three CSV exports and three MCP tools per provider. Evidence: `tmp/mdh-iv-lseg-live-fixed-20261106.json`, `tmp/mdh-iv-ibkr-live-20261106.json`.
  - LSEG AAPL: IVR 65.55 / IVP 74.10 over 252 points. Fixed the exclusive upstream start boundary; the exact stats window now replays all 252 points, and single-day history succeeds. Two regression cases were added.
  - Seven application validation/error checks passed (400/422/501, including unsupported IBKR futures/tenors), without cache headers.
  - The user explicitly waived the additional manual Redis-HIT/max-age verification on 2026-11-06 ("Redis-Livecheck auslassen"). No live HIT is claimed; automated cache coverage remains green and the runtime stays Redis-disabled.
  - set the default volatility provider to LSEG in the Admin UI
  - call `/volatility/AAPL`, `/volatility/SPY?sec_type=etf`, `/volatility/SPX?sec_type=index`, `/volatility/ES?sec_type=future`, `/volatility/CL?sec_type=future` (expect 404), `/volatility/AAPL/history` and `/volatility/AAPL/stats` (compare with the spike: IVR ≈ 65, IVP ≈ 74 on 2026-11-05); repeat `/volatility/AAPL` and expect `X-FastAPI-Cache: HIT` and `Cache-Control: max-age≤900`
  - IBKR (Gateway, delayed): `/volatility/AAPL?provider=ibkr`, `/volatility/CL?sec_type=future&provider=ibkr`, `/volatility/SPX/history?sec_type=index&provider=ibkr`, `/volatility/SPX/stats?sec_type=index&provider=ibkr`, `/volatility/ES/history?sec_type=future&provider=ibkr` (expect 501)
- [x] 6.5 Run `openspec validate add-underlying-implied-volatility --strict`
