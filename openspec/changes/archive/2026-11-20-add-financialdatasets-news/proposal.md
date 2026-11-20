## Why

Financial Datasets is already enabled for prices, company facts and earnings history, and its API also offers company news (`GET /news`, docs `https://docs.financialdatasets.ai/api/news/company`). Today `GET /companies/{symbol}/news` and the MCP tool `get_company_news` can only use Finnhub, IBKR or the mock provider. Adding news to the existing Financial Datasets provider gives TradeSensei and VisioTrade a second news source on the same key and pay-per-request credit (USD 0.02 per request), with no additional subscription.

## What Changes

- `FinancialDatasetsProvider` additionally implements `BaseNewsProvider`: `get_company_news` requests `GET /news?ticker=<root>&limit=10` and maps each article (`title`, `source`, `date`, `url`) to `NewsArticle`.
- The upstream endpoint has no date range, offset, language or category parameter and returns at most 10 recent articles per ticker. MDH applies the date range, category, `offset` and `limit` locally on those 10 articles; a non-English `language` is answered with an empty list without a provider request.
- `article_id` is derived from the article URL (`financialdatasets:<sha1(url)[:16]>`), `summary` is empty, `published_at` is the publication date at 00:00 UTC (accepting both the documented date and the live timestamp), and `category` is detected from the title with the keyword rules already used for Finnhub (moved to a shared helper).
- Capability `news` for `financialdatasets` in the admin provider list, the static capability map, `GET /providers` (`available.news`) and the `default_news_provider` dropdown.
- Every news request passes through the existing Financial Datasets request budget; the route cache (`CACHE_TTL_COMPANY_NEWS_SECONDS`) keeps repeated calls free.
- Provider hint texts of the news route and MCP tool list `financialdatasets`.
- Contract test: news fixture and news request validated against the pinned OpenAPI copy.

## Capabilities

### New Capabilities
- none

### Modified Capabilities
- `financialdatasets-provider`: registration lists the news capability; new requirement for company news (request, mapping, local filtering, budget, errors).

## Impact

- **Code**: `app/providers/financialdatasets.py` (news interface), `app/providers/news_categories.py` (new shared keyword detection, used by `finnhub.py` too), `app/api/routes_admin.py` (`PROVIDER_CAPABILITIES`), `app/api/routes_companies.py` and `app/api/mcp.py` (provider hint texts), tests and fixtures under `tests/fixtures/financialdatasets/`.
- **API**: additive; new provider value `financialdatasets` for the news endpoint and MCP tool. Responses keep the existing `NewsResponse` shape.
- **Dependencies**: none.
- **Costs**: USD 0.02 per uncached news request, counted against the existing budget (default 1,000 per month).
- **Not covered**: broad market news (`/news` without `ticker`), more than 10 articles per ticker, article text or summaries, a news store or background refresh, sentiment.
