# 🏗️ Finnhub Provider Architecture

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        HTTP Request                              │
│   GET /companies/AAPL/news?provider=finnhub                     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FastAPI Route Handler                          │
│              routes_companies.py                                 │
│         @router.get("/companies/{symbol}/news")                 │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Service Layer                               │
│            company_service.get_company_news()                   │
│              (Orchestration & Fallback)                         │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Dependency Injection                           │
│         dependencies.py: get_news_provider()                    │
│         Returns: FinnhubProvider() instance                      │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FinnhubProvider                                │
│              (providers/finnhub.py)                              │
│                                                                   │
│  1. Check Rate Limit (Token Bucket)  ──┐                        │
│  2. Build API Request                  │                        │
│  3. Call Finnhub API (httpx)          ├─→ Error Handling       │
│  4. Parse Response                     │   - 401 Auth           │
│  5. Detect Categories                  │   - 404 Not Found      │
│  6. Parse Sentiment                    │   - 429 Rate Limit     │
│  7. Map to NewsArticle                ──┘   - Timeout          │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Finnhub API                                    │
│              https://finnhub.io/api/v1                          │
│              GET /company-news?symbol=AAPL                      │
└─────────────────────────────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   JSON Response                                  │
│  {                                                               │
│    "data": [                                                     │
│      {                                                           │
│        "id": 12345,                                             │
│        "headline": "Apple Reports Record Q4 Earnings",          │
│        "summary": "...",                                        │
│        "source": "Reuters",                                     │
│        "url": "https://...",                                    │
│        "image": "https://...",                                  │
│        "datetime": 1672758600,                                  │
│        "sentiment": {"positive": 0.85, ...}                    │
│      }                                                          │
│    ]                                                            │
│  }                                                              │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              Data Processing Pipeline                            │
│                                                                   │
│  ┌─────────────────┐    ┌──────────────────┐                    │
│  │ Category        │    │  Sentiment       │                    │
│  │ Detection       │    │  Parsing         │                    │
│  │                 │    │                  │                    │
│  │ Keyword Regex:  │    │ Extract Scores:  │                    │
│  │ • earnings      │    │ • positive       │                    │
│  │ • merger        │    │ • negative       │                    │
│  │ • product       │    │ • neutral        │                    │
│  │ • legal         │    │                  │                    │
│  │                 │    │ Fallback to      │                    │
│  │ Fallback:       │    │ Sentiment Proxy  │                    │
│  │ Use Sentiment   │    │ if no keywords   │                    │
│  └────────┬────────┘    └────────┬─────────┘                    │
│           └────────────────────┬─────────────────┘               │
│                                ▼                                 │
│              ┌──────────────────────────────┐                    │
│              │  NewsArticle Model           │                    │
│              │  (Pydantic Validation)       │                    │
│              │                              │                    │
│              │  - article_id                │                    │
│              │  - title                     │                    │
│              │  - summary                   │                    │
│              │  - published_at              │                    │
│              │  - source                    │                    │
│              │  - url                       │                    │
│              │  - category ← Detected       │                    │
│              │  - image                     │                    │
│              │  - sentiment ← Parsed        │                    │
│              └──────────────┬───────────────┘                    │
└───────────────────────────────┼─────────────────────────────────┘
                                ▼
                    ┌───────────────────────────┐
                    │   Rate Limiting Check     │
                    │   (Token Bucket)          │
                    │                           │
                    │  ┌─────────────────────┐  │
                    │  │ deque(maxlen=60)    │  │
                    │  │ Stores: timestamps  │  │
                    │  │ Window: 60 seconds  │  │
                    │  │ Capacity: 60 reqs   │  │
                    │  │ Status: OK/429      │  │
                    │  └─────────────────────┘  │
                    └───────────────┬───────────┘
                                    ▼
                    ┌───────────────────────────┐
                    │   Return Response         │
                    │                           │
                    │  List[NewsArticle]        │
                    │  with metadata:           │
                    │  - total count            │
                    │  - provider (finnhub)     │
                    │  - request_date range     │
                    │  - has_more (pagination)  │
                    └───────────────────────────┘
                                    ▼
                    ┌───────────────────────────┐
                    │   HTTP Response (200)     │
                    │                           │
                    │   JSON / CSV (format)     │
                    │   ← Back to Client        │
                    └───────────────────────────┘
