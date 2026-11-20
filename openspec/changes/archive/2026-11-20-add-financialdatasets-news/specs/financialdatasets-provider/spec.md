## MODIFIED Requirements

### Requirement: Financial Datasets provider registration
The system SHALL provide a provider `financialdatasets` that implements the earnings history capability, the price capability, the company capability and the news capability. It SHALL be part of the known providers, disabled by default, enabled and configured in the Admin UI like other providers, and SHALL send its credential `api_key` from the encrypted key store as header `X-API-KEY` to `https://api.financialdatasets.ai`. `GET /api/admin/providers` SHALL list its capabilities as `["prices", "companies", "earnings_history", "news"]`. Its request budget (see `alphavantage-provider`) SHALL default to 0 per day and 1000 per month, which is USD 20 at USD 0.02 per request.

#### Scenario: Enable with a key
- **WHEN** an admin stores an `api_key` for `financialdatasets` and enables the provider
- **THEN** the registry loads it without a restart and lists it under `price`, `company`, `earnings` and `news`

#### Scenario: Missing credit or key
- **WHEN** Financial Datasets answers HTTP 402 `Payment required`
- **THEN** the request fails with `PROVIDER_NOT_AVAILABLE` and a message that the key is missing or the credit is used up

#### Scenario: Default news provider
- **WHEN** `financialdatasets` is enabled
- **THEN** it is offered in `GET /providers` under `available.news` and can be selected as `default_news_provider`

### Requirement: Financial Datasets errors
HTTP 401 and 402 SHALL map to `PROVIDER_NOT_AVAILABLE` with the `message` of the error body; 404 or an empty result for a ticker SHALL be `DATA_NOT_FOUND`, except that an empty company news result SHALL succeed with no articles. Other HTTP errors SHALL use the shared mapping `map_httpx_http_error`. Every request SHALL pass through the provider's request budget.

#### Scenario: Unknown ticker
- **WHEN** Financial Datasets answers 404 for a ticker
- **THEN** the request fails with `DATA_NOT_FOUND`

## ADDED Requirements

### Requirement: Company news from Financial Datasets
`get_company_news` SHALL request `GET /news` with `ticker=<root>` and `limit=10`, following `next_page_url` with the provider's safe pagination, and map each article to `NewsArticle`: `article_id` `financialdatasets:` followed by the first 16 hexadecimal digits of the SHA-1 of `url`, `title`, `summary` `""`, `published_at` at 00:00 UTC on the publication day, `source`, `url`, `category` detected from the title with the shared keyword rules also used by Finnhub, and `full_text`, `image`, `sentiment` `null`. The mapper SHALL accept both the documented ISO date and the live upstream ISO 8601 timestamp in `date`; for timestamps the publication day SHALL be the UTC calendar date. Articles without `title` or `url` or with an invalid `date` SHALL be skipped. The provider SHALL then keep articles whose publication day lies within `from_date` and `to_date`, apply the `category` filter, sort newest first (keeping upstream order for equal dates) and apply `offset` and `limit` locally. A `language` other than `en` SHALL return an empty list without a request. An empty `news` array SHALL be an empty result; 401, 402 and 404 SHALL map as for the other Financial Datasets endpoints, and every request SHALL pass through the request budget.

#### Scenario: Recent news
- **WHEN** `GET /companies/AAPL/news?provider=financialdatasets` is requested
- **THEN** the provider sends one request `/news?ticker=AAPL&limit=10` and returns at most 10 articles from the last 30 days, newest first, each with `article_id` starting with `financialdatasets:`

#### Scenario: Stable article id
- **WHEN** the same article is returned by two calls
- **THEN** both responses carry the same `article_id`

#### Scenario: Upstream publication timestamp
- **WHEN** the upstream `date` is `2026-11-20T16:42:26+00:00`
- **THEN** the article is included for the publication day `2026-11-20` and `published_at` is `2026-11-20T00:00:00Z`

#### Scenario: Date range applied locally
- **WHEN** news for `from_date=2026-11-10` and `to_date=2026-11-12` is requested and the upstream articles span 2026-11-05 to 2026-11-18
- **THEN** only articles dated 2026-11-10 through 2026-11-12 are returned

#### Scenario: Offset beyond the upstream window
- **WHEN** news is requested with `offset=10`
- **THEN** the result is an empty list

#### Scenario: Category filter
- **WHEN** news is requested with `category=earnings`
- **THEN** only articles whose title matches the earnings keywords are returned

#### Scenario: Non-English language
- **WHEN** news is requested with `language=de`
- **THEN** the result is an empty list and no request is sent to Financial Datasets

#### Scenario: Ticker without news
- **WHEN** Financial Datasets answers with an empty `news` array
- **THEN** the endpoint returns HTTP 200 with `data: []`

#### Scenario: Budget exhausted
- **WHEN** the Financial Datasets request budget is used up
- **THEN** the news request is refused before any HTTP call

### Requirement: Contract coverage for news
The contract test SHALL validate the news fixtures against the `NewsResponse` schema and the news request the provider builds (path `/news`, `ticker`, `limit` not above 10, header `X-API-KEY`) against the pinned OpenAPI document.

#### Scenario: Limit above the schema maximum
- **WHEN** the provider would build a news request with `limit=20`
- **THEN** the contract test fails
