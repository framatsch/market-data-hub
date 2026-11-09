# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.0] - 2026-11-09

### Added

- Namespaced symbols with one grammar across REST, MCP and WebSocket: bare symbols
  are stocks/ETFs, `I:`/`^` are indices, `F:`/`/` futures and `O:` option ids. A
  central parser (`app/utils/symbols.py`) resolves prefix/`sec_type` conflicts and
  responses return canonical symbols.
- Per-provider symbol mapping (IBKR Index/ContFuture, LSEG `.ROOT`/`ROOTc1`,
  Schwab `$ROOT`/`/ROOT`, Polygon `I:ROOT`) with declared support sets; unsupported
  combinations answer 501 `CAPABILITY_NOT_SUPPORTED` before any provider call.
- New 403 `PROVIDER_NOT_ENTITLED` error for runtime subscription/entitlement denials
  (applied after previous-close and delayed-data fallbacks); Admin UI shows provider
  support sets.

### Changed

- **Breaking:** `symbol` in responses is canonical (`I:SPX`, `F:ES`; stocks
  unchanged); missing subscriptions answer 403 instead of 503; `.SPX`/`$SPX` input
  is rejected; index/future requests at providers without a mapping answer 501;
  cache keys changed (old entries expire).

### Fixed

- Stored credentials encrypted with another `APP_ENCRYPTION_KEY` no longer break
  provider configuration or the admin credential list; they are logged and treated
  as unconfigured.
- Schwab futures quotes are keyed by the active contract; LSEG index ATMIV records
  without a market field are handled.

## [1.2.1] - 2026-11-07

### Added

- Production `docker-compose.release.yml` (plus `env.example` and `README.md`) is
  attached to every GitHub release, pinned to the matching image tag; releases
  list their `ghcr.io/framatsch/market-data-hub` image.

### Changed

- Repository and GHCR images moved to the `framatsch` GitHub account
  (`ghcr.io/framatsch/market-data-hub`); Admin UI links updated.
- README consolidated: removed unsupported LSEG sections and verbose internals.

## [1.2.0] - 2026-11-06

### Added

- Underlying implied-volatility snapshots and daily history from LSEG and IBKR,
  plus provider-independent IV Rank/Percentile through three REST endpoints and
  three MCP tools. All underlying IV uses four-place decimal fractions; provider
  support metadata and a DB-backed default expose supported markets and tenors.
  New settings: `IBKR_IV_TIMEOUT_SECONDS` (default `10`, IV tick wait) and
  `CACHE_TTL_VOLATILITY_SECONDS` (default `900`, Redis cache for IV
  snapshots/stats/open history, no market-closed extension).
- Shared, fail-open Redis response caching for option chains and historical prices,
  including JSON/CSV HIT/MISS headers, ETag revalidation, and client bypass headers.
- Extended caching to company profiles, search, news (JSON/CSV), market status,
  and six MCP tools with forced refresh; added capability-aware keys, configurable
  TTLs, market-status transition caps, and matching Admin UI counts/clear scopes.
- Market- and bar-state-aware TTLs with runtime policy overrides, authenticated
  admin status/policy/confirmed scoped clearing APIs, and a Response Cache card
  on the Admin Settings page.
- Compose Redis service with persistent RDB snapshots, bounded LRU memory and
  internal-only networking; hermetic cache tests and isolated Compose verification.
- `schwab_cli.py`: CLI to download Schwab accounts, positions and transactions
  into the wrapped JSON format used by the Trade Sensei importer (with unit tests).

### Changed

- Removed unsupported LSEG news integration from provider capabilities, the
  public provider catalog and REST/MCP guidance. Use Finnhub, IBKR or mock for
  news; an obsolete LSEG news default is treated as unconfigured. Clear old
  `company_news` cache entries for `provider=lseg` when upgrading with Redis.
- Schwab option-chain and option-quote `implied_volatility` now uses a decimal
  fraction (`0.22345` = 22.345%), consistent with IBKR, Polygon and underlying
  IV values. Multiply by 100 for percentage display. Missing/NaN values and
  negative sentinels such as `-999` now return `null`.

### Fixed

- Normalized historical REST/MCP request date ranges to UTC before provider
  calls, fixing IBKR's naive/aware datetime subtraction error when `end` is
  omitted or timezone forms are mixed. Both channels use UTC-aware current-time
  defaults and derive a missing start from the effective end minus 30 days.
- Admin UI TypeScript and React Hooks lint failures: typed API results and errors,
  derived form defaults that preserve local edits, valid sidebar route matching,
  and OAuth polling timer cleanup.
- Resolved the `E402` lint error in `app/logging_config.py` (misplaced
  `typing` import), so `ruff check app/` passes cleanly.

### Documentation

- Updated README, provider/Finnhub/news guides and Copilot instructions for the
  LSEG news removal, underlying IV and response-cache changes; synced and
  archived the OpenSpec changes (`underlying-implied-volatility`,
  `extend-response-cache-coverage`).

## [1.1.3] - 2026-09-03

### Changed
- **Config:** Implemented dynamic versioning for the UI and API. The frontend now reads its version directly from `package.json`, and the Python backend (FastAPI and MCP server) reads it directly from `pyproject.toml` via `tomllib`.
- **Release:** Automated the `bump_version.py` skill to seamlessly handle `git push`, tag pushing, and `gh release create` to trigger Discord notifications automatically.

