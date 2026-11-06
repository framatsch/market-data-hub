## Context

The hub exposes implied volatility only per option contract (`OptionQuote.implied_volatility`). There is no notion of "the IV of AAPL / SPY / ES". Consumers want the ATM IV of the underlying plus enough daily history to compute **IV Rank** and **IV Percentile** (52-week / 252 trading days).

Provider research (engram `research/underlying-implied-volatility*`):

| Provider | Underlying IV | History | Futures |
|---|---|---|---|
| LSEG | Dedicated ATMIV instruments, 30/60/90-day, call & put | Daily, > 2 years | Equity-index, grains, rates (no energy/metals) |
| IBKR | Generic tick 106 (30-day), works with delayed data | `OPTION_IMPLIED_VOLATILITY`, 2 years for STK/ETF/IND | Live tick 106 OK (incl. CL); history unusable (see IBKR Spike Findings) |
| Schwab | ❌ no IV for the underlying (verified by the user via API, 2026-11-06). ✅ IV per option contract (`volatility` in chain/quote, percent) | No | No |
| Polygon (Massive) | Per contract only (chain snapshot, Options Starter+ plan); **our plan: 403 NOT_AUTHORIZED** | No | No |

Scope of this change: **LSEG and IBKR**. Polygon is dropped (not entitled, see Polygon section). Schwab is out: its API delivers no underlying IV (verified by the user).

Current LSEG provider (`app/providers/lseg.py`):
- `LSEGProvider(BaseCompanyProvider, BasePriceProvider, BaseNewsProvider)`.
- Uses `historical_pricing.summaries`, `search`, `rd.news`.
- Reusable sync helpers: `_get_session()`, `_throttle()`, `_retry_with_backoff()`, `_is_retryable_error()`. Everything is wrapped in `asyncio.to_thread`.

Provider defaults are DB-backed per category and resolved by `ProviderRegistry._resolve_default` via `isinstance`.

## Spike Findings (LSEG, 2026-11-06)

Scripts and raw output live in `tmp/lseg_iv_spike*.py` and `tmp/lseg_iv_spike_out/` (git-ignored). Recorded CSVs become test fixtures.

**Access paths**

| Path | Result |
|---|---|
| `rd.get_data(ric, ["TR.30DAYATTHEMONEY…"])` (datagrid) | ❌ `Insufficient scope … trapi.data.get.data.read` |
| `pricing.Definition(...).get_data()` (REST snapshot) | ❌ `Insufficient scope … trapi.data.pricing.read` |
| `rd.get_data(rics, ["30D_A_IM_C", …])` (streaming snapshot) | ✅ batch-capable, unknown RIC → NaN row (no exception) |
| `historical_pricing.summaries(ric, DAILY, fields=[FIDs])` | ✅ `Date` index, `Float64`, AAPL 496 rows since 2024-11-04 |
| `TR.Volatility30D` (realized) | ❌ datagrid scope → **realized vol dropped** |
| CBOE vol indices `.VIX/.VXN/.OVX/.GVZ` | ❌ `UserNotPermission` / no data |

**FIDs on ATMIV records**: `30D_A_IM_C`, `30D_A_IM_P`, `60D_A_IM_C`, `60D_A_IM_P`, `90D_A_IM_C`, `90D_A_IM_P` (percent, call == put in all samples), plus `TRADE_DATE`, `DSPLY_NAME`, `UNDERLYING`, `INST_DESC`, `OPTIONS` and `GN_TXT16_5` (market code). Per speed guide `IMPLIEDVOL3`, values update daily (hourly for index options) and are stored for history.

**Naming (verified)**

```
.U  = OPRA (US equity / ETF / index options)       GN_TXT16_5 = OPRA
      AAPLATMIV.U  SPYATMIV.U  GLDATMIV.U  USOATMIV.U
      SPXATMIV.U   NDXATMIV.U  RUTATMIV.U  VIXATMIV.U
(no suffix) = US futures options                    GN_TXT16_5 = COMFUT | CMEG
      ESATMIV  NQATMIV  YMATMIV  CATMIV (corn)  WATMIV (wheat)  TYATMIV (10Y)
.EX = Eurex, option-series root (≠ ticker)          GN_TXT16_5 = EUREX
      SAPGATMIV.EX  STXEATMIV.EX  GDAXATMIV.EX
Not available: CL, NG, GC, SI, HG, Brent futures IV; .SPXATMIV; 1C/1W/2TY/GC/SI from the (stale) speed guide
```

