# 📰 Company News API - Quick Start Guide

## Overview

The Company News API fetches company news articles from multiple data providers:
- **Mock Provider** (✅ Works immediately - no setup)
- **LSEG (Refinitiv)** (requires permission scope)
- **IBKR (Interactive Brokers)** (requires TWS/Gateway connection)

## Quick Start (Using Mock Provider)

### 1. Start the API

```bash
cd /home/fscheffold/private/market-data-hub
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Test the Endpoint

```bash
# Get all AAPL news (default: last 30 days)
curl "http://localhost:8000/companies/AAPL/news?provider=mock" | jq .

# View as CSV
curl "http://localhost:8000/companies/AAPL/news?provider=mock&format=csv"

# With filters
curl "http://localhost:8000/companies/AAPL/news?provider=mock&days=7&category=earnings"

# View Swagger UI
# Open in browser: http://localhost:8000/docs
```

## API Endpoint

```
GET /companies/{symbol}/news
```

### Path Parameters

| Parameter | Type   | Required | Example | Description |
|-----------|--------|----------|---------|-------------|
| `symbol`  | string | Yes      | AAPL    | Stock ticker symbol |

### Query Parameters

| Parameter    | Type     | Default | Range | Description |
|--------------|----------|---------|-------|-------------|
| `provider`   | string   | mock    | mock, lseg, ibkr | Data provider |
| `days`       | integer  | 30      | 1-365 | Last N days of news |
| `from_date`  | string   | -       | YYYY-MM-DD | Start date (overrides days) |
| `to_date`    | string   | today   | YYYY-MM-DD | End date |
| `category`   | string   | -       | earnings, product, merger, legal | Filter by category |
| `limit`      | integer  | 20      | 1-100 | Articles per page |
| `offset`     | integer  | 0       | ≥0 | Pagination offset |
| `format`     | string   | json    | json, csv | Response format |
| `language`   | string   | en      | en, de, etc | Language |

### Response (Success)

```json
{
  "data": [
    {
      "article_id": "mock:aapl:001",
      "title": "Apple Reports Record Q4 Earnings",
      "summary": "Apple Inc. announced record-breaking quarterly earnings...",
      "published_at": "2026-01-03T00:00:00Z",
      "source": "Reuters",
      "url": "https://www.reuters.com/tech/apple-earnings-2026",
      "full_text": null,
      "category": "earnings"
    }
  ],
  "meta": {
    "total": 5,
    "limit": 20,
    "offset": 0,
    "has_more": false,
    "provider": "mock",
    "from_date": "2025-12-05",
    "to_date": "2026-01-04"
  }
}
```

### Response (Error)

```json
{
  "error": {
    "code": "DATA_NOT_FOUND",
    "message": "Ticker 'INVALID' not found",
    "details": {}
  }
}
```

## Example Requests

### Get AAPL earnings announcements (last 30 days)
```bash
curl "http://localhost:8000/companies/AAPL/news?provider=mock&category=earnings"
```

### Get MSFT news with pagination
```bash
curl "http://localhost:8000/companies/MSFT/news?provider=mock&limit=10&offset=0"
```

### Export news as CSV
```bash
curl "http://localhost:8000/companies/AAPL/news?provider=mock&format=csv" > aapl_news.csv
```

### Get news from specific date range
```bash
curl "http://localhost:8000/companies/GOOGL/news?provider=mock&from_date=2025-12-01&to_date=2026-01-04"
```

### Get news in German
```bash
curl "http://localhost:8000/companies/AAPL/news?provider=mock&language=de"
```

## Available Symbols (Mock Provider)

| Symbol | Articles | Categories | Status |
|--------|----------|------------|--------|
| AAPL   | 5        | earnings, product, merger, legal | ✅ Working |
| MSFT   | 2        | product, merger | ✅ Working |
| GOOGL  | 1        | product | ✅ Working |

## Testing

### Run Full Test Suite

```bash
# Make executable (one time)
chmod +x /home/fscheffold/private/market-data-hub/scripts/test_news_api.sh

# Run all tests
/home/fscheffold/private/market-data-hub/scripts/test_news_api.sh
```

This runs 10 comprehensive tests:
1. ✅ Basic news request
2. ✅ Days filter
3. ✅ Category filter
4. ✅ Pagination
5. ✅ CSV export
6. ✅ Multiple symbols
7. ✅ Invalid symbol error
8. ✅ Provider list
9. ✅ Limit parameter
10. ✅ Offset parameter

### Run Individual Tests

```bash
# Test 1: Basic news
curl -s http://localhost:8000/companies/AAPL/news?provider=mock | jq .

# Test 2: Category filter
curl -s http://localhost:8000/companies/AAPL/news?provider=mock&category=earnings | jq .

# Test 3: Error handling
curl -s http://localhost:8000/companies/INVALID/news?provider=mock | jq .

# Test 4: Provider list
curl -s http://localhost:8000/providers | jq '.news'

