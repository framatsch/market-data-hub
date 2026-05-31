# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