**Ticker collision (critical)**: `ESATMIV.U` is *Eversource Energy* (24.13 %), not E-mini S&P (`ESATMIV`, 13.16 %). `CLATMIV.U` is Colgate, `NGATMIV.U` is NovaGold and `SOATMIV.U` is Southern Co. The suffix alone decides the market, so validation against `GN_TXT16_5` is mandatory.

**IVR/IVP feasibility**: AAPL 30-day IV, last 252 points gives current 26.76, min 16.20, max 32.31 → IVR 65.5, IVP 74.1. The history depth is sufficient.

**LSEG futures caveat**: On 2026-11-05, `ESATMIV` = 13.16 % while SPX = 20.09 % and IBKR ES = 19.84 %. `NQATMIV` = 21.89 % while NDX = 26.40 % and IBKR NQ = 31.75 %. LSEG futures ATMIV values sit noticeably below the cash-index IV. Document this and prefer `sec_type=index` for equity-index exposure.

## IBKR Spike Findings (2026-11-06)

Script: `tmp/ibkr_iv_spike.py`. Output: `tmp/ibkr_iv_spike_out/` (`report_mdt1_user_run.json`, `report_mdt3_live.json`, `H_*.csv`). Gateway: paper account, port 4002. The first attempt failed with "data farm connection broken" because the container had no outbound connectivity (VPN).

| Check | Result |
|---|---|
| Live tick 106/104, `mdt=1` | ❌ 354 / 10089 "not subscribed" (paper account without API live subscriptions) |
| Live tick 106/104, `mdt=3` (delayed) | ✅ AAPL 25.2 %, SPY 18.3 %, SPX 17.8 %, VIX 105 %, ES 18.1 %, **CL 54.1 %**; GC → None. Requires streaming `reqMktData` (snapshot + generic ticks = error 321) |
| History `OPTION_IMPLIED_VOLATILITY`, stocks/ETFs/indices | ✅ ~500 daily bars (2 years), decimal fractions; vs LSEG on overlapping days mean abs diff 0.1–0.5 pp for ETFs/indices, 0.5–3.5 pp for single names |
| History, outliers | 0–1.8 % of days deviate > 30 % from the ±5-day median (VIX 4.6 %). Single bad days hit IVR hard (QQQ IVR 100 raw vs 57 filtered); IVP is robust |
| History, futures | ❌ Not supported per IB docs, and the data proves it: ES/ZC/ZW values are quantized (multiples of √252/400 and √252/4), ES contains 0 and 12.98, ZN is all zeros, ZC/ZW are in percent instead of fractions, GC/SI/HG give "HMDS query returned no data". The data is also per-contract, so it breaks at rolls |

Implications (implemented in D10):
- Snapshot: streaming `reqMktData(c, "106", False, False)`, wait for tick 24, then `cancelMktData`. Delayed data (`mdt=3`) is enough.
- History: STK, ETF and IND only. Futures history is rejected (`CAPABILITY_NOT_SUPPORTED`) rather than returning quantized garbage.
- Live CL (and NG) IV from IBKR fills the LSEG energy gap, for snapshots only.

## Polygon (dropped, spike 2026-11-06)

Script: `tmp/polygon_iv_spike.py`. Output: `tmp/polygon_iv_spike_out/report.json`.

| Check | Result |
|---|---|
| Key validity (`/v2/aggs/ticker/{T}/prev`) | ✅ AAPL 344.17, SPY 733.00, QQQ 647.05, GLD 375.49 |
| `GET /v3/snapshot/options/{AAPL,SPY,QQQ,GLD}` | ❌ 403 `NOT_AUTHORIZED` "You are not entitled to this data. Please upgrade your plan" |
| Index chains `SPX`, `I:SPX`, `NDX`, `I:NDX`, `RUT`, `I:RUT` | ❌ 403 (ticker convention still unknown) |

