## 1. Preparation

- [x] 1.1 One live request `GET /news?ticker=AAPL&limit=10` (one paid request, key from the encrypted store or `tmp/.env`, never committed); record in `design.md` whether fields beyond the schema exist and whether `next_page_url` appears
- [x] 1.2 Synthetic, schema-conformant fixtures in `tests/fixtures/financialdatasets/`: `news.json` (10 articles over several dates, one without `url`), `news_empty.json`; update the fixture README

## 2. Shared category detection

- [x] 2.1 `app/providers/news_categories.py`: `detect_category(text)` with the keyword table from `finnhub.py`; Finnhub uses it and keeps its sentiment fallback
- [x] 2.2 Unit tests: existing Finnhub category tests unchanged, new tests for title-only detection

## 3. Provider

- [x] 3.1 `FinancialDatasetsProvider` implements `BaseNewsProvider.get_company_news`: language check (D4), `/news` with `ticker=<root>` and `limit=10` via `_pages(..., field="news")`, mapping (D2), skip invalid articles, date/category filter, newest-first sort, `offset`/`limit` slicing
- [x] 3.2 Error handling per D5; empty `news` → `[]`
- [x] 3.3 Unit tests: mapping and `article_id` stability, date filter, category filter, offset beyond 10 → `[]`, `language=de` without request, 402 → `PROVIDER_NOT_AVAILABLE`, 404 → `DATA_NOT_FOUND`, budget refusal without request, metric increment

## 4. Registration and texts

- [x] 4.1 `app/api/routes_admin.py`: `PROVIDER_CAPABILITIES["financialdatasets"]` adds `news`; test that `GET /api/admin/providers` lists it and that the registry offers it under `news` / `GET /providers` `available.news`
- [x] 4.2 Provider hint texts in `app/api/routes_companies.py` and `app/api/mcp.py` add `financialdatasets`; route description notes the 10-article limit
- [x] 4.3 Admin UI: verify that the `News` chip and the `default_news_provider` dropdown show `financialdatasets` (no code change expected)

## 5. Contract and verification

- [x] 5.1 `tests/test_financialdatasets_contract.py`: validate the news fixtures against `NewsResponse` and the built news request (path, `ticker`, `limit ≤ 10`, header) against the pinned document
- [x] 5.2 Full test suite and lint green
- [x] 5.3 User-approved local deployment check: `GET /companies/AAPL/news?provider=financialdatasets` on the updated local MDH returns articles and the budget usage increases by one (public deployment deferred)