# Test 5: CSV export
curl -s http://localhost:8000/companies/AAPL/news?provider=mock&format=csv | head -5
```

## Provider Setup (Optional)

### LSEG (Refinitiv) Setup

**Current Status:** ⚠️ Permission Required

To use the LSEG provider:

1. Contact LSEG Support
2. Request scope: `trapi.data.news.read`
3. Provide LSEG credentials:
   - `LSEG_APP_KEY` - Application API key
   - `LSEG_USERNAME` - Platform username
   - `LSEG_PASSWORD` - Platform password

4. Test once approved:
```bash
curl "http://localhost:8000/companies/AAPL/news?provider=lseg"
```

### IBKR (Interactive Brokers) Setup

**Current Status:** ⚠️ Requires TWS Setup

To use the IBKR provider:

1. Start Interactive Brokers Trader Workstation (TWS) or IB Gateway
2. Enable API in settings:
   - File → Global Configuration
   - API → Enable "Allow connections"
3. Restart on port 4002 (Gateway) or 7497 (TWS Paper)
4. Test once running:
```bash
curl "http://localhost:8000/companies/AAPL/news?provider=ibkr"
```

## Features

### Date Filtering

Automatic date range logic:
- `days` parameter takes priority
- Falls back to `from_date` / `to_date` if provided
- Default is last 30 days

```bash
# Last 7 days
curl ".../companies/AAPL/news?days=7"

# Specific range
curl ".../companies/AAPL/news?from_date=2025-12-01&to_date=2026-01-04"
```

### Category Filtering

News articles are automatically categorized:
- **earnings** - Earnings announcements, guidance
- **product** - Product launches, releases
- **merger** - Mergers, acquisitions
- **legal** - Lawsuits, regulatory actions

```bash
# Get only earnings
curl ".../companies/AAPL/news?category=earnings"
```

### Pagination

Efficiently navigate through large result sets:

```bash
# Get articles 10-20
curl ".../companies/AAPL/news?limit=10&offset=10"
```

Metadata includes `has_more` flag to detect end of results:
```json
{
  "meta": {
    "total": 50,
    "limit": 10,
    "offset": 10,
    "has_more": true,
    "provider": "mock"
  }
}
```

### CSV Export

Export results as CSV for Excel/data analysis:

```bash
# Save to file
curl ".../companies/AAPL/news?format=csv" > articles.csv

# View first 5 rows
head -5 articles.csv
```

## Architecture

```
GET /companies/{symbol}/news
           ↓
    FastAPI Router
           ↓
   NewsProviderDependency
           ↓
    Provider Registry
    ├── Mock (Always works)
    ├── LSEG (requires auth)
    └── IBKR (requires connection)
           ↓
   Provider Implementation
           ↓
   Response Model (Pydantic)
           ↓
   JSON / CSV Response
```

### File Locations

```
app/
├── api/
│   └── routes_companies.py      # GET /companies/{symbol}/news endpoint
├── models/
│   └── news.py                  # NewsArticle, NewsResponse models
├── providers/
│   ├── base.py                  # BaseNewsProvider abstract class
│   ├── mock_news.py             # MockNewsProvider (test data)
│   ├── lseg.py                  # LSEGProvider.get_company_news()
│   ├── ibkr.py                  # IBKRProvider.get_company_news()
│   └── registry.py              # Provider registration
├── services/
│   └── company_service.py       # News service layer (orchestration)
└── dependencies.py              # Dependency injection (get_news_provider)

scripts/
└── test_news_api.sh            # Automated test suite (10 tests)
```

## Troubleshooting

### Issue: "Connection refused" when using LSEG

**Cause:** LSEG session not initialized
**Solution:** Use mock provider instead, or contact LSEG for permission

### Issue: "Insufficient scope: trapi.data.news.read"

**Cause:** LSEG account lacks permission
**Solution:** Contact LSEG support to request scope

### Issue: IBKR provider returns no data

**Cause:** TWS/Gateway not running
**Solution:** Start TWS and enable API connections

### Issue: "Ticker not found" error

**Cause:** Invalid symbol (only AAPL, MSFT, GOOGL in mock)
**Solution:** Use valid symbols or add to MockNewsProvider

## Development

### Add More Mock Data

Edit `app/providers/mock_news.py`:

```python
MOCK_NEWS_DB = {
    "TSLA": [
        NewsArticle(
            article_id="mock:tsla:001",
            title="Tesla Q4 Production Report",
            # ... more fields
        )
    ]
}
```

### Implement New Provider

1. Create provider in `app/providers/new_provider.py`
2. Inherit from `BaseNewsProvider`
3. Implement `get_company_news()` method
4. Register in `app/providers/registry.py`

```python
class NewProvider(BaseNewsProvider):
    async def get_company_news(self, symbol: str, ...) -> NewsResponse:
        # Implementation
        pass
```

## Support

For questions or issues:
- Check [specs/04.prompt.md](../../specs/04.prompt.md) for requirements
- View test results: `/home/fscheffold/private/market-data-hub/scripts/test_news_api.sh`
- Review code: [app/providers/mock_news.py](../../app/providers/mock_news.py)
