## Why

Clients (and MCP agents) need the implied volatility of an **underlying**, meaning a stock, ETF, index or future, not of individual option contracts. They also need enough daily IV history to derive **IV Rank** and **IV Percentile**. Today the hub only exposes IV per option contract (`OptionQuote.implied_volatility`), and even that comes in inconsistent units (Schwab percent, IBKR/Polygon fractions). `PriceQuote` has no volatility at all, so consumers have to pull full option chains and derive a number themselves.

Live spikes on 2026-11-06 (see `design.md`) showed that two providers complement each other:

- **LSEG** publishes dedicated constant-maturity ATM IV instruments (30/60/90 days) with more than 2 years of daily history. It covers US stocks, ETFs and indices, CME/CBOT equity-index, grain and rate futures, and Eurex.
- **IBKR** delivers a live 30-day IV (tick 106, also with delayed data). This includes **crude oil futures**, which LSEG lacks. It also has a 2-year daily IV history for stocks, ETFs and indices.

Polygon was evaluated and **dropped**. Our plan returns `403 NOT_AUTHORIZED` for option chain snapshots, including the index variants `SPX` and `I:SPX`, and Polygon offers no IV history at any plan.

## What Changes

- Introduce a new provider-agnostic **volatility** capability (`BaseVolatilityProvider`) with snapshot and daily-history operations. Each provider declares which sec_types, operations and tenors it supports. Unsupported combinations return **HTTP 501 `CAPABILITY_NOT_SUPPORTED`**.
- New Pydantic models in `app/models/volatility.py`: `VolatilitySnapshot`, `VolatilityHistory` / `VolatilityPoint` and `VolatilityStats`. **One uniform format for every provider**:
  - all IV values are **decimal fractions with 4 decimal places** (`0.2676` = 26.76 %)
  - `iv_rank` / `iv_percentile` are on a 0–100 scale
  - `implied` always lists the tenors 30/60/90 (unsupported tenors are `null`)
  - `method` states how the value was obtained
- **LSEG** implementation:
  - snapshot via the streaming FIDs `30D/60D/90D_A_IM_C/P`, history via `historical_pricing.summaries`
  - instrument resolution `<SYM>ATMIV.U` (stock/ETF/index) / `<ROOT>ATMIV` (future), with a `ric` override
  - mandatory market validation (`CLATMIV.U` is Colgate, not crude oil)
- **IBKR** implementation:
  - snapshot via streaming generic tick 106 (30 days) for stocks, ETFs, indices and front-month futures (incl. CL/NG)
  - history via `OPTION_IMPLIED_VOLATILITY` for stocks, ETFs and indices only; futures history is rejected because the provider data is unusable
- New REST endpoints:
  - `GET /volatility/{symbol}`
  - `GET /volatility/{symbol}/history` (default 365 days)
  - `GET /volatility/{symbol}/stats` (IV Rank / IV Percentile over 252 trading days by default, computed provider-agnostically in the service)
  - parameters: `sec_type` (`stock` | `etf` | `index` | `future`), `provider` and `format=csv`
- New MCP tools: `get_implied_volatility`, `get_implied_volatility_history` and `get_implied_volatility_stats`.
- New system default `default_volatility_provider` (DB-backed setting, Admin Settings dropdown), a new `volatility` capability category, and `volatility_support` in the admin provider listing.
- **BREAKING (Schwab):** `OptionQuote.implied_volatility` from Schwab is normalized from percent to fractions, and sentinels such as `-999` become `null`. After this change every IV value in the hub is a fraction.
- `PriceQuote` and `/prices/*` are **not** changed.

## Capabilities

### New Capabilities
- `underlying-implied-volatility`: Provider-agnostic snapshot, daily history and IVR/IVP stats of ATM implied volatility for stocks, ETFs, indices and futures. Covers the REST/MCP surface, uniform units and format, provider support declaration, underlying validation, and the LSEG and IBKR implementations. It also includes the Schwab option-IV unit normalization.

### Modified Capabilities
- `system-defaults`: Add `default_volatility_provider` to the settings repository, defaults API and System Defaults UI; add `volatility` to the capabilities API categories.
- `provider-capabilities-display`: Add a `Volatility` capability chip/subtitle entry for providers implementing the volatility capability.
- `response-caching`: Cache the three volatility endpoints and MCP tools with a new runtime-configurable `volatility_seconds` TTL (default 900 s, no market-closed extension). Closed history ranges reuse the daily-candle closed-range TTL. The change also adds a `volatility` clear scope and key count, and default-provider resolution via `default_volatility_provider`.

## Non-goals

- **Polygon** underlying IV. Our plan is not entitled to option snapshots (403, verified 2026-11-06), and Polygon has no IV history. If the plan is upgraded later, a chain-derived ATM IV (strike plus total-variance interpolation) can be added on the same interface; see `design.md` → Polygon (dropped).
- Schwab underlying IV. The Schwab API delivers none (verified by the user).
- IBKR futures IV history (provider data is quantized/zero and per-contract).
- Metals futures IV (GC/SI/HG): neither LSEG nor IBKR deliver it. ETF proxies (GLD, SLV) are documented.
- **Realized / historical volatility.** It was dropped because LSEG's `TR.Volatility*` fields are not entitled, and only IV is needed.
- Intraday IV streaming, volatility surfaces, per-strike skew.
- Outlier filtering for IVR (documented; open question).

## Impact

- **Code**:
  - Providers: `app/providers/base.py`, `app/providers/lseg.py`, `app/providers/ibkr.py`, `app/providers/schwab.py` (units), `app/providers/registry.py`
  - New modules: `app/models/volatility.py`, `app/services/volatility_service.py`, `app/api/routes_volatility.py`
  - Wiring: `app/main.py` (router, 422/501 mapping), `app/utils/errors.py`, `app/dependencies.py`, `app/api/mcp.py`
  - Admin backend: `app/api/routes_admin.py`, `app/api/routes_meta.py`, `app/admin/settings_repository.py`, `app/config.py`
  - Admin UI: `admin/src/types.ts`, `admin/src/pages/SettingsPage.tsx`, capability chips
- **API**:
  - Additive: three new public endpoints, three MCP tools, one new optional field in the admin defaults payload, `volatility_support` and one new key in the capabilities response. The admin cache API gains one policy field (`volatility_seconds`) and one scope (`volatility`).
  - **BREAKING**: Schwab option IV units.
- **Cache**: `app/cache.py` (policy field, resolve branches, scope, provider-default map), `app/config.py` (`CACHE_TTL_VOLATILITY_SECONDS`), settings allowlist, `admin/src/components/CacheCard.tsx`.
- **Dependencies**: None new (`refinitiv-data` and `ib_async` are already installed).
- **Entitlements**:
  - LSEG was verified on 2026-11-06 (PROD_PERM 6410). `TR.*` datagrid fields and REST pricing snapshots are **not** entitled, and the design avoids them. The `app/config.py` LSEG comment is corrected.
  - IBKR works with delayed data (`mdt=3`) on the paper account.
  - Polygon: the key is valid (previous close works), but option snapshots are not entitled (403). Out of scope.