Even with an upgrade (Options Starter+), Polygon only offers per-contract IV in live snapshots and **no IV history**. It could therefore never serve `/history` or `/stats`. **Decision: Polygon is out of scope.**

If revisited, the prepared approach still applies:
- chain snapshot filtered to expiries +1..+130 days and strikes ±10 % around spot
- linear strike interpolation at spot per expiry/side
- total-variance interpolation `σ_T = sqrt((σ1²T1(T2−T) + σ2²T2(T−T1)) / ((T2−T1)T))` to 30/60/90 days, with no extrapolation
- `method = "derived_from_chain"`

The prototype lives in the spike script.

## Goals / Non-Goals

**Goals:**
- One provider-agnostic contract for the ATM IV of an underlying: a snapshot and a daily history.
- Two implementations with **one uniform response format**:
  - **LSEG** for stocks, ETFs, indices and futures, plus a `ric` override (e.g. Eurex).
  - **IBKR** for stocks, ETFs, indices and futures (snapshot); history for STK/ETF/IND.
- Unit-normalized values (decimal fractions, 4 decimal places) for every provider.
- History long enough for 252-day IV Rank / IV Percentile, plus a server-side `/stats` endpoint that computes both.
- Default volatility provider selectable via system settings.
- REST and MCP exposure.

**Non-Goals:**
- Realized/historical volatility (dropped).
- Schwab underlying IV (not available via the Schwab API).
- Polygon (not entitled to option snapshots; no IV history at any plan).
- IBKR futures IV history (provider data unusable).
- Metals futures IV (GC/SI/HG: neither LSEG nor IBKR deliver it; use ETF proxies GLD/SLV).
- Changing `PriceQuote` or `/prices/*`.
- Intraday IV, surfaces, skew.

## Decisions

### D1 — New capability `BaseVolatilityProvider`

```
BaseVolatilityProvider  (new)
  ├─ get_implied_volatility(symbol, sec_type, ric=None) -> VolatilitySnapshot
  ├─ get_implied_volatility_history(symbol, start, end, tenor_days=30,
  │                                 sec_type, ric=None) -> VolatilityHistory
  └─ test_connection()
```

Underlying IV is its own analytics category (LSEG has it without being an options provider). The registry, capabilities API and defaults treat it as `volatility`.

Providers differ in what they can deliver, so the base class declares it explicitly:

```
class BaseVolatilityProvider(ABC):
    volatility_sec_types: frozenset[str]          # snapshot support
    volatility_history_sec_types: frozenset[str]  # history (and therefore stats) support
    volatility_tenors: frozenset[int]             # tenors with real values
```

| Provider | snapshot sec_types | history sec_types | tenors |
|---|---|---|---|
| LSEG | stock, etf, index, future | stock, etf, index, future | 30, 60, 90 |
| IBKR | stock, etf, index, future | stock, etf, index | 30 |

`VolatilityService` checks these sets **before** calling the provider. An unsupported combination raises `CapabilityNotSupportedError` (D5). Admin `GET /api/admin/providers` exposes the sets as `volatility_support` so the UI and clients can see why a default might not serve `/history`.

Alternatives rejected:
- **Field on `PriceQuote`**: forces IV on every quote, mixes tenors and has no history.
- **Method on `BaseOptionsProvider`**: LSEG would have to implement fake option-chain methods.

### D2 — Data model and units

