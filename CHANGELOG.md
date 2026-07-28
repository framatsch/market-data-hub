# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Admin Settings UI and Backend API (including provider test-connection endpoints and capabilities display).
- News service integration.
- **Schwab Provider** implementation (including OAuth flow and options support).
- Discord webhook support for alerts and test connections.
- Support for secure provider credentials storage via `keys.db` (including a generation script).
- Remote MCP connection support (e.g., for Claude integration) and provider overrides.
- **Regular Trading Hours (RTH):** Added `extended_hours` query parameter (default: `false`) for historical prices. Intraday intervals now automatically filter out pre/after-market data for IBKR, Polygon, and LSEG by default.

### Changed
- **Security:** Moved all provider API keys and credentials (including Finnhub) to the secure `keys.db`, removing them from environment variables.
- Consolidated provider admin UI and added favicons.
- Gated auto-reload functionality strictly behind `APP_ENV=dev` and `RELOAD=true`.
- Refactored LSEG provider (test connections now validate session only).
- Updated CI/CD pipeline to use `devel` branch triggers and Docker GHCR tags.
- Consolidated agent memory instructions and runtime configuration documentation.

### Fixed
- Fixed silent fallbacks for unsupported historical data intervals across all providers (LSEG, IBKR, Polygon). Requests for unknown intervals (e.g. `4h`) now correctly fail with a `ProviderError` (HTTP 400).
- Fixed Claude remote MCP connection issues.
- Fixed Prixe provider to correctly send ticker instead of symbol.
- Fixed empty default provider dropdowns and removed custom logo in Admin UI.
- Fixed admin credential handling and log attribution.
- Resolved integration test flakiness by using mock providers for MCP tests.
- Cleaned up unused variables and linting errors across the codebase.


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
