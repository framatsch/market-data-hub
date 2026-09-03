# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.3] - 2026-09-03

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