```
ImpliedVolatilityTenor
  tenor_days: int                 # 30 | 60 | 90 — always all three, in this order
  iv_call: Decimal | None         # decimal fraction, 0.2676 == 26.76 %
  iv_put:  Decimal | None
  iv:      Decimal | None         # mean of available call/put; or the provider's combined value

VolatilitySnapshot
  symbol: str
  sec_type: Literal["stock", "etf", "index", "future"]
  method: Literal["provider_atm_index", "provider_model_30d"]
  source_instrument: str          # LSEG "AAPLATMIV.U" | IBKR "CLZ6" / "AAPL"
  underlying: str | None          # e.g. "AAPL", ".SPX", "ES"
  underlying_name: str | None     # e.g. "APPLE INC", "COLGATE PALMOLIVE"
  market: str | None              # LSEG GN_TXT16_5 / IBKR exchange
  as_of: date | None              # date of the underlying IV value
  implied: list[ImpliedVolatilityTenor]
  provider: str

VolatilityPoint
  date: date
  iv_call: Decimal | None
  iv_put:  Decimal | None
  iv:      Decimal | None

VolatilityHistory
  symbol, sec_type, source_instrument, tenor_days, provider
  points: list[VolatilityPoint]   # ascending by date
```

**Unit decision: decimal fraction (`0.20`), not percent (`20`).**

| Criterion | Fraction `0.2676` | Percent `26.76` |
|---|---|---|
| Native provider format | IBKR ✅, Polygon ✅ | LSEG, Schwab |
| Direct use in formulas (Black-Scholes, expected move `S·σ·√t`, variance `σ²`) | ✅ no conversion | ✗ ÷100 everywhere, a classic factor-100 bug |
| Libraries (py_vollib, QuantLib, mibian partly) | ✅ expect fractions | ✗ |
| Consistency with the rest of the API (returns, `delta`) | ✅ | ✗ |
| Human readability | needs `× 100` for display | ✅ |

Readability is a presentation concern (UI/CSV formatting). The API contract favours calculation safety. Therefore:
- **All IV values are fractions** (`Decimal`, quantized to **4 decimal places** = 0.01 percentage point, `ROUND_HALF_UP`). This applies to every provider, snapshot, history point and `/stats` `current`/`min`/`max`.
- **`iv_rank` and `iv_percentile` are 0–100.** They are ranks, not volatilities, and 0–100 is the universal market convention (IVR 65 = 65th % of the range). The field names make the difference explicit.
- Provider conversions: LSEG `÷ 100`, IBKR as is.
- **Uniform shape**: `implied` always contains 30, 60 and 90 (in that order). A tenor the provider cannot deliver has all three values `null` (IBKR: only 30d). If a provider only gives one combined value (IBKR), `iv` is set and `iv_call`/`iv_put` are `null`.
- `method` tells consumers how comparable values are. LSEG uses interpolated constant-maturity ATM values; IBKR uses its own 30-day model.
- Realized volatility was removed from the model.

**Existing inconsistency fixed in this change (BREAKING for Schwab):** `OptionQuote.implied_volatility` from Schwab is currently percent (`22.3`), while IBKR and Polygon use fractions. Schwab values are normalized to fractions (`÷ 100`), and the Schwab missing-value sentinel `-999` maps to `null`. After this change every IV in the hub (underlying and per contract) is a fraction.

### D3 — LSEG instrument resolution and validation

```
sec_type=stock|etf|index :  f"{SYM}ATMIV.U"     SYM upper-cased, leading "^" and "." stripped (SPX, NDX, RUT, VIX)
sec_type=future          :  f"{ROOT}ATMIV"      ROOT = LSEG futures-options root (ES, NQ, YM, C, W, TY)
ric=<explicit>           :  verbatim            Eurex (SAPGATMIV.EX, STXEATMIV.EX, GDAXATMIV.EX) and any other venue
```

Expected market codes (validated after fetch, `GN_TXT16_5` stripped and upper-cased):

| sec_type | accepted `market` |
|---|---|
| stock, etf, index | `OPRA` |
| future | `COMFUT`, `CMEG` |
| `ric=` override | not validated (caller is explicit), but `market` is returned |

A mismatch raises `DataValidationError` (HTTP 422) with `details={"expected_market": [...], "market": ..., "underlying_name": ...}`. This is how `CL` + `sec_type=stock` (Colgate) is distinguished from crude oil, and why `ES` + `sec_type=stock` yields Eversource instead of silently answering a futures question.

Resolution is pure string building with no `search` call.

### D4 — LSEG data access

