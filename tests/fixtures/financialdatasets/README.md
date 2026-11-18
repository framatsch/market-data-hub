# Financial Datasets contract fixtures

`openapi.json` is an unmodified copy of the published OpenAPI 3.0.1 document
from <https://www.financialdatasets.ai/openapi.json>, pinned 17 November 2026.

All other JSON files are **synthetic, schema-conformant responses**, not live
market data. No API key or paid credit was used. They cover multiple filings
per report period, every filing window (including null), cursor pagination,
day/week prices, a price snapshot, company facts and 401/402/404 errors.

Two shapes follow the live API (checked 18 November 2026), not the schema text:
price `time` is a bare date (`"2026-11-16"`), and weekly bars are labelled by
the Sunday that closes the week. Later 8-K filings also repeat prior-year
periods as comparatives, which the earnings fixture includes.

`tests/test_financialdatasets_contract.py` resolves local `$ref` and converts
OpenAPI `nullable` before JSON Schema validation. It also validates upstream
requests and pins the supported filing-window enum so schema drift is visible.