```

---

## Data Flow: Category Detection

```
Article Headline + Summary
         │
         ▼
    ┌─────────────────────────────┐
    │ Check Keywords Regex        │
    │ Category: earnings          │
    │ Keywords: EARN, EPS, REV... │
    │ Status: Found? ──────────┐  │
    │                          │  │
    │ Category: merger         │  │
    │ Keywords: M&A, IPO, SPAC │  │
    │ Status: Found? ──────────┼──┼─────┐
    │                          │  │     │
    │ Category: product        │  │     │
    │ Keywords: LAUNCH, APP... │  │     │
    │ Status: Found? ──────────┼──┼─────┼─────┐
    │                          │  │     │     │
    │ Category: legal          │  │     │     │
    │ Keywords: LAWSUIT, SEC.. │  │     │     │
    │ Status: Found? ──────────┼──┼─────┼─────┼─────┐
    │                          │  │     │     │     │
    │ No Match? ───────────────┘  │     │     │     │
    │ Check Sentiment Fallback    │     │     │     │
    │ positive > 0.6? ────────────┘     │     │     │
    │ negative > 0.6? ────────────────────┘     │     │
    │                                           │     │
    │ Use Category ──────────────────────────────┘     │
    │ or NULL ─────────────────────────────────────────┘
    │
    └─────→ category: str | None
```

---

## Data Flow: Sentiment Parsing

```
Finnhub API Response:
{
  "sentiment": {
    "positive": 0.85,
    "negative": 0.05,
    "neutral": 0.10
  }
}
    │
    ▼
    ┌──────────────────────────────┐
    │ Extract Score Values         │
    │ positive, negative, neutral   │
    │ (or use None if missing)      │
    │ Type: float (0.0 - 1.0)       │
    │ Validation: sum ≈ 1.0 (soft) │
    └──────────────────────────────┘
    │
    ▼
    ┌──────────────────────────────┐
    │ NewsArticle.sentiment        │
    │ Optional[Dict[str, float]]    │
    │ Keys: positive, negative,     │
    │       neutral                 │
    │                               │
    │ Example:                       │
    │ {                             │
    │   "positive": 0.85,           │
    │   "negative": 0.05,           │
    │   "neutral": 0.10             │
    │ }                             │
    └──────────────────────────────┘
```

---

## Token Bucket Rate Limiting

```
Timeline (60 seconds):

Time: 00:00 ─ 60 capacity
       ├─ Request 1 ──→ ✅ OK (60 - 1 = 59)
       ├─ Request 2 ──→ ✅ OK (59 - 1 = 58)
       ├─ Request 3 ──→ ✅ OK (58 - 1 = 57)
       ├─ ...
       └─ Request 60 ─→ ✅ OK (1 - 1 = 0)

Time: 00:01 ─ 0 capacity (no tokens yet)
       └─ Request 61 ─→ ❌ Rate Limited (429)

Time: 00:02 ─ 2 tokens regenerate
       ├─ Request 62 ─→ ✅ OK (2 - 1 = 1)
       └─ Request 63 ─→ ✅ OK (1 - 1 = 0)

Time: 01:00 ─ Entire first minute expires
       └─ Request 64 ─→ ✅ OK (60 - 1 = 59) [WINDOW RESET]

Implementation:
┌──────────────────────────────────┐
│ deque(maxlen=60)                 │
│ Stores: [t0, t1, t2, ..., t59]   │
│ Each: Unix timestamp when called  │
│                                  │
│ Check:                           │
│ 1. Remove timestamps > 60s old    │
│ 2. Count remaining entries        │
│ 3. If count >= 60: REJECT (429)   │
│ 4. Else: ACCEPT (append time)     │
└──────────────────────────────────┘
```

---

## Error Handling Flow

```
FinnhubProvider.get_company_news()
│
├─ Check Rate Limit
│  ├─ Over limit? → raise ProviderError("429 Rate Limited")
│  └─ OK? → Continue
│
├─ Make API Request (httpx)
│  ├─ Network Error
│  │  └─ raise ProviderError("Connection timeout")
│  │
│  ├─ HTTP 401 Unauthorized
│  │  └─ raise ProviderError("Invalid API Key")
│  │
│  ├─ HTTP 404 Not Found
│  │  └─ raise DataNotFoundError("Symbol not found")
│  │
│  ├─ HTTP 429 Too Many Requests
│  │  └─ raise ProviderError("Rate limit exceeded")
│  │
│  └─ HTTP 200 OK → Continue
│
├─ Parse JSON Response
│  ├─ JSON Error
│  │  └─ raise ValueError("Invalid JSON response")
│  │
│  ├─ Missing Fields
│  │  └─ raise ValueError("Missing required fields")
│  │
│  └─ Valid JSON → Continue
│
├─ Process Articles
│  ├─ Map to NewsArticle
│  │  ├─ Validate Pydantic Model
│  │  └─ Catch ValidationError
│  │
│  ├─ Detect Category
│  │  └─ OK (always succeeds)
│  │
│  └─ Parse Sentiment
│     └─ OK (always succeeds, may be None)
│
└─ Return List[NewsArticle]
```

---

## Provider Registry: Before & After

### Before (LSEG only for news)
```python
# app/providers/registry.py
def _initialize_providers(self):
    self._providers["lseg"] = LSEGProvider()
    self._providers["ibkr"] = IBKRProvider()
    self._providers["mock"] = MockProvider()
    # News from LSEG only ↑