- **Snapshot**: `rd.get_data(ric, IV_FIDS + META_FIDS)`.
  - `IV_FIDS` = `30D_A_IM_C, 30D_A_IM_P, 60D_A_IM_C, 60D_A_IM_P, 90D_A_IM_C, 90D_A_IM_P`.
  - `META_FIDS` = `TRADE_DATE, DSPLY_NAME, UNDERLYING, INST_DESC, GN_TXT16_5`.
  - This uses the streaming-snapshot path that is entitled. `pricing.Definition().get_data()` must **not** be used because the REST snapshot is not entitled.
- **History**: `historical_pricing.summaries.Definition(universe=ric, interval=DAILY, start, end, fields=[C, P for tenor])`.
  - The result has a `Date` index. Rows where both values are NaN are dropped, and the rest is sorted ascending.
  - Always pass explicit `fields`. Without them LSEG adds an unrelated `IMP_VOLT` column.
- Execution follows the existing pattern: sync function, `asyncio.to_thread`, `_get_session()`, `_throttle()`, `_retry_with_backoff()`.
- **No provider-level cache.** Caching is done by the shared Redis response cache (D9), in line with the `response-caching` goal of "no second cache mechanism".
- Correct the misleading LSEG comment in `app/config.py`. It should say: streaming pricing works; REST pricing snapshots and the datagrid (`TR.*`) are not entitled.

### D5 — Error mapping

| Situation | Error | HTTP |
|---|---|---|
| Snapshot row has all IV FIDs NaN (unknown RIC behaves the same, no exception) | `DataNotFoundError("ImpliedVolatility", ric, details={"reason": "no_iv_data"})` | 404 |
| History returns no rows / only NaN | `DataNotFoundError(..., details={"reason": "no_iv_history"})` | 404 |
| `market` does not match `sec_type` | `DataValidationError` (see D3) | 422 |
| `UserNotPermission` / `Insufficient scope` in error text | `ProviderError(code="PROVIDER_NOT_AVAILABLE", details={"reason": "not_entitled", "instrument": ric})` | 503 |
| Transient (timeout/connection/5xx) | existing retry → `ProviderConnectionError` | 503 |
| `tenor_days ∉ {30,60,90}`, `start > end`, unknown `sec_type` | FastAPI 422 / `DataValidationError` | 422 |
| Provider does not support the `sec_type` / operation / tenor (D1 sets; e.g. IBKR futures history, IBKR `tenor_days=60`) | new `CapabilityNotSupportedError` → code `CAPABILITY_NOT_SUPPORTED`, `details={"provider", "operation", "sec_type", "tenor_days", "supported": [...]}` | 501 |
| IBKR tick 24 not received within the timeout | `DataNotFoundError(details={"reason": "no_iv_data"})` | 404 |
| IBKR 354 / 10089 (not subscribed), even after the delayed fallback | `ProviderError(code="PROVIDER_NOT_AVAILABLE", details={"reason": "not_entitled"})` | 503 |

`app/main.py`'s `app_error_handler` currently maps `DATA_VALIDATION_ERROR` to 500 by default. Add it to the 4xx mapping (422) and add `CAPABILITY_NOT_SUPPORTED` → 501 as part of this change.

### D6 — Registry, defaults and capabilities

```
ProviderRegistry
  default_volatility_provider: str | None          (new)
  _apply_default_settings → _resolve_default(..., BaseVolatilityProvider)
  get_volatility_provider(name) / use_volatility_provider(name)

SettingsRepository.SETTINGS_ALLOWLIST += "default_volatility_provider"
DEFAULT_PROVIDER_FALLBACKS["default_volatility_provider"] = None
routes_admin: SystemDefaultsUpdate, _system_defaults(), _provider_capabilities() → "volatility",
              PROVIDER_CAPABILITIES["lseg"] += "volatility", /settings/capabilities → "volatility"
routes_meta /providers: defaults["volatility"], available["volatility"]
Admin UI: SettingsPage "Default Volatility Provider"; types.ts; chips via capabilityLabel()
```

### D7 — API surface