## [1.1.2] - 2026-09-02

### Fixed
- **Admin UI:** Configured provider credentials rendered as empty input fields instead of masked values. Two changes in 1.1.1 landed four hours apart and were never reconciled: `22aff53` made the frontend read a cleartext `value` field from `GET /api/admin/credentials`, then `2889502` hardened that endpoint back to metadata-only without touching any frontend file. The leftover `cred.value` was always `undefined` and silently collapsed to `''` via `|| ''`. Configured secrets now render as a mask, and the visibility toggle fetches plaintext on demand through the already-existing rate-limited, audit-logged `/api/admin/credentials/{provider}/{credential}/reveal` endpoint — which the frontend had never called. This supersedes the "cleartext backend transmission" approach described in the 1.1.1 notes below; the metadata-only backend posture is retained unchanged.

### Changed
- Consolidated four drifting copies of the credential TypeScript type into a single `CredentialMetadata` in `admin/src/types.ts`, corrected `provider_name` → `provider` to match the actual API response, and removed the phantom `value` field that TypeScript could not catch because `fetcher()` results are unvalidated type assertions. Added `CredentialReveal` for the reveal endpoint.

## [1.1.1] - 2026-08-14

### Fixed
- **API/MCP:** Fix service discovery on Kubernetes by adding `proxy_headers=True` to Uvicorn, ensuring `url_for` generates the correct external URL behind an Ingress.

### Added
- Admin Settings UI and Backend API (including provider test-connection endpoints and capabilities display).
- News service integration.
- **Schwab Provider** implementation (including OAuth flow and options support).
- Discord webhook support for alerts and test connections.
- Support for secure provider credentials storage via `keys.db` (including a generation script).
- Remote MCP connection support (e.g., for Claude integration) and provider overrides.
- **Regular Trading Hours (RTH):** Added `extended_hours` query parameter (default: `false`) for historical prices. Intraday intervals now automatically filter out pre/after-market data for IBKR, Polygon, and LSEG by default.
- Auto-sync background token watcher for Schwab OAuth integration.

### Changed
- **Security:** Moved all provider API keys and credentials (including Finnhub) to the secure `keys.db`, removing them from environment variables.
- Consolidated provider admin UI, integrating Schwab OAuth settings directly into `routes_admin.py`.
- Refactored Admin UI credential masking to use native browser password fields and cleartext backend transmission, removing complex "fetch-on-demand" logic.
- Gated auto-reload functionality strictly behind `APP_ENV=dev` and `RELOAD=true`.
- Refactored LSEG provider (test connections now validate session only).
- Updated CI/CD pipeline to use `devel` branch triggers and Docker GHCR tags.
- Consolidated agent memory instructions and runtime configuration documentation.
- Refactored service-layer provider access to use async context-managed registry usage paths, enabling in-flight tracking and safer provider reload/close behavior.

### Fixed
- Fixed silent fallbacks for unsupported historical data intervals across all providers (LSEG, IBKR, Polygon). Requests for unknown intervals (e.g. `4h`) now correctly fail with a `ProviderError` (HTTP 400).
- Fixed Claude remote MCP connection issues.
- Fixed Prixe provider to correctly send ticker instead of symbol.
- Fixed empty default provider dropdowns and removed custom logo in Admin UI.
- Fixed admin credential handling and log attribution.
- Resolved integration test flakiness by using mock providers for MCP tests.
- Cleaned up unused variables and linting errors across the codebase.
- Hardened admin static asset serving against path traversal and malformed path inputs (including null-byte edge cases).
- Changed admin credentials listing to metadata-only and added guarded credential reveal behavior with explicit validation, per-user rate limiting, and reveal audit context.
- Moved LSEG quote/history/news blocking operations off the event loop via thread offloading and added regression coverage.
- Improved provider registry reload safety with copy-on-write swap, deferred close semantics, and in-flight provider drain tracking.
- Fixed Schwab token persistence/watcher robustness (correct repository import, typed watcher task lifecycle, and logged fallback behavior).
- Fixed strict typing regressions and updated service tests for async context-manager based provider access.


## [1.0.0] - 2026-05-31
### Added
- Integrated **Polygon.io** provider for high-performance US stocks and options data.
- Added **Prixe** provider for real-time stock price lookup.
- Implemented `ENABLED_PROVIDERS` environment variable for selective provider loading.
- New **Startup Protocol** banner in logs for immediate visibility of active features.
- Enabled **CORS** support to allow connection from the web-based MCP Inspector.
- Comprehensive **unit test suite** with 140+ tests and over 70% coverage.
- Detailed **Provider Setup Guide** (`doc/providers-setup.md`).
- Integrated **MCP (Model Context Protocol)** directly into the FastAPI router.

### Changed
- Removed deprecated Schwab provider.
- Refactored `LSEGProvider` to use explicit date ranges for historical data.
- Isolated network-intensive integration tests from default test runs and CI.
- Updated project tools in `tools/` for the Market Data Hub structure.

### Fixed
- Improved resilience of `ProviderRegistry` against missing dependencies.
- Fixed IBKR connection hangs during test teardown.
- Corrected Pydantic model mappings for various data providers.

## [0.1.0] - 2026-05-30
### Added
- Initial project setup with FastAPI and MCP support.
- Integration with IBKR, LSEG, Schwab, and Finnhub providers.
- Basic price, company, and options endpoints.
