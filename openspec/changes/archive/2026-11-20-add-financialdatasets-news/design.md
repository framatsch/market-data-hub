## Context

The pinned OpenAPI copy (`tests/fixtures/financialdatasets/openapi.json`, 17 November 2026) and the docs page (checked 19 November 2026) describe the endpoint identically:

| Item | Value |
|---|---|
| Request | `GET /news`, header `X-API-KEY` |
| `ticker` | string; docs: required for company news; schema: optional, omitted = broad market news |
| `limit` | integer, default 5, maximum 10; total across all pages, not a page size |
| `cursor` | opaque, only via `next_page_url`; overrides all other parameters |
| Response | `{news: [{ticker, title, source, date (YYYY-MM-DD), url}], next_page_url?}` |
| Errors | 400, 401, 402, 404 (shared error schemas) |

The schema documents no article id, time of day, summary, image, sentiment or date filter. Live responses send a timestamp in `date` (see verification below). The MDH news contract (`BaseNewsProvider.get_company_news`) passes `from_date`, `to_date`, `limit` (≤ 100), `offset`, `language` and `category`, and `NewsArticle` requires `article_id`, `title`, `summary`, `published_at`, `source`, `url`.

## Goals / Non-Goals

**Goals:**
- Recent company news from Financial Datasets through the existing endpoint, MCP tool and response shape.
- One request per uncached call, inside the existing request budget.

**Non-Goals:**
- Broad market news, deeper history than the 10 most recent articles, article bodies, sentiment, persisting news.

## Decisions

### D1: One request with `limit=10`, filtering in MDH

The provider always requests `limit=10` (the maximum) and follows `next_page_url` with the existing safe pagination helper (with a 10-record page there is normally no second page). It then filters by `date` within `from_date`–`to_date`, by detected category, sorts newest first (stable for equal dates, keeping upstream order), and slices `offset`/`limit`. Requesting fewer than 10 would save nothing (cost is per request) and would make offset pages inconsistent.

Consequence: callers see at most 10 articles; the route reports `has_more: false` as soon as fewer than `limit` remain. This is documented in the route description.

### D2: Field mapping

| `NewsArticle` | Source |
|---|---|
| `article_id` | `financialdatasets:` + first 16 hex digits of SHA-1 of `url` (stable across calls, no native id exists) |
| `title` | `title` |
| `summary` | `""` (field required, API has no summary) |
| `published_at` | `date` at 00:00 UTC. Accept the schema's date-only value and the live ISO 8601 timestamp; for a timestamp, use its UTC calendar date. |
| `source` | `source` |
| `url` | `url` |
| `category` | keyword detection on `title` (D3) |
| `full_text`, `image`, `sentiment` | `null` |

Articles without `title` or `url`, or with an unparseable `date`, are skipped and logged at debug level.

### D3: Shared category detection

Finnhub's `_detect_category` keyword table moves to `app/providers/news_categories.py` as `detect_category(text) -> str | None`; Finnhub keeps its sentiment fallback on top. Financial Datasets uses keyword detection on the title only, so `?category=earnings` works for both providers with the same rules.

### D4: Language

Financial Datasets news has no language parameter and its sources are English. `language` other than `en` returns an empty list without a request, so a German-only query does not spend credit.

### D5: Errors and budget

Same mapping as the other Financial Datasets endpoints: 401/402 → `PROVIDER_NOT_AVAILABLE` with the upstream `message`; 404 → `DATA_NOT_FOUND`; an empty `news` array is an empty result (HTTP 200 with `data: []`), not `DATA_NOT_FOUND`, because a ticker without recent news is a valid answer. Every request passes the request budget; a refused budget raises before any HTTP call.

## Risks / Trade-offs

- **Only 10 articles** → wide date ranges return little. Acceptable for "recent news" use in TradeSensei/VisioTrade; Finnhub stays the provider for depth.
- **Day-level output** → the mapper keeps the date-only contract even when an upstream timestamp is available. Articles for the same UTC day are ordered as delivered. Clients needing an intraday timestamp should use Finnhub.
- **Schema says `ticker` optional, docs say required** → MDH always sends `ticker`, so both readings are satisfied.

## Live verification

- **Live check, 2026-11-20:** One authenticated `GET /news?ticker=AAPL&limit=10` returned HTTP 200 with 10 records. The response only contained `news`, each article had the documented field set in aggregate (`ticker`, `title`, `source`, `date`, `url`), and no `next_page_url` was present. No additional fields were observed.
- **Schema discrepancy confirmed:** A follow-up request approved by the user found that all 10 `date` values were ISO 8601 UTC timestamps (for example `2026-11-20T16:42:26+00:00`). MDH accepts both formats and maps them to 00:00 UTC on the publication day. The pinned schema and its compliant fixtures are unchanged; a separate regression test covers the live format.
- The restarted local MDH (1.7.0) lists `financialdatasets` under `available.news`; `market-data-hub.framas.cloud` (1.6.0) does not. The user approved a local acceptance check in place of the public deployment smoke test.
- **Local acceptance passed, 2026-11-20:** A temporary MDH 1.7.0 container with the updated parser, the configured credential and the local shared Redis budget served `GET /companies/AAPL/news?provider=financialdatasets` with HTTP 200 and 10 articles. With the response cache bypassed, the day budget went from 1 to 2 and the month budget from 34 to 35. The original local container was not restarted and the public instance was not changed.