```
GET /volatility/{symbol}
    ?sec_type=stock|etf|index|future   (default stock)
    &ric=<override> &provider=<name> &format=json|csv
  → VolatilitySnapshot

GET /volatility/{symbol}/history
    ?start=YYYY-MM-DD   (default: end − 365 days → ≥ 252 trading days for IVR/IVP)
    &end=YYYY-MM-DD     (default: today)
    &tenor_days=30|60|90 (default 30)
    &sec_type &ric &provider &format
  → VolatilityHistory

GET /volatility/{symbol}/stats
    ?window=252          (trading-day points, 20..756, default 252)
    &tenor_days=30|60|90 (default 30)
    &sec_type &ric &provider &format
  → VolatilityStats

MCP: get_implied_volatility, get_implied_volatility_history, get_implied_volatility_stats
```

`VolatilityService` mirrors `PriceService` (`registry.use_volatility_provider`, structlog provider binding).

### D8 — IV Rank / IV Percentile in the service layer

```
VolatilityStats
  symbol, sec_type, source_instrument, tenor_days, provider
  window: int                 # requested points
  window_points: int          # points actually used (≤ window)
  window_start, window_end: date
  current: Decimal            # last point's iv (fraction)
  min, max: Decimal           # over the window, incl. current
  iv_rank: Decimal | None     # (current − min) / (max − min) × 100, None if max == min
  iv_percentile: Decimal      # share of window points (excl. current) strictly below current × 100
```

- The service calls `get_implied_volatility_history` with `start = end − ceil(window × 365 / 252) − 14 days` (buffer for holidays). It then takes the last `window` points by date.
- `current`, `min` and `max` are fractions with 4 dp, like every IV value (D2). `iv_rank` and `iv_percentile` are 0–100 with 2 dp. All rounding uses `ROUND_HALF_UP`.
- The service first checks `volatility_history_sec_types`. IBKR futures and IBKR `tenor_days ≠ 30` → 501 `CAPABILITY_NOT_SUPPORTED`.
- Fewer than 20 usable points → `DataNotFoundError(details={"reason": "insufficient_history", "points": n})` (404).
- **Provider-agnostic**: lives in `VolatilityService`, so IBKR/others get stats for free once they implement history.
- **No outlier filtering in v1**. It is documented that IVR (min/max-based) is sensitive to single bad prints and IVP is robust. The IBKR spike showed that this matters (QQQ IVR 100 vs 57). Revisit when IBKR is added.
- Alternative (client-side computation only) was rejected. Every consumer, including MCP agents, would reimplement the same arithmetic.

### D9 — Response caching (Redis, `response-caching` capability)

**How often IV changes** (from the LSEG spike `TRADE_DATE`/`TRDTIM_1` values, sampled during the US session on 2026-11-06):

| Source | Update cadence |
|---|---|
| LSEG `.U` stocks/ETFs, ES/NQ futures, Eurex single stocks | once per day, after the close (settlement-based); `TRADE_DATE` = previous day |
| LSEG `.U` indices (SPX, NDX, RUT, VIX), YM/C/W/TY, Eurex indices | intraday, roughly hourly (SPX moved 17.71 → 17.75 within an hour) |
| IBKR tick 106 | live (delayed 15 min with `mdt=3`) |
| Daily history (all) | one new point per day; past points are immutable |

**Policy**

| Route key | Condition | TTL | Market-closed extension |
|---|---|---|---|
| `volatility:snapshot` (`GET /volatility/{symbol}`) | always | `volatility_seconds` (default **900 s**) | **no** |
| `volatility:history` | `end` before yesterday 00:00 ET (same closed-range rule as `1d` candles) | `historical_closed_seconds` (7 d) | n/a |
| `volatility:history` | open range (no `end`, or `end` ≥ yesterday 00:00 ET) | `volatility_seconds` | **no** |
| `volatility:stats` | always (the window ends today) | `volatility_seconds` | **no** |