```

### After (Finnhub added)
```python
# app/providers/registry.py
def _initialize_providers(self):
    self._providers["lseg"] = LSEGProvider()
    self._providers["ibkr"] = IBKRProvider()
    self._providers["finnhub"] = FinnhubProvider()  ← NEW!
    self._providers["mock"] = MockProvider()
    # News now from Finnhub (default), LSEG, IBKR, or Mock
```

---

## API Endpoint: Request/Response

### Request
```
GET /companies/AAPL/news?provider=finnhub&days=7&category=earnings
Host: localhost:8000
Accept: application/json
```

### Response (200 OK)
```json
{
  "data": [
    {
      "article_id": "finnhub:12345678",
      "title": "Apple Reports Record Q4 Earnings",
      "summary": "Apple Inc. reported record-breaking financial results for Q4 2025...",
      "published_at": "2026-01-03T15:30:00Z",
      "source": "Reuters",
      "url": "https://reuters.com/technology/apple-reports-record-q4-earnings/",
      "full_text": null,
      "category": "earnings",
      "image": "https://images.reuters.com/...",
      "sentiment": {
        "positive": 0.85,
        "negative": 0.05,
        "neutral": 0.10
      }
    }
  ],
  "meta": {
    "total": 12,
    "limit": 20,
    "offset": 0,
    "has_more": false,
    "provider": "finnhub",
    "from_date": "2025-12-27",
    "to_date": "2026-01-03"
  }
}
```

### Error Response (429 Too Many Requests)
```json
{
  "error": {
    "code": "RATE_LIMIT",
    "message": "Finnhub rate limit exceeded (60 requests per minute)",
    "details": {
      "limit": 60,
      "window_seconds": 60,
      "retry_after": 15
    }
  }
}
```

---

## Configuration Hierarchy

```
Environment → Settings (config.py) → Provider Instance
    ↓
.env file
  FINNHUB_API_KEY=xxx
  FINNHUB_RATE_LIMIT_PER_MIN=60
    ↓
app/config.py (Settings class)
  FINNHUB_API_KEY: str
  FINNHUB_RATE_LIMIT_PER_MIN: int
    ↓
FinnhubProvider.__init__()
  self.api_key = settings.FINNHUB_API_KEY
  self.rate_limit = settings.FINNHUB_RATE_LIMIT_PER_MIN
    ↓
Runtime behavior
```

---

## Performance Characteristics

### Time Complexity
| Operation | Complexity | Details |
|-----------|-----------|---------|
| Rate Limit Check | O(1) | Append to deque, remove from left |
| Category Detection | O(n) | n = keywords count ≈ 16 |
| Sentiment Parsing | O(1) | Direct dictionary access |
| API Request | O(1) | Single HTTP call |
| **Total per Article** | **O(1)** | Dominated by API call (~200ms) |

### Space Complexity
| Component | Space |
|-----------|-------|
| Rate Limit Deque | O(1) - max 60 entries |
| HTTP Client | O(1) - single instance |
| **Total** | **< 1 MB** |

### Network Performance
| Scenario | Latency |
|----------|---------|
| Rate Limit Check | ~0.1ms |
| API Request | ~200-500ms (Finnhub bound) |
| Data Processing | ~50ms |
| **Total** | **~250-550ms** |

---

## Integration Testing Checklist

- [ ] Test with valid symbol (AAPL)
- [ ] Test with invalid symbol (INVALID)
- [ ] Test rate limiting (60 requests in 60 seconds)
- [ ] Test category filtering
- [ ] Test sentiment parsing
- [ ] Test without API key (401)
- [ ] Test timeout handling
- [ ] Test CSV export
- [ ] Test pagination (limit/offset)
- [ ] Test date range filtering

---

## Next Steps After API Key Setup

1. ✅ Add FINNHUB_API_KEY to .env
2. ✅ Run test_finnhub_news.py
3. ✅ Start API: `uvicorn app.main:app --reload`
4. ✅ Test endpoint: `curl http://localhost:8000/companies/AAPL/news?provider=finnhub`
5. ⭕ Monitor rate limit usage in production
6. ⭕ Consider caching for frequently requested symbols
7. ⭕ Upgrade to Premium tier if needed (>60/min)
