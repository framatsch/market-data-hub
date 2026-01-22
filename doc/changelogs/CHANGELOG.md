# Changelog

All notable changes to this project will be documented in this file.

## [2026-01-22]

### Added
- **Finnhub News Provider**: New news data provider with sentiment analysis and category detection. Configure via `FINNHUB_API_KEY` in environment variables. Set `provider=finnhub` when calling `/companies/{symbol}/news` endpoint.
  - Supports 4 news categories: earnings, merger, product, legal
  - Automatic sentiment scoring (positive, negative, neutral)
  - Rate limiting: 60 calls/minute (Token Bucket)
  - Test with: `python scripts/diagnostics/test_finnhub_news.py`

## [Previous]

- Changed: Consolidated top-level docs into the doc/ folder.
  - Moved DEPLOYMENT.md → doc/DEPLOYMENT.md
  - Moved NEWS_API_GUIDE.md → doc/NEWS_API_GUIDE.md
  - Moved MARKET_OPEN_STATUS.md → doc/MARKET_OPEN_STATUS.md
- Added: Updated Market Open Status documentation to reflect IBKR tradingHours new format parsing and dynamic exchange time zone (`timeZoneId`) handling via ZoneInfo.
- Added: Reference to scripts/diagnostics/verify_market_open_fix.py for end-to-end verification of `is_market_open`.
- Fixed: Documented that `/prices/{symbol}/last` with provider=ibkr now returns a boolean `is_market_open` (no longer null) when Contract Details provide trading hours.