- **Why not the daily-candle open-bar TTL (300 s)?** A forming candle changes with every trade. IV from LSEG changes at most hourly (indices) or daily (stocks). 300 s would refetch identical data 12× per hour.
- **Why 900 s and not 3600 s?** It equals the option-chain TTL (also options-derived data). It is fresh enough for hourly index updates and still reasonable for IBKR live IV. Admins can raise it in the Admin UI for LSEG-only setups.
- **Why no market-closed extension?** The daily stock/ETF value is published *after* the close. With the extension, a request at 16:35 ET could pin the pre-update value until 09:30 the next day. Without it, overnight requests refetch at most every 15 min, which is negligible load.
- **Closed history** reuses the `1d` candle rule and `historical_closed_seconds`, as the user asked ("same value as daily candles"). This covers the large IVR/IVP backfills.

**Keys and plumbing** (reuses `app/cache.py`, no new mechanism)

```
HTTP  @cache(expire=…, key="volatility:snapshot")  mdh:volatility:snapshot:AAPL:provider=lseg&sec_type=stock
      @cache(expire=…, key="volatility:history")   mdh:volatility:history:AAPL:end=…&provider=lseg&start=…&tenor_days=30
      @cache(expire=…, key="volatility:stats")     mdh:volatility:stats:AAPL:provider=lseg&tenor_days=30&window=252
MCP   cached_call("volatility:…", …, refresh=…)    same keys + channel=mcp
```

- `_compose_key` provider defaulting: `volatility:*` → `registry.default_volatility_provider`.
- `CachePolicyValues.volatility_seconds`, env `CACHE_TTL_VOLATILITY_SECONDS=900`, stored key `cache_ttl_volatility_seconds` (settings allowlist).
- `CachePolicy.resolve()`: add the volatility branches *before* the market-closed extension block, so the extension never applies to them.
- `CacheScope` / `_PATTERNS`: new scope `volatility` → `mdh:volatility:*`, counted in `cache_status()`.
- Admin UI `CacheCard`: new TTL field "Implied volatility" and the new scope in the clear dialog. The extension-switch note lists option chains and historical prices only (unchanged).
- `/stats` is cached separately, because the service calls the provider history directly and does not go through the HTTP history cache.
- `ric` is a declared query parameter, so it is part of the key automatically.

Alternative rejected: reusing `historical_open_bar_seconds` for open IV ranges. It couples IV freshness to chart freshness, and changing one would silently change the other.

The policy is route-based, not provider-based. IBKR (live/delayed) snapshots use the same 900 s as LSEG. That is acceptable for an IV level and avoids hammering IBKR, which needs a streaming subscription and several seconds of waiting per call. `CapabilityNotSupportedError` responses are errors and therefore never cached.

### D10 — IBKR implementation

```
IBKRProvider(… , BaseVolatilityProvider)
  volatility_sec_types         = {stock, etf, index, future}
  volatility_history_sec_types = {stock, etf, index}
  volatility_tenors            = {30}
```

**Contract resolution** (explicit secType, so no ticker collisions are possible):

| sec_type | Contract |
|---|---|
| stock, etf | `Stock(SYM, "SMART", "USD")` |
| index | `Index(SYM, exchange)` via `_get_index_exchange`. The mapping must be corrected: `RUT → RUSSELL` (spike), `NDX → NASDAQ`, `SPX`/`VIX → CBOE` |
| future | front month: `reqContractDetails(Future(ROOT, exchange))`, nearest contract with `lastTradeDateOrContractMonth ≥ today + 7 days`, to avoid expiry-week distortion. The exchange comes from a built-in root map: ES/NQ/RTY → CME, YM/ZC/ZW/ZS/ZN/ZB → CBOT, CL/NG/RB/HO → NYMEX, GC/SI/HG → COMEX. Unknown roots try `Future(ROOT)` without an exchange and need exactly one exchange, otherwise 422 |

`source_instrument` = `localSymbol` (`AAPL`, `SPX`, `CLZ6`), `underlying_name` = contract details `longName`, `market` = `primaryExchange or exchange`.

**Snapshot:**
- Set the market data type to the configured IBKR type (default 3 = delayed). On 354/10089 with type 1, retry once with 3, mirroring `IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR`.
- Request `reqMktData(c, "106", snapshot=False)` and wait until `ticker.impliedVolatility` is a finite value > 0, at most `IBKR_IV_TIMEOUT_SECONDS` (new setting, default 10). Then always call `cancelMktData`.
- Fill tenor 30 with `iv` = value (4 dp), `iv_call`/`iv_put` = `null`. Tenors 60 and 90 are all `null`.
- `as_of` = the date of `ticker.time` (exchange tz), `method = "provider_model_30d"`.
- **Important:** do not use `_get_tickers_snapshot()` (snapshot mode, error 321 with generic ticks).

**History:**
- Use `reqHistoricalDataAsync(c, endDateTime, durationStr, "1 day", "OPTION_IMPLIED_VOLATILITY", useRTH=True)`.
  - `endDateTime` = `""` when `end` ≥ today, else `end` 23:59:59 US/Eastern.
  - `durationStr` = `"{days} D"` up to 365 days, else `"{ceil(days/365)} Y"`. Then filter to `[start, end]`.
- Point `iv` = bar `close` (4 dp), with `iv_call`/`iv_put` = `null`.
- Drop bars with `close ≤ 0`.
- Futures, and `tenor_days ≠ 30`, raise `CapabilityNotSupportedError`.
- Timeout → `ProviderTimeoutError` (503). "HMDS query returned no data" → 404 `no_iv_history`.

Connection handling follows the existing `_ensure_connection()` / `_disconnect()` pattern.

## Risks / Trade-offs

- **[Ticker collisions between OPRA and futures roots]** → D3 market validation, plus `underlying_name` in every response.
- **[End-of-day data]** Values are daily (hourly for index options), and `as_of` exposes the trade date. Docs must not call it "real-time IV".
- **[Stale speed guide]** Several documented RICs are empty (GCATMIV, SIATMIV, 1CATMIV …). Only spike-verified roots are documented, and the rest goes through `ric=`.
- **[No metals futures IV; energy only as an IBKR snapshot]** → IBKR covers CL/NG snapshots; ETF proxies (USO, UNG, GLD, SLV) are documented for history/IVR.
- **[Provider values are not identical]** IBKR's 30-day model and the LSEG interpolated ATM indices differ by about 0.1–0.5 pp (ETFs/indices) and more for single names. `method` and `provider` are always in the response. IVR/IVP should be computed with one provider consistently, which `/stats` does (single provider per call).
- **[IBKR history outliers]** affect IVR (min/max). No filtering in v1; documented. See Open Questions.
- **[IBKR snapshot latency]** A streaming subscription plus up to 10 s wait per uncached call. Mitigated by the 900 s cache and the timeout setting.
- **[Schwab IV unit change is BREAKING]** Consumers of Schwab option chains/quotes must multiply by 100 for display. Called out in the CHANGELOG.
- **[Streaming dependency]** The snapshot relies on the WebSocket streaming path. If LSEG changes entitlements, failures surface as 503 `not_entitled`.
- **[Stale cached IV after the evening publish]** → no market-closed extension for volatility routes; 900 s TTL. Clients may send `Cache-Control: no-cache`, and MCP tools may pass `refresh: true`.

## Migration Plan

Additive, except the Schwab option-IV unit change (BREAKING, CHANGELOG). `default_volatility_provider` starts as `None`. Admins select LSEG or IBKR in Settings. To roll back, revert the change; older versions ignore the extra settings rows.

## Open Questions

- ~~Server-side IVR/IVP~~ → decided: yes, D8.
- ~~IBKR as second provider~~ → included in this change (D10).
- ~~Polygon~~ → dropped: option snapshots not entitled (403), and no IV history at any plan.
- ~~Unit format~~ → fractions with 4 dp for all IV values; IVR/IVP 0–100 (D2).
- Built-in mapping for common Eurex names (DAX → `GDAX`, Euro Stoxx 50 → `STXE`, SAP → `SAPG`), or keep `ric=` only?
- Outlier handling for IVR (e.g. a median filter) for IBKR history? IVP is robust; IVR is not (QQQ 100 vs 57 in the spike).
